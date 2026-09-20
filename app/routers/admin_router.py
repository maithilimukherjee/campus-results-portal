from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
import redis.asyncio as redis

from app.database import get_db
from app.redis_client import get_redis
from app.models import Teacher, ClassTeacher, Result, Student, Payment, PaymentStatus
from app.auth import require_role

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])

# --- Request/Response Schemas ---

class AssignTeacherRequest(BaseModel):
    employee_id: str
    semester: int
    department: str

class AdminPaymentView(BaseModel):
    payment_id: str
    roll_number: str
    full_name: str
    department: str
    semester: int
    amount: float
    status: PaymentStatus
    idempotency_key: str
    created_at: datetime

# ⚡ Added Promote Schema
class PromoteStudentRequest(BaseModel):
    roll_number: str


# --- Endpoints ---

@router.post("/assign-class-teacher")
async def assign_class_teacher(
    payload: AssignTeacherRequest,
    user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    teacher = (await db.execute(select(Teacher).where(Teacher.employee_id == payload.employee_id))).scalar_one_or_none()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found.")

    # Upsert logic to handle reassignment
    existing_assignment = (await db.execute(
        select(ClassTeacher).where(ClassTeacher.semester == payload.semester, ClassTeacher.department == payload.department)
    )).scalar_one_or_none()

    if existing_assignment:
        existing_assignment.teacher_id = teacher.id
    else:
        new_assignment = ClassTeacher(
            teacher_id=teacher.id,
            semester=payload.semester,
            department=payload.department
        )
        db.add(new_assignment)

    await db.commit()
    return {"message": f"Assigned {teacher.full_name} as Class Teacher for Semester {payload.semester} {payload.department}"}


@router.post("/publish-results")
async def admin_publish_results(
    semester: int,
    department: str,
    # background_tasks: BackgroundTasks, # (Uncomment if using the AI Cache Warmer)
    user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    """Admin sets results from draft (False) to published (True)."""
    
    # Update all unpublished results for this semester/department to published
    stmt = update(Result).where(
        Result.semester == semester,
        Result.is_published == False,
        Result.student.has(department=department) 
    ).values(is_published=True)
    
    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        return {"message": "No draft results found to publish."}

    return {"message": f"Successfully published {result.rowcount} grade entries for Semester {semester}."}


@router.get("/payment-requests", response_model=List[AdminPaymentView])
async def list_payment_requests(
    status_filter: Optional[PaymentStatus] = None,
    semester_filter: Optional[int] = None,
    admin_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin-only endpoint to list all student payment records with optional filtering
    by payment status (PENDING, SUCCESS, FAILED) and semester.
    """
    stmt = (
        select(Payment, Student)
        .join(Student, Payment.student_id == Student.id)
    )

    if status_filter:
        stmt = stmt.where(Payment.status == status_filter)
    if semester_filter:
        stmt = stmt.where(Payment.semester == semester_filter)

    stmt = stmt.order_by(Payment.created_at.desc())

    result = await db.execute(stmt)
    rows = result.all()

    return [
        AdminPaymentView(
            payment_id=str(payment.id),
            roll_number=student.roll_number,
            full_name=student.full_name,
            department=student.department,
            semester=payment.semester,
            amount=float(payment.amount),
            status=payment.status,
            idempotency_key=payment.idempotency_key,
            created_at=payment.created_at
        )
        for payment, student in rows
    ]


# ⚡ Moved Promotion Endpoint into Admin Router
@router.post("/promote-student", status_code=status.HTTP_200_OK)
async def promote_semester(
    payload: PromoteStudentRequest,
    admin_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin-only endpoint to promote a student.
    Order of operations:
    1. Verify limits (max semester 8).
    2. Check Academics (Must pass all subjects. If 'F', block and require Repeat Fee).
    3. Check Financials (Must have SUCCESS payment for current semester).
    """
    
    # 1. Fetch Student
    student_stmt = select(Student).where(Student.roll_number == payload.roll_number)
    student = (await db.execute(student_stmt)).scalar_one_or_none()

    if not student:
        raise HTTPException(
            status_code=404, 
            detail=f"Student with roll number '{payload.roll_number}' not found."
        )

    # Check bounds (1 to 8)
    if student.current_semester >= 8:
        raise HTTPException(
            status_code=400, 
            detail="Student has already reached the maximum semester (8)."
        )

    current_sem = student.current_semester

    # 2. ACADEMIC GATE (Check this FIRST)
    results_stmt = select(Result).where(
        Result.student_id == student.id,
        Result.semester == current_sem,
        Result.is_published == True
    )
    results = (await db.execute(results_stmt)).scalars().all()

    if not results:
        raise HTTPException(
            status_code=400, 
            detail=f"No published results found for Semester {current_sem}."
        )

    # Check for failing grades
    for result in results:
        if result.grade == "F": 
            # Halt promotion, instruct admin/system to take Repeat Fee
            raise HTTPException(
                status_code=400, 
                detail=f"Student failed subject {result.subject_code}. Promotion denied. Repeat semester fee payment required."
            )

    # 3. FINANCIAL GATE (Only checked if they actually passed)
    payment_stmt = select(Payment).where(
        Payment.student_id == student.id,
        Payment.semester == current_sem,
        Payment.status == PaymentStatus.SUCCESS
    )
    has_paid = (await db.execute(payment_stmt)).scalars().first()
    
    if not has_paid:
        raise HTTPException(
            status_code=402, 
            detail=f"Pending fee clearance for Semester {current_sem}. Please ensure fees are paid before promotion."
        )

    # 4. PROMOTE STUDENT
    student.current_semester += 1
    await db.commit()

    return {
        "message": f"Successfully promoted {student.full_name} ({student.roll_number}).",
        "previous_semester": current_sem,
        "new_semester": student.current_semester,
        "status": "PROMOTED"
    }
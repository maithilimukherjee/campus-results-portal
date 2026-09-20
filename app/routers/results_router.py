import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import redis.asyncio as redis
 
from app.database import get_db
from app.redis_client import get_redis
from app.models import Student, Teacher, ClassTeacher, Result, Payment, PaymentStatus
from app.auth import get_current_user, require_role
 
router = APIRouter(prefix="/api/v1/results", tags=["Results"])
 
# --- Request Schemas ---
 
class MarkEntry(BaseModel):
    roll_number: str
    subject_code: str
    subject_name: str
    marks_obtained: float
    max_marks: float = 100.0
    grade: str
 
class UploadMarksRequest(BaseModel):
    semester: int
    marks: List[MarkEntry]
 
 
# --- 1. Teacher Endpoint: Upload Marks as Drafts (Class Teacher Only) ---
 
@router.post("/upload-marks", status_code=status.HTTP_201_CREATED)
async def upload_marks(
    payload: UploadMarksRequest,
    user: dict = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db)
):
    """
    Class Teacher endpoint to bulk upload marks as drafts (is_published=False).
    Only the assigned Class Teacher for the given semester and department can upload marks.
    Marks will not be visible to students until published by an Admin.
    """
    user_uid = user.get("uid")
 
    # 1. Verify Teacher Profile
    teacher_stmt = select(Teacher).where(Teacher.user_uid == user_uid)
    teacher = (await db.execute(teacher_stmt)).scalar_one_or_none()
 
    if not teacher:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher profile not found.")
 
    # 2. Verify Class Teacher Assignment for this Semester
    assignment_stmt = select(ClassTeacher).where(
        ClassTeacher.teacher_id == teacher.id,
        ClassTeacher.semester == payload.semester
    )
    assignment = (await db.execute(assignment_stmt)).scalar_one_or_none()
 
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You are not assigned as the Class Teacher for Semester {payload.semester}."
        )
 
    successful_inserts = 0
    errors = []
 
    for entry in payload.marks:
        # 3. Find Student by Roll Number & Validate Department Match
        student_stmt = select(Student).where(Student.roll_number == entry.roll_number)
        student = (await db.execute(student_stmt)).scalar_one_or_none()
 
        if not student:
            errors.append(f"Student with roll number '{entry.roll_number}' not found.")
            continue
 
        if student.department != assignment.department:
            errors.append(f"Student {entry.roll_number} belongs to '{student.department}', not assigned department '{assignment.department}'.")
            continue
 
        # 4. Check for existing result (draft vs published)
        existing_stmt = select(Result).where(
            Result.student_id == student.id,
            Result.semester == payload.semester,
            Result.subject_code == entry.subject_code
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
 
        if existing:
            if existing.is_published:
                errors.append(f"Marks for {entry.roll_number} in {entry.subject_code} are already published and locked.")
            else:
                # Update existing draft
                existing.subject_name = entry.subject_name
                existing.marks_obtained = entry.marks_obtained
                existing.max_marks = entry.max_marks
                existing.grade = entry.grade
                existing.published_by_id = teacher.id
                successful_inserts += 1
            continue
 
        # 5. Insert New Draft Result
        new_result = Result(
            student_id=student.id,
            published_by_id=teacher.id,
            semester=payload.semester,
            subject_code=entry.subject_code,
            subject_name=entry.subject_name,
            marks_obtained=entry.marks_obtained,
            max_marks=entry.max_marks,
            grade=entry.grade,
            is_published=False  # Saved as draft until Admin publishes
        )
        db.add(new_result)
        successful_inserts += 1
 
    await db.commit()
 
    return {
        "message": f"Saved {successful_inserts} draft result records successfully.",
        "errors": errors
    }
 
 
# --- 2. Student Endpoint: View Results (Published Only) ---
 
@router.get("/{semester}")
async def get_student_results(
    semester: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)
):
    """Fetches published semester results. Accessible regardless of payment status."""
    user_uid = user.get("uid")
    user_email = user.get("email", "student@campus.edu")
 
    # 1. JIT Student Profile Auto-Provisioning
    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()
 
    if not student:
        unlinked_stmt = select(Student).where(Student.user_uid.like("mock_%"))
        student = (await db.execute(unlinked_stmt)).scalars().first()
 
        if student:
            student.user_uid = user_uid
        else:
            student = Student(
                user_uid=user_uid,
                roll_number=f"CS{user_uid[:6].upper()}",
                full_name=user_email.split("@")[0].replace(".", " ").title(),
                department="Computer Science",
                current_semester=1  # Default starting semester
            )
            db.add(student)
 
        await db.commit()
        await db.refresh(student)
 
    # 2. Payment Status Check for Requested Semester
    payment_stmt = select(Payment).where(
        Payment.student_id == student.id,
        Payment.semester == semester,
        Payment.status == "SUCCESS"
    )
    has_paid = (await db.execute(payment_stmt)).scalars().first()
    can_download = True if has_paid else False
 
    # 3. Redis Cache Lookup (Cache-Aside Pattern)
    cache_key = f"result:{str(student.id)}:sem:{str(semester)}"
    cached_data = await cache.get(cache_key)
 
    if cached_data:
        return {
            "source": "CACHE_HIT (Redis)",
            "can_download": can_download,
            "data": json.loads(cached_data)
        }
 
    # 4. Database Fallback Query (Only fetches PUBLISHED results)
    results_stmt = select(Result).where(
        Result.student_id == student.id,
        Result.semester == semester,
        Result.is_published == True  # Must be published by Admin
    )
    results = (await db.execute(results_stmt)).scalars().all()
 
    payload = {
        "roll_number": student.roll_number,
        "full_name": student.full_name,
        "semester": semester,
        "subjects": [
            {
                "subject_code": r.subject_code,
                "subject_name": r.subject_name,
                "marks_obtained": float(r.marks_obtained),
                "max_marks": float(r.max_marks),
                "grade": r.grade
            }
            for r in results
        ]
    }
 
    # 5. Populate Redis Cache (24-hour TTL) if published results exist
    if results:
        await cache.set(cache_key, json.dumps(payload), ex=86400)
 
    return {
        "source": "DATABASE_MISS (Neon PostgreSQL)",
        "can_download": can_download,
        "data": payload
    }
 
 
# --- 3. Student Endpoint: Download Grade Card (Gated by Payment & Publication) ---
 
@router.get("/{semester}/download")
async def download_grade_card(
    semester: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Downloads official grade card document. Hard-blocked by payment status and publication status."""
    user_uid = user.get("uid")
 
    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()
 
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student profile not found.")
 
    # 1. Verify Results are Published
    results_stmt = select(Result).where(
        Result.student_id == student.id,
        Result.semester == semester,
        Result.is_published == True
    )
    results = (await db.execute(results_stmt)).scalars().all()
 
    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No published results found for Semester {semester}."
        )
 
    # 2. Hard Payment Gate for this Semester
    payment_stmt = select(Payment).where(
        Payment.student_id == student.id,
        Payment.semester == semester,
        Payment.status == PaymentStatus.SUCCESS
    )
    has_paid = (await db.execute(payment_stmt)).scalars().first()
 
    if not has_paid:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Semester {semester} fee payment required to download official grade card."
        )
 
    return {
        "message": "Grade card generated successfully.",
        "download_url": f"/static/grade_cards/{student.roll_number}_sem{semester}.pdf",
        "student_name": student.full_name,
        "roll_number": student.roll_number,
        "semester": semester,
        "status": "OFFICIAL_PAID_DOCUMENT"
    }
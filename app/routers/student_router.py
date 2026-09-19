from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models import Student, Result, Payment, PaymentStatus
from app.auth import get_current_user

router = APIRouter(prefix="/api/v1/students", tags=["Students"])

@router.post("/promote")
async def promote_semester(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Evaluates eligibility to advance to the next semester."""
    user_uid = user.get("uid")
    student = (await db.execute(select(Student).where(Student.user_uid == user_uid))).scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    if student.current_semester >= 8:
        raise HTTPException(status_code=400, detail="Student has already reached the maximum semester (8).")

    current_sem = student.current_semester

    # 1. Condition: Payment Status = Success for the current semester
    payment_stmt = select(Payment).where(
        Payment.student_id == student.id,
        Payment.semester == current_sem,
        Payment.status == PaymentStatus.SUCCESS
    )
    has_paid = (await db.execute(payment_stmt)).scalars().first()
    
    if not has_paid:
        raise HTTPException(status_code=402, detail=f"Pending fee clearance for Semester {current_sem}.")

    # 2. Condition: Result = Pass (Assuming 'F' is failing grade. Adjust logic to your academic rules)
    results_stmt = select(Result).where(
        Result.student_id == student.id,
        Result.semester == current_sem,
        Result.is_published == True
    )
    results = (await db.execute(results_stmt)).scalars().all()

    if not results:
        raise HTTPException(status_code=400, detail=f"No published results found for Semester {current_sem}.")

    for result in results:
        if result.grade == "F": # Adjust this trigger string based on your grading schema
            raise HTTPException(status_code=400, detail="Student has failing grades and cannot be promoted.")

    # 3. Promote Student
    student.current_semester += 1
    await db.commit()

    return {
        "message": "Promotion successful.",
        "new_semester": student.current_semester,
        "status": "PROMOTED"
    }
import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import redis.asyncio as redis

from app.database import get_db
from app.redis_client import get_redis
from app.models import Student, Teacher, Result, Payment, PaymentStatus
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

class PublishResultsRequest(BaseModel):
    semester: int
    marks: List[MarkEntry]


# --- 1. Teacher Endpoint: Publish Marks (Teacher-Only) ---

@router.post("/publish", status_code=status.HTTP_201_CREATED)
async def publish_results(
    payload: PublishResultsRequest,
    user: dict = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)
):
    """Teacher-only endpoint to bulk upload marks and invalidate stale student caches."""
    user_uid = user.get("uid")

    # 1. Verify Teacher Profile
    teacher_stmt = select(Teacher).where(Teacher.user_uid == user_uid)
    teacher = (await db.execute(teacher_stmt)).scalar_one_or_none()

    if not teacher:
        raise HTTPException(status_code=403, detail="Teacher profile not found.")

    successful_inserts = 0
    errors = []

    for entry in payload.marks:
        # 2. Find Student by Roll Number
        student_stmt = select(Student).where(Student.roll_number == entry.roll_number)
        student = (await db.execute(student_stmt)).scalar_one_or_none()

        if not student:
            errors.append(f"Student {entry.roll_number} not found.")
            continue

        # 3. Check for existing result to prevent duplicates
        existing_stmt = select(Result).where(
            Result.student_id == student.id,
            Result.semester == payload.semester,
            Result.subject_code == entry.subject_code
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()

        if existing:
            errors.append(f"Marks for {entry.roll_number} in {entry.subject_code} already exist.")
            continue

        # 4. Insert Result
        new_result = Result(
            student_id=student.id,
            published_by_id=teacher.id,
            semester=payload.semester,
            subject_code=entry.subject_code,
            subject_name=entry.subject_name,
            marks_obtained=entry.marks_obtained,
            max_marks=entry.max_marks,
            grade=entry.grade
        )
        db.add(new_result)
        successful_inserts += 1

        # ⚡ CRITICAL: Purge student's stale cache for this semester
        cache_key = f"result:{student.id}:sem:{payload.semester}"
        await cache.delete(cache_key)

    await db.commit()

    return {
        "message": f"Published {successful_inserts} result records successfully.",
        "errors": errors
    }


# --- 2. Student Endpoint: View Results (Independent of Payment Status) ---

@router.get("/{semester}")
async def get_student_results(
    semester: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)
):
    """Fetches semester results. Accessible regardless of payment status."""
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
                department="Computer Science"
            )
            db.add(student)

        await db.commit()
        await db.refresh(student)

    # 2. Payment Status Check (Evaluates download capability without blocking results)
    payment_stmt = select(Payment).where(
        Payment.student_id == student.id,
        Payment.status == PaymentStatus.SUCCESS
    )
    has_paid = (await db.execute(payment_stmt)).scalars().first()
    can_download = True if has_paid else False

    # 3. Redis Cache Lookup (Cache-Aside for Academic Marks)
    cache_key = f"result:{student.id}:sem:{semester}"
    cached_data = await cache.get(cache_key)

    if cached_data:
        return {
            "source": "CACHE_HIT (Redis)",
            "can_download": can_download,
            "data": json.loads(cached_data)
        }

    # 4. Database Fallback Query
    results_stmt = select(Result).where(
        Result.student_id == student.id,
        Result.semester == semester
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

    # 5. Populate Redis Cache (24-hour TTL)
    await cache.set(cache_key, json.dumps(payload), ex=86400)

    return {
        "source": "DATABASE_MISS (Neon PostgreSQL)",
        "can_download": can_download,
        "data": payload
    }


# --- 3. Student Endpoint: Download Grade Card (Gated by Payment) ---

@router.get("/{semester}/download")
async def download_grade_card(
    semester: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Downloads official grade card document. Hard-blocked by payment status."""
    user_uid = user.get("uid")

    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    # 🛑 Hard Payment Gate
    payment_stmt = select(Payment).where(
        Payment.student_id == student.id,
        Payment.status == PaymentStatus.SUCCESS
    )
    has_paid = (await db.execute(payment_stmt)).scalars().first()

    if not has_paid:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Semester fee payment required to download official grade card."
        )

    # Fetch academic records for PDF generation / export
    results_stmt = select(Result).where(
        Result.student_id == student.id,
        Result.semester == semester
    )
    results = (await db.execute(results_stmt)).scalars().all()

    return {
        "message": "Grade card generated successfully.",
        "download_url": f"/static/grade_cards/{student.roll_number}_sem{semester}.pdf",
        "student_name": student.full_name,
        "roll_number": student.roll_number,
        "semester": semester,
        "status": "OFFICIAL_PAID_DOCUMENT"
    }
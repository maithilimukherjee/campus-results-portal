import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import redis.asyncio as redis

from app.database import get_db
from app.redis_client import get_redis
from app.models import Student, Result
from app.auth import get_current_user

router = APIRouter(prefix="/api/v1/results", tags=["Results"])

@router.get("/{semester}")
async def get_student_results(
    semester: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)
):
    """Fetches semester results with automatic JIT student profile linking and Redis caching."""
    user_uid = user.get("uid")
    user_email = user.get("email", "student@campus.edu")

    # 1. Fetch Student profile by Firebase UID
    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()

    # ⚡ AUTOMATIC LINKING / JIT PROVISIONING
    if not student:
        # Check if an unlinked seed student exists (e.g., from seed scripts)
        unlinked_stmt = select(Student).where(Student.user_uid.like("mock_%"))
        student = (await db.execute(unlinked_stmt)).scalars().first()

        if student:
            # Auto-link the active user UID to this seed student
            student.user_uid = user_uid
        else:
            # Auto-provision a brand new student profile
            student = Student(
                user_uid=user_uid,
                roll_number=f"CS{user_uid[:6].upper()}",
                full_name=user_email.split("@")[0].replace(".", " ").title(),
                department="Computer Science"
            )
            db.add(student)

        await db.commit()
        await db.refresh(student)

    # 2. Redis Cache Lookup (Cache-Aside Pattern)
    cache_key = f"result:{student.id}:sem:{semester}"
    cached_data = await cache.get(cache_key)

    if cached_data:
        return {
            "source": "CACHE_HIT (Redis)",
            "data": json.loads(cached_data)
        }

    # 3. Database Fallback Query
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

    # 4. Populate Redis Cache (24-hour TTL)
    await cache.set(cache_key, json.dumps(payload), ex=86400)

    return {
        "source": "DATABASE_MISS (Neon PostgreSQL)",
        "data": payload
    }
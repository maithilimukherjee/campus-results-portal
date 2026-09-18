import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import redis.asyncio as redis

from app.database import get_db
from app.redis_client import get_redis
from app.models import Student, Result
from app.auth import get_current_user

router = APIRouter(prefix="/api/v1/results", tags=["Results & Marksheets"])

@router.get("/{semester}")
async def get_my_results(
    semester: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)
):
    """Retrieves student results using the Cache-Aside pattern."""
    user_uid = user.get("uid")
    
    # 1. Look up student profile in DB via Firebase UID
    query = select(Student).where(Student.user_uid == user_uid)
    db_student = (await db.execute(query)).scalar_one_or_none()
    
    if not db_student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Student profile not found. Contact administrator."
        )

    cache_key = f"result:{db_student.id}:sem:{semester}"

    # 2. Redis Lookup (⚡ Sub-5ms Read)
    try:
        cached_result = await cache.get(cache_key)
        if cached_result:
            return {
                "source": "CACHE_HIT (Redis)",
                "data": json.loads(cached_result)
            }
    except Exception as e:
        # Fall back gracefully if cache fails
        pass

    # 3. DB Lookup (🐢 Cache Miss)
    results_query = select(Result).where(
        Result.student_id == db_student.id,
        Result.semester == semester
    )
    results = (await db.execute(results_query)).scalars().all()

    if not results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No results published for Semester {semester}"
        )

    # 4. Serialize payload
    payload = {
        "roll_number": db_student.roll_number,
        "full_name": db_student.full_name,
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

    # 5. Store in Redis with a 24-hour TTL (86,400 seconds)
    try:
        await cache.set(cache_key, json.dumps(payload), ex=86400)
    except Exception:
        pass

    return {
        "source": "DATABASE_MISS (Neon PostgreSQL)",
        "data": payload
    }
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import redis.asyncio as redis

from app.database import get_db
from app.redis_client import get_redis
from app.models import Student, Teacher, Result, Reevaluation, ReevalStatus
from app.auth import get_current_user, require_role

router = APIRouter(prefix="/api/v1/reevaluations", tags=["Re-Evaluations"])


# --- Request/Response Schemas ---

class ReevalRequest(BaseModel):
    result_id: uuid.UUID


# --- Endpoints ---

@router.post("/", status_code=status.HTTP_201_CREATED)
async def submit_reevaluation(
    payload: ReevalRequest,
    idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)
):
    """Submits a re-evaluation request, auto-assigns the subject teacher, and enforces atomic locking."""
    user_uid = user.get("uid")

    # 1. Fetch Student profile
    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Student profile not found"
        )

    # 2. Redis Distributed Lock (prevents duplicate fast-clicking)
    lock_key = f"lock:reeval:{student.id}:{payload.result_id}"
    acquired = await cache.set(lock_key, "locked", nx=True, ex=10)
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Duplicate request in progress. Please wait a moment."
        )

    try:
        # 3. Verify target Result exists
        result_stmt = select(Result).where(Result.id == payload.result_id)
        result_rec = (await db.execute(result_stmt)).scalar_one_or_none()
        if not result_rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Result record not found"
            )

        # 4. Check if re-evaluation request was already submitted
        existing_stmt = select(Reevaluation).where(
            Reevaluation.student_id == student.id,
            Reevaluation.result_id == payload.result_id
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing:
            return {
                "message": "Re-evaluation request already exists for this subject.",
                "reevaluation_id": str(existing.id),
                "assigned_teacher_id": str(existing.assigned_teacher_id) if existing.assigned_teacher_id else None,
                "status": existing.status
            }

        # 5. Create new Reevaluation record (Auto-mapping published_by_id to assigned_teacher_id)
        new_reeval = Reevaluation(
            idempotency_key=idempotency_key,
            student_id=student.id,
            result_id=payload.result_id,
            assigned_teacher_id=result_rec.published_by_id,  # 🎯 Subject-specific routing
            status=ReevalStatus.SUBMITTED
        )
        db.add(new_reeval)
        await db.commit()
        await db.refresh(new_reeval)

        return {
            "message": "Re-evaluation request submitted successfully",
            "reevaluation_id": str(new_reeval.id),
            "assigned_teacher_id": str(new_reeval.assigned_teacher_id) if new_reeval.assigned_teacher_id else None,
            "status": new_reeval.status
        }

    finally:
        # Release short-lived lock
        await cache.delete(lock_key)


@router.get("/my-requests")
async def get_student_reevaluations(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Fetches all re-evaluation requests submitted by the currently logged-in student."""
    user_uid = user.get("uid")

    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Student profile not found"
        )

    stmt = select(Reevaluation).options(selectinload(Reevaluation.result)).where(
        Reevaluation.student_id == student.id
    )
    requests = (await db.execute(stmt)).scalars().all()

    return {
        "student_id": str(student.id),
        "count": len(requests),
        "reevaluations": [
            {
                "reevaluation_id": str(r.id),
                "result_id": str(r.result_id),
                "subject_code": r.result.subject_code if r.result else None,
                "subject_name": r.result.subject_name if r.result else None,
                "status": r.status,
                "updated_marks": float(r.updated_marks) if r.updated_marks is not None else None,
                "created_at": r.created_at
            }
            for r in requests
        ]
    }


@router.get("/assigned")
async def get_teacher_assigned_reevaluations(
    user: dict = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db)
):
    """Fetches re-evaluation requests specifically assigned to the logged-in teacher."""
    user_uid = user.get("uid")

    teacher_stmt = select(Teacher).where(Teacher.user_uid == user_uid)
    teacher = (await db.execute(teacher_stmt)).scalar_one_or_none()
    if not teacher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Teacher profile not found"
        )

    stmt = select(Reevaluation).options(
        selectinload(Reevaluation.student),
        selectinload(Reevaluation.result)
    ).where(
        Reevaluation.assigned_teacher_id == teacher.id
    )
    assigned_requests = (await db.execute(stmt)).scalars().all()

    return {
        "teacher_id": str(teacher.id),
        "teacher_name": teacher.full_name,
        "department": teacher.department,
        "count": len(assigned_requests),
        "requests": [
            {
                "reevaluation_id": str(r.id),
                "student_name": r.student.full_name if r.student else None,
                "roll_number": r.student.roll_number if r.student else None,
                "subject_code": r.result.subject_code if r.result else None,
                "subject_name": r.result.subject_name if r.result else None,
                "original_marks": float(r.result.marks_obtained) if r.result else None,
                "status": r.status,
                "created_at": r.created_at
            }
            for r in assigned_requests
        ]
    }
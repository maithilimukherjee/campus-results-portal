from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
import redis.asyncio as redis

from app.database import get_db
from app.redis_client import get_redis
from app.models import Teacher, ClassTeacher, Result
from app.auth import require_role

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])

class AssignTeacherRequest(BaseModel):
    employee_id: str
    semester: int
    department: str

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

    # background_tasks.add_task(warm_result_cache, semester, db, cache) # Trigger pre-warmer here

    return {"message": f"Successfully published {result.rowcount} grade entries for Semester {semester}."}
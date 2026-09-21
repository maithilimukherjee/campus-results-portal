import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import redis.asyncio as redis
 
from app.database import get_db
from app.redis_client import get_redis
from app.models import Student, Teacher, ClassTeacher, Result, Payment, PaymentStatus, ReevaluationStatus
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

# --- Additional Request Schemas ---
 
class ReevaluationRequest(BaseModel):

    subject_code: str
 
class CompleteReevaluationRequest(BaseModel):

    roll_number: str

    semester: int

    subject_code: str

    new_marks_obtained: float

    new_grade: str
 
 

 
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
 
    # ⚡ REMOVED: Database query checking the Payment table
 
    # 2. Redis Cache Lookup (Cache-Aside Pattern)
    cache_key = f"result:{str(student.id)}:sem:{str(semester)}"
    cached_data = await cache.get(cache_key)
 
    if cached_data:
        return {
            "source": "CACHE_HIT (Redis)",
            "can_download": True, # Always True
            "data": json.loads(cached_data)
        }
 
    # 3. Database Fallback Query (Only fetches PUBLISHED results)
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
 
    # 4. Populate Redis Cache (24-hour TTL) if published results exist
    if results:
        await cache.set(cache_key, json.dumps(payload), ex=86400)
 
    return {
        "source": "DATABASE_MISS (Neon PostgreSQL)",
        "can_download": True, # Always True
        "data": payload
    }
 
 
# --- 3. Student Endpoint: Download Grade Card (Gated by Publication ONLY) ---
 
@router.get("/{semester}/download")
async def download_grade_card(
    semester: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Downloads official grade card document. Only blocked by publication status."""
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
 
    # ⚡ REMOVED: The Hard Payment Gate blocking document generation

    return {
        "message": "Grade card generated successfully.",
        "download_url": f"/static/grade_cards/{student.roll_number}_sem{semester}.pdf",
        "student_name": student.full_name,
        "roll_number": student.roll_number,
        "semester": semester,
        "status": "OFFICIAL_DOCUMENT" # Removed 'PAID' from status string
    }


# --- 4. Student Endpoint: Request Reevaluation ---
@router.post("/{semester}/request-reevaluation", status_code=status.HTTP_200_OK)
async def request_reevaluation(
    semester: int,
    payload: ReevaluationRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Student requests reevaluation for a specific subject. Strictly limited to one attempt."""
    user_uid = user.get("uid")
    
    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()
    
    if not student:
        raise HTTPException(status_code=404, detail="Student not found.")

    result_stmt = select(Result).where(
        Result.student_id == student.id,
        Result.semester == semester,
        Result.subject_code == payload.subject_code,
        Result.is_published == True
    )
    result = (await db.execute(result_stmt)).scalar_one_or_none()

    if not result:
        raise HTTPException(status_code=404, detail="Published result not found for this subject.")

    # Enforce "At most once" rule
    if result.reevaluation_status != ReevaluationStatus.NONE:
        raise HTTPException(
            status_code=400, 
            detail=f"Reevaluation for {payload.subject_code} has already been requested or completed."
        )

    result.reevaluation_status = ReevaluationStatus.REQUESTED
    await db.commit()

    return {
        "message": f"Reevaluation requested successfully for {payload.subject_code}.",
        "status": result.reevaluation_status
    }


# --- 5. Teacher Endpoint: View Pending Reevaluations ---

@router.get("/reevaluations/pending")
async def get_pending_reevaluations(
    semester: int,
    user: dict = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db)
):
    """Class teacher fetches all pending reevaluation requests for their assigned class."""
    user_uid = user.get("uid")
    
    teacher_stmt = select(Teacher).where(Teacher.user_uid == user_uid)
    teacher = (await db.execute(teacher_stmt)).scalar_one_or_none()

    assignment_stmt = select(ClassTeacher).where(
        ClassTeacher.teacher_id == teacher.id,
        ClassTeacher.semester == semester
    )
    assignment = (await db.execute(assignment_stmt)).scalar_one_or_none()

    if not assignment:
        raise HTTPException(status_code=403, detail="Not assigned as Class Teacher for this semester.")

    # Fetch REQUESTED results for students in this teacher's assigned department
    pending_stmt = (
        select(Result, Student)
        .join(Student, Result.student_id == Student.id)
        .where(
            Result.semester == semester,
            Result.reevaluation_status == ReevaluationStatus.REQUESTED,
            Student.department == assignment.department
        )
    )
    
    rows = (await db.execute(pending_stmt)).all()
    
    return [
        {
            "roll_number": student.roll_number,
            "student_name": student.full_name,
            "subject_code": result.subject_code,
            "current_marks": result.marks_obtained,
            "current_grade": result.grade
        }
        for result, student in rows
    ]


# --- 6. Teacher Endpoint: Complete Reevaluation ---

@router.post("/reevaluations/complete", status_code=status.HTTP_200_OK)
async def complete_reevaluation(
    payload: CompleteReevaluationRequest,
    user: dict = Depends(require_role("teacher")),
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis) # ⚡ Required to purge stale cache
):
    """Class teacher submits updated marks. Updates DB and forcefully invalidates Redis cache."""
    user_uid = user.get("uid")
    
    teacher = (await db.execute(select(Teacher).where(Teacher.user_uid == user_uid))).scalar_one_or_none()
    student = (await db.execute(select(Student).where(Student.roll_number == payload.roll_number))).scalar_one_or_none()

    if not student or not teacher:
        raise HTTPException(status_code=404, detail="Entity not found.")

    # Validate Teacher Assignment
    assignment = (await db.execute(select(ClassTeacher).where(
        ClassTeacher.teacher_id == teacher.id,
        ClassTeacher.semester == payload.semester,
        ClassTeacher.department == student.department
    ))).scalar_one_or_none()

    if not assignment:
        raise HTTPException(status_code=403, detail="Unauthorized to reevaluate this student.")

    # Find the specific requested result
    result = (await db.execute(select(Result).where(
        Result.student_id == student.id,
        Result.semester == payload.semester,
        Result.subject_code == payload.subject_code,
        Result.reevaluation_status == ReevaluationStatus.REQUESTED
    ))).scalar_one_or_none()

    if not result:
        raise HTTPException(status_code=404, detail="No pending reevaluation request found for this subject.")

    # 1. Update the Database Ledger
    result.original_marks = result.marks_obtained # Save audit trail
    result.marks_obtained = payload.new_marks_obtained
    result.grade = payload.new_grade
    result.reevaluation_status = ReevaluationStatus.COMPLETED
    
    await db.commit()

    # 2. ⚡ CACHE INVALIDATION: Forcefully delete the student's old result cache
    cache_key = f"result:{str(student.id)}:sem:{str(payload.semester)}"
    await cache.delete(cache_key)

    return {
        "message": "Reevaluation completed successfully. New grade card is available.",
        "roll_number": student.roll_number,
        "subject_code": result.subject_code,
        "new_grade": result.grade
    }


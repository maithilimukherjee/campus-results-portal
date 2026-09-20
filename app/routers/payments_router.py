import uuid
import redis.asyncio as redis
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.redis_client import get_redis
from app.models import Student, Payment, PaymentStatus
from app.auth import get_current_user, require_role

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])

# --- Request Schemas ---

class InitiatePaymentRequest(BaseModel):
    amount: float
    purpose: str
    semester: Optional[int] = None  

class UpdatePaymentStatusRequest(BaseModel):
    payment_id: str
    status: PaymentStatus

# --- Endpoints ---

@router.post("/initiate", status_code=status.HTTP_201_CREATED)
async def initiate_payment(
    payload: InitiatePaymentRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Initiates payment. The idempotency key is deterministically generated 
    based on the year, roll number, and semester to prevent duplicate payments.
    """
    user_uid = user.get("uid")

    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    target_semester = payload.semester if payload.semester is not None else student.current_semester

    current_year = datetime.now().year
    deterministic_key = f"FEE_{current_year}_{student.roll_number}_SEM{target_semester}"

    existing_stmt = select(Payment).where(Payment.idempotency_key == deterministic_key)
    existing_payment = (await db.execute(existing_stmt)).scalar_one_or_none()

    if existing_payment:
        if existing_payment.status == PaymentStatus.SUCCESS:
            return {
                "message": f"Payment for Semester {target_semester} has already been paid successfully.",
                "payment_id": str(existing_payment.id),
                "status": existing_payment.status,
                "semester": existing_payment.semester
            }
        
        return {
            "message": "Payment intent already exists for this semester.",
            "payment_id": str(existing_payment.id),
            "status": existing_payment.status,
            "semester": existing_payment.semester
        }

    new_payment = Payment(
        idempotency_key=deterministic_key,
        student_id=student.id,
        semester=target_semester,
        amount=payload.amount,
        status=PaymentStatus.PENDING
    )
    db.add(new_payment)
    await db.commit()
    await db.refresh(new_payment)

    return {
        "message": "Payment initiated successfully.",
        "payment_id": str(new_payment.id),
        "status": new_payment.status,
        "semester": new_payment.semester,
        "idempotency_key_used": deterministic_key
    }


# SECURED WEBHOOK (Admin Only)
@router.post("/callback", status_code=status.HTTP_200_OK)
async def payment_callback(
    payload: UpdatePaymentStatusRequest,
    admin_user: dict = Depends(require_role("admin")), # Strict Admin Gate Added
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)
):
    """
    Callback endpoint to update payment status and automatically invalidate 
    stale Redis cache keys. 
    LOCKED: Only accessible by users with the 'admin' role.
    """
    payment_uuid = uuid.UUID(payload.payment_id)
    payment_stmt = select(Payment).where(Payment.id == payment_uuid)
    payment = (await db.execute(payment_stmt)).scalar_one_or_none()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found.")

    if payment.status == payload.status:
        return {
            "message": f"Payment is already marked as {payment.status}",
            "payment_id": str(payment.id),
            "new_status": payment.status
        }

    payment.status = payload.status
    await db.commit()

    if payload.status == PaymentStatus.SUCCESS:
        cache_key = f"result:{payment.student_id}:sem:{payment.semester}"
        await cache.delete(cache_key)

    return {
        "message": "Payment status updated",
        "payment_id": str(payment.id),
        "new_status": payment.status
    }
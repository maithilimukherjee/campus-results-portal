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
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)  # ⚡ Added Redis for double-click prevention
):
    """
    Initiates payment. The idempotency key is deterministically generated.
    Includes failure recovery: if previous attempts failed, it generates a new attempt.
    """
    user_uid = user.get("uid")

    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found.")

    target_semester = payload.semester if payload.semester is not None else student.current_semester
    current_year = datetime.now().year
    
    # 1. Base Deterministic Key (e.g., FEE_2026_CS001_SEM1)
    base_key = f"FEE_{current_year}_{student.roll_number}_SEM{target_semester}"

    # 2. REDIS LOCK: Prevent rapid double-clicks (10-second window)
    lock_key = f"lock:init_pay:{student.id}:{base_key}"
    acquired = await cache.set(lock_key, "processing", nx=True, ex=10)
    
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Payment request is already processing. Please do not refresh."
        )

    try:
        # 3. Idempotency Check & Failure Recovery (Wildcard Search)
        existing_stmt = select(Payment).where(Payment.idempotency_key.like(f"{base_key}%"))
        existing_payments = (await db.execute(existing_stmt)).scalars().all()

        if existing_payments:
            for ep in existing_payments:
                if ep.status == PaymentStatus.SUCCESS:
                    return {
                        "message": f"Payment for Semester {target_semester} has already been paid successfully.",
                        "payment_id": str(ep.id),
                        "status": ep.status,
                        "semester": ep.semester
                    }
                if ep.status == PaymentStatus.PENDING:
                    return {
                        "message": "You have an active pending payment intent.",
                        "payment_id": str(ep.id),
                        "status": ep.status,
                        "semester": ep.semester
                    }
            
            # ⚡ FAILURE RECOVERY: All previous attempts failed.
            # Append an attempt counter so they aren't permanently locked out.
            attempt_count = len(existing_payments) + 1
            final_idempotency_key = f"{base_key}_ATTEMPT_{attempt_count}"
        else:
            # First time trying to pay this fee
            final_idempotency_key = base_key

        # 4. Insert New Pending Payment
        new_payment = Payment(
            idempotency_key=final_idempotency_key,
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
            "idempotency_key_used": final_idempotency_key
        }

    finally:
        # 5. ALWAYS release the Redis Lock so they can try again safely
        await cache.delete(lock_key)


# --- SECURED WEBHOOK (Admin Only) ---
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
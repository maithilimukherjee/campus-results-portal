import uuid
from typing import Optional
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import redis.asyncio as redis

from app.database import get_db
from app.redis_client import get_redis
from app.models import Student, Payment, PaymentStatus
from app.auth import get_current_user

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])

# --- Request Schemas ---
class PaymentInitiateRequest(BaseModel):
    amount: Decimal
    purpose: str = "SEMESTER_FEE"

class PaymentWebhookRequest(BaseModel):
    payment_id: uuid.UUID
    gateway_status: str  # "SUCCESS" or "FAILED"

# --- Endpoints ---

@router.post("/initiate", status_code=status.HTTP_201_CREATED)
async def initiate_payment(
    payload: PaymentInitiateRequest,
    idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key", description="Auto-generated if left blank"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cache: redis.Redis = Depends(get_redis)
):
    """
    Initiates payment. If X-Idempotency-Key header is omitted, 
    the backend automatically generates a unique UUIDv4.
    """
    user_uid = user.get("uid")

    # ⚡ Auto-generate idempotency key if not provided by client
    if not idempotency_key:
        idempotency_key = str(uuid.uuid4())

    # 1. Fetch Student profile
    student_stmt = select(Student).where(Student.user_uid == user_uid)
    student = (await db.execute(student_stmt)).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student profile not found")

    # 2. REDIS LOCK: Prevent duplicate rapid clicks (10-second window)
    lock_key = f"lock:payment:{student.id}:{idempotency_key}"
    acquired = await cache.set(lock_key, "processing", nx=True, ex=10)
    
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Payment request already in progress. Please do not refresh."
        )

    try:
        # 3. DB CHECK: Has this idempotency key been processed before?
        existing_stmt = select(Payment).where(Payment.idempotency_key == idempotency_key)
        existing_payment = (await db.execute(existing_stmt)).scalar_one_or_none()
        
        if existing_payment:
            return {
                "message": "Payment previously initiated (Idempotent response)",
                "payment_id": str(existing_payment.id),
                "status": existing_payment.status,
                "auto_generated_key": idempotency_key
            }

        # 4. Create PENDING ledger entry
        new_payment = Payment(
            idempotency_key=idempotency_key,
            student_id=student.id,
            amount=payload.amount,
            status=PaymentStatus.PENDING
        )
        db.add(new_payment)
        await db.commit()
        await db.refresh(new_payment)

        return {
            "message": "Payment initiated successfully",
            "payment_id": str(new_payment.id),
            "amount": float(new_payment.amount),
            "status": new_payment.status,
            "idempotency_key_used": idempotency_key
        }

    finally:
        # Release the Redis lock
        await cache.delete(lock_key)


@router.post("/webhook")
async def payment_webhook(
    payload: PaymentWebhookRequest,
    db: AsyncSession = Depends(get_db)
):
    """Simulated webhook from gateway to update payment status."""
    payment_stmt = select(Payment).where(Payment.id == payload.payment_id)
    payment = (await db.execute(payment_stmt)).scalar_one_or_none()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found")

    if payment.status != PaymentStatus.PENDING:
        return {"message": f"Payment is already marked as {payment.status}"}

    if payload.gateway_status.upper() == "SUCCESS":
        payment.status = PaymentStatus.SUCCESS
    else:
        payment.status = PaymentStatus.FAILED

    await db.commit()
    await db.refresh(payment)

    return {
        "message": "Payment status updated",
        "payment_id": str(payment.id),
        "new_status": payment.status
    }
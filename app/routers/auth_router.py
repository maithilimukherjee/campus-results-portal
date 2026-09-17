from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from firebase_admin import auth as firebase_auth
from app.auth import get_current_user, require_role

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

class AssignRoleRequest(BaseModel):
    uid: str
    role: str  # "student" or "admin"

@router.get("/me")
def get_user_profile(user: dict = Depends(get_current_user)):
    """Returns profile info and custom claims for the currently logged-in user."""
    return {
        "uid": user.get("uid"),
        "email": user.get("email"),
        "role": user.get("role", "student")
    }

@router.post("/set-role")
def set_user_role(payload: AssignRoleRequest, admin_user: dict = Depends(require_role("admin"))):
    """Sets custom claims (RBAC) on a Firebase user account. (Admin only)"""
    try:
        firebase_auth.set_custom_user_claims(payload.uid, {"role": payload.role})
        return {"message": f"Successfully assigned role '{payload.role}' to UID {payload.uid}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
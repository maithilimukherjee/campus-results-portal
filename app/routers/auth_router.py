import os
import requests
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from firebase_admin import auth as firebase_auth
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
 
from app.database import get_db
from app.models import Student, Teacher
from app.auth import get_current_user, require_role
 
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
 
# --- Models ---
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
 
class AssignRoleRequest(BaseModel):
    email: EmailStr
    role: str  # "unassigned", "student", "teacher", "admin"
    full_name: Optional[str] = None
    department: Optional[str] = "Computer Science"
    roll_number: Optional[str] = None  # Optional override for students
    employee_id: Optional[str] = None  # Optional override for teachers
 
class LoginRequest(BaseModel):
    email: EmailStr
    password: str
 
# --- Endpoints ---
 
@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterRequest):
    """Creates a new user and automatically assigns the default 'unassigned' role."""
    try:
        user = firebase_auth.create_user(
            email=payload.email,
            password=payload.password
        )
       
        default_role = "unassigned"
        firebase_auth.set_custom_user_claims(user.uid, {"role": default_role})
       
        return {
            "message": f"Successfully registered {payload.email} with role '{default_role}'",
            "uid": user.uid
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
 
@router.post("/login")
def login_user(payload: LoginRequest):
    """Authenticates a user via Firebase and returns a JWT token."""
    API_KEY = os.getenv("apiKey")
   
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server misconfiguration: API Key missing")
 
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}"
    data = {
        "email": payload.email,
        "password": payload.password,
        "returnSecureToken": True
    }
   
    response = requests.post(url, json=data)
    result = response.json()
   
    if "idToken" in result:
        return {
            "message": "Login successful",
            "access_token": result["idToken"],
            "token_type": "Bearer",
            "expires_in": result["expiresIn"]
        }
    else:
        error_message = result.get("error", {}).get("message", "Unknown error")
        raise HTTPException(status_code=401, detail=f"Login failed: {error_message}")
 
@router.get("/me")
def get_user_profile(user: dict = Depends(get_current_user)):
    """Returns profile info for the currently logged-in user."""
    return {
        "uid": user.get("uid"),
        "email": user.get("email"),
        "role": user.get("role", "unassigned")
    }
 
@router.post("/set-role")
async def set_user_role(
    payload: AssignRoleRequest,
    admin_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    """Admin-only override to change a user's role and automatically provision their Neon DB profile."""
    valid_roles = ["unassigned", "student", "teacher", "admin"]
    if payload.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")
 
    try:
        # 1. Update Custom Claims in Firebase Auth
        target_user = firebase_auth.get_user_by_email(payload.email)
        firebase_auth.set_custom_user_claims(target_user.uid, {"role": payload.role})
       
        user_uid = target_user.uid
        display_name = payload.full_name or target_user.display_name or payload.email.split("@")[0].replace(".", " ").title()
        department = payload.department or "Computer Science"
 
        # 2. Auto-provision into Neon PostgreSQL based on the assigned role
        if payload.role == "student":
            stmt = select(Student).where(Student.user_uid == user_uid)
            existing_student = (await db.execute(stmt)).scalar_one_or_none()
 
            if not existing_student:
                roll = payload.roll_number or f"CS{user_uid[:6].upper()}"
                new_student = Student(
                    user_uid=user_uid,
                    roll_number=roll,
                    full_name=display_name,
                    department=department,
                    current_semester=1  # ⚡ Added default semester 1 for new students
                )
                db.add(new_student)
                await db.commit()
 
        elif payload.role == "teacher":
            stmt = select(Teacher).where(Teacher.user_uid == user_uid)
            existing_teacher = (await db.execute(stmt)).scalar_one_or_none()
 
            if not existing_teacher:
                emp_id = payload.employee_id or f"EMP{user_uid[:6].upper()}"
                new_teacher = Teacher(
                    user_uid=user_uid,
                    employee_id=emp_id,
                    full_name=display_name,
                    department=department
                )
                db.add(new_teacher)
                await db.commit()
 
        return {
            "message": f"Successfully updated {payload.email} to role '{payload.role}' and synced database profile.",
            "uid": user_uid,
            "assigned_role": payload.role
        }
 
    except firebase_auth.UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No account found registered with email '{payload.email}'"
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
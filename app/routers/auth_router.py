from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from firebase_admin import auth as firebase_auth
from app.auth import get_current_user, require_role
import requests
import os       

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

# --- Models ---
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

class AssignRoleRequest(BaseModel):
    email: EmailStr
    role: str

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
def set_user_role(payload: AssignRoleRequest, admin_user: dict = Depends(require_role("admin"))):
    """Admin-only override to change a user's role using their email address."""
    valid_roles = ["unassigned", "student", "teacher", "admin"]
    if payload.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

    try:
        target_user = firebase_auth.get_user_by_email(payload.email)
        firebase_auth.set_custom_user_claims(target_user.uid, {"role": payload.role})
        
        return {
            "message": f"Successfully updated {payload.email} to role '{payload.role}'",
            "uid": target_user.uid
        }
    except firebase_auth.UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No account found registered with email '{payload.email}'"
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
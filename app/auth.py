from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth as firebase_auth
import app.config  # Ensures Firebase app is initialized

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Verifies Firebase JWT token and returns decoded user claims."""
    token = credentials.credentials
    try:
        decoded_token = firebase_auth.verify_id_token(token)
        return decoded_token
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

def require_role(required_role: str):
    """Dependency wrapper for Role-Based Access Control (RBAC)."""
    def role_checker(user: dict = Depends(get_current_user)):
        user_role = user.get("role", "student") 
        if user_role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Requires '{required_role}' role"
            )
        return user
    return role_checker 
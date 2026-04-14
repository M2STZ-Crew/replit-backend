"""
dependencies.py – FastAPI dependency injectors.
These are used in route definitions to enforce authentication and RBAC.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from app.core.security import decode_access_token
from app.db.supabase_client import supabase_admin

# Points FastAPI to the login endpoint for OpenAPI docs
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    Validate JWT and return the current user from the database.
    Raises 401 if token is invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if not payload:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if not user_id:
        raise credentials_exception

    # Fetch user with their role from Supabase
    result = (
        supabase_admin.table("users")
        .select("*, roles(name)")
        .eq("id", user_id)
        .single()
        .execute()
    )

    if not result.data:
        raise credentials_exception

    user = result.data
    if not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive"
        )

    return user


def require_roles(*roles: str):
    """
    Factory that returns a dependency enforcing role-based access.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_roles("super_admin"))])
    """
    async def role_checker(current_user: dict = Depends(get_current_user)):
        user_role = current_user.get("roles", {}).get("name")
        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {list(roles)}"
            )
        return current_user
    return role_checker
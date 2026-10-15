# app/api/routes/auth.py
# EAP-IT35 — Added rate limiting and audit logging
# Rate limit: 5 login attempts per IP per minute
# Audit: LOGIN_SUCCESS and LOGIN_FAIL written to audit_log table

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.schemas.auth import LoginRequest, LoginResponse
from app.services.auth_service import authenticate_user, refresh_user_token
from app.services.audit_service import log_login_success, log_login_failure
from app.core.jwt import create_access_token
from app.models.user import User
from app.api.dependencies import get_current_user, require_permission
from app.core.permission import ADMIN


limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
@limiter.limit("15/minute")
def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    """
    POST /auth/login
    - Rate limited: 5 attempts per IP per minute
    - Audit logged: LOGIN_SUCCESS or LOGIN_FAIL
    - JWT expiry is validated by python-jose on every decode (see dependencies.py)
    """
    ip = request.client.host if request.client else "unknown"

    user = authenticate_user(db, payload.email, payload.password)

    if not user:
        log_login_failure(db, ip_address=ip, reason="invalid_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # US-009: a user an admin has deactivated must not be able to log in, even
    # though their password is still correct.
    if not user.is_active:
        log_login_failure(db, ip_address=ip, reason="account_deactivated")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account has been deactivated.",
        )

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )

    log_login_success(db, user_id=user.id, ip_address=ip)

    return LoginResponse(
        access_token=access_token,
        role=user.role.value,
    )

@router.post("/refresh", response_model=LoginResponse)
def refresh(
    current_user: User = Depends(get_current_user),
):
    """
    POST /auth/refresh
    - get_current_user already returns 401 for a missing/invalid/expired token.
    - get_current_user re-queries the user by email, so role/is_active are current.
    - Returns 401 if the user has since been deactivated (see refresh_user_token).
    """
    token_data = refresh_user_token(current_user)
    return LoginResponse(**token_data)

@router.get("/admin-test")
def admin_test(
    current_user: User = Depends(get_current_user),
):
    require_permission(current_user.role.value, ADMIN)
    return {
        "message": f"Welcome {current_user.email}"
    }


import logging

from app.core.permission import can_access
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.jwt import decode_access_token
from app.models.user import User
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

def require_permission(role: str, resource: str):
    if not can_access(role, resource):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are unauthorized for this section.",
        )

security = HTTPBearer()

def get_session(db: Session = Depends(get_db)):
    return db

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        # IT35-332: decode_access_token now logs the specific reason itself
        # (expired / bad signature / malformed / unexpected) — nothing more
        # to add here, this 401 is just the HTTP-facing consequence of that.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token."
        )
    user = db.query(User).filter(User.email == payload.get("email")).first()
    if not user:
        # IT35-332: a valid, non-expired token whose email no longer matches
        # any user is a different failure than "expired" — worth its own log
        # line, since it points at account changes (e.g. email edited) rather
        # than token/auth-layer timing.
        logger.warning("Token valid but no user found for email=%s", payload.get("email"))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found."
        )

    # US-009: a user deactivated while already logged in still holds a valid token,
    # so blocking them at /auth/login is not enough — reject them here too, on the
    # first request they make after being deactivated.
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account has been deactivated."
        )

    # NOTE: the role is read from this fresh DB row, not from the token, which is
    # what makes an admin's role change take effect on the user's very next request.
    return user


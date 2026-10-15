from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.user import User
from app.core.security import verify_password
from app.core.jwt import create_access_token


def authenticate_user(db: Session, email: str, password: str):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def refresh_user_token(user: User) -> dict:
    """
    Issue a fresh access token for an already-authenticated user.
    `user` is expected to come from get_current_user, which re-fetches
    the row from the DB on every call — so user.role/user.is_active
    are already current.
    Raises 401 if the user has since been deactivated.
    """
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account has been deactivated.",
        )

    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )

    return {
        "access_token": access_token,
        "role": user.role.value,
    }
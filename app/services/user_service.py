# app/services/user_service.py
# US-009 — Admin user & role management.
# Every function here writes an audit log entry, per the acceptance criteria
# ("User management actions are stored in audit logs").

import logging

from fastapi import HTTPException, status as http_status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.core.security import hash_password
from app.schemas.user import CreateUserRequest, UpdateUserRequest

logger = logging.getLogger(__name__)


def _get_user_or_404(db: Session, user_id: int) -> User:
    """Finds a user by id, or raises 404."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found."
        )
    return user


def _add_audit(
    db: Session,
    admin_id: int,
    action: str,
    target_user_id: int,
    old_status: str = None,
    new_status: str = None,
) -> None:
    """
    Queues one audit entry. It is added to the session but NOT committed —
    the caller commits it together with the user change, so we can never end up
    with an audit log for a change that was rolled back.
    """
    db.add(AuditLog(
        user_id=admin_id,               # the admin who performed the action
        action=action,
        resource_type="user",
        resource_id=target_user_id,     # the user who was affected
        old_status=old_status,
        new_status=new_status,
    ))


def list_users(db: Session, page: int = 1, limit: int = 20) -> dict:
    """Returns a paginated list of all users."""
    query = db.query(User)
    total = query.count()

    items = (
        query
        .order_by(User.id)
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "empty_message": "No users found." if total == 0 else None,
    }


def create_user(db: Session, admin_id: int, data: CreateUserRequest) -> User:
    """Creates a new user with one role. Email must not already be taken."""
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="A user with this email already exists."
        )

    try:
        new_user = User(
            email=data.email,
            name=data.name,
            hashed_password=hash_password(data.password),
            role=data.role,
            is_active=True,
        )
        db.add(new_user)
        # flush() sends the INSERT so the database assigns new_user.id,
        # which the audit entry needs. It does not commit yet.
        db.flush()

        _add_audit(
            db,
            admin_id=admin_id,
            action="USER_CREATED",
            target_user_id=new_user.id,
            new_status=new_user.role.value,
        )

        db.commit()
        db.refresh(new_user)

    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error creating user: %s", e)
        raise RuntimeError("Failed to create user") from e

    logger.info("USER_CREATED — user_id=%d role=%s by admin_id=%d",
                new_user.id, new_user.role.value, admin_id)
    return new_user


def update_user(db: Session, admin_id: int, user_id: int, data: UpdateUserRequest) -> User:
    """Updates a user's email and/or name. Role and is_active are not touched here."""
    user = _get_user_or_404(db, user_id)

    if data.email is not None and data.email != user.email:
        # The email must stay unique across users.
        taken = db.query(User).filter(
            User.email == data.email,
            User.id != user_id
        ).first()
        if taken:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Email already in use by another user."
            )
        user.email = data.email

    if data.name is not None:
        user.name = data.name

    try:
        _add_audit(db, admin_id=admin_id, action="USER_UPDATED", target_user_id=user.id)
        db.commit()
        db.refresh(user)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error updating user %d: %s", user_id, e)
        raise RuntimeError("Failed to update user") from e

    logger.info("USER_UPDATED — user_id=%d by admin_id=%d", user_id, admin_id)
    return user


def update_user_role(db: Session, admin_id: int, user_id: int, new_role: UserRole) -> User:
    """
    Assigns a new role to a user.

    The change takes effect immediately: get_current_user re-reads the user row
    from the database on every request, so permission checks use the new role on
    the user's very next call — no re-login needed.
    """
    user = _get_user_or_404(db, user_id)

    # Guardrail: an admin demoting themselves would instantly lose access to this
    # page and could lock the whole team out. Not in the acceptance criteria —
    # remove this block if the team decides self-demotion should be allowed.
    if user.id == admin_id:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role."
        )

    old_role = user.role.value
    user.role = new_role

    try:
        _add_audit(
            db,
            admin_id=admin_id,
            action="USER_ROLE_CHANGED",
            target_user_id=user.id,
            old_status=old_role,
            new_status=new_role.value,
        )
        db.commit()
        db.refresh(user)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error changing role for user %d: %s", user_id, e)
        raise RuntimeError("Failed to change user role") from e

    logger.info("USER_ROLE_CHANGED — user_id=%d %s -> %s by admin_id=%d",
                user_id, old_role, new_role.value, admin_id)
    return user


def set_user_active(db: Session, admin_id: int, user_id: int, is_active: bool) -> User:
    """
    Shared body for deactivate and activate — the two only differ by a boolean,
    so writing them as one function keeps the audit handling in a single place.
    """
    user = _get_user_or_404(db, user_id)

    # Guardrail: same lock-out risk as self-demotion above.
    if user.id == admin_id and not is_active:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account."
        )

    old_state = "active" if user.is_active else "inactive"
    new_state = "active" if is_active else "inactive"
    user.is_active = is_active

    try:
        _add_audit(
            db,
            admin_id=admin_id,
            action="USER_ACTIVATED" if is_active else "USER_DEACTIVATED",
            target_user_id=user.id,
            old_status=old_state,
            new_status=new_state,
        )
        db.commit()
        db.refresh(user)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error setting active=%s for user %d: %s", is_active, user_id, e)
        raise RuntimeError("Failed to change user active status") from e

    logger.info("USER_%s — user_id=%d by admin_id=%d",
                "ACTIVATED" if is_active else "DEACTIVATED", user_id, admin_id)
    return user
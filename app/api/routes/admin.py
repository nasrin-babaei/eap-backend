# app/api/routes/admin.py
# US-009 — Admin user & role management.
# Every user-management endpoint here is admin-only ("Only admins can manage users.").
# US-012 (IT35-310) adds /activity/export, which is also admin-only but keeps its
# own 403 message, same reasoning as request_types.py's separate require_admin.

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User, UserRole
from app.schemas.user import (
    UserResponse,
    UserListResponse,
    CreateUserRequest,
    UpdateUserRequest,
    UpdateRoleRequest,
)
from app.services.user_service import (
    list_users,
    create_user,
    update_user,
    update_user_role,
    set_user_active,
)
from app.services.audit_service import export_my_admin_activity_csv

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency that lets only admins through.
    Declaring it once and reusing it beats repeating the same if-block in all
    five user-management routes below — one place to change if the rule
    ever changes. NOTE: /activity/export below does its own inline check
    instead, because it needs a different 403 message.
    """
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can manage users."
        )
    return current_user


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_endpoint(
    payload: CreateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return create_user(db=db, admin_id=admin.id, data=payload)


@router.get("/users", response_model=UserListResponse)
def list_users_endpoint(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return list_users(db=db, page=page, limit=limit)


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user_endpoint(
    user_id: int,
    payload: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return update_user(db=db, admin_id=admin.id, user_id=user_id, data=payload)


@router.patch("/users/{user_id}/role", response_model=UserResponse)
def update_user_role_endpoint(
    user_id: int,
    payload: UpdateRoleRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return update_user_role(db=db, admin_id=admin.id, user_id=user_id, new_role=payload.role)


@router.patch("/users/{user_id}/deactivate", response_model=UserResponse)
def deactivate_user_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return set_user_active(db=db, admin_id=admin.id, user_id=user_id, is_active=False)


@router.patch("/users/{user_id}/activate", response_model=UserResponse)
def activate_user_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return set_user_active(db=db, admin_id=admin.id, user_id=user_id, is_active=True)


# ============================================================================
# US-012 (IT35-310) — GET /admin/activity/export
# ============================================================================

@router.get("/activity/export")
def export_my_admin_activity(
    start_date: Optional[date] = Query(default=None, description="Inclusive, on timestamp"),
    end_date: Optional[date] = Query(default=None, description="Inclusive, on timestamp"),
    action: Optional[str] = Query(default=None, description="Optional action-type filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    US-012 (IT35-310) — the caller (an admin) downloads their own admin
    activity as CSV. Not the system-wide audit log (US-011) and not the
    request statistics report (US-010) — see
    audit_service.export_my_admin_activity_csv.
    """
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can export admin activity."
        )

    csv_text, row_count = export_my_admin_activity_csv(
        db=db,
        admin_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        action=action,
    )

    filename = f"my-admin-activity-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Decision T — lets the frontend show "N rows exported" as
            # US-012's success confirmation.
            "X-Export-Row-Count": str(row_count),
        },
    )


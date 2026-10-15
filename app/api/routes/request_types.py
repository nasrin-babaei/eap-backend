# app/api/routes/request_types.py
# US-017 (IT35-74) — request types.
#
# Two routers live here on purpose:
#   * router       -> /request-types        readable by EVERY authenticated user
#   * admin_router -> /admin/request-types  admin only
# That split is decision J in openapi-sprint6.yaml: the submission form needs
# the active types, but only an admin may see or change inactive ones.
#
# IT35-308 adds PATCH /{id}, /{id}/deactivate and /{id}/activate to admin_router.

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.request_type import (
    CreateRequestTypeRequest,
    UpdateRequestTypeRequest,
    RequestTypeActionResponse,
    RequestTypeListResponse,
)
from app.services.request_type_service import (
    create_request_type,
    list_request_types,
    update_request_type,
    set_request_type_active,
)

router = APIRouter(prefix="/request-types", tags=["Request Types"])
admin_router = APIRouter(prefix="/admin/request-types", tags=["Admin"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Admin-only gate for the management endpoints.

    admin.py has its own require_admin with the message "Only admins can manage
    users." — the spec asks for a different message here, so this is a separate
    dependency rather than a shared one.
    """
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can manage request types.",
        )
    return current_user


@router.get("", response_model=RequestTypeListResponse)
def list_request_types_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    The list the request submission form is built from. Active types only —
    that is what makes "deactivated types are not displayed in the submission
    form" true without the frontend having to filter anything itself.

    No role check: requesters need it to submit, and approvers need it because
    they submit requests too (US-019).
    """
    return list_request_types(db=db, active_only=True)


@admin_router.get("", response_model=RequestTypeListResponse)
def list_request_types_admin_endpoint(
    is_active: Optional[bool] = Query(
        default=None,
        description="Omit to get all types — the management page needs to see "
                    "deactivated ones in order to reactivate them.",
    ),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if is_active is None:
        return list_request_types(db=db, active_only=False)

    # The filter only has two possible values, and active_only=True already
    # means "active ones". For is_active=false we list everything and keep the
    # inactive rows.
    result = list_request_types(db=db, active_only=False)
    if is_active is False:
        result["items"] = [item for item in result["items"] if not item.is_active]
    else:
        result["items"] = [item for item in result["items"] if item.is_active]
    result["total"] = len(result["items"])
    result["empty_message"] = "No request types found." if result["total"] == 0 else None
    return result


@admin_router.post(
    "",
    response_model=RequestTypeActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_request_type_endpoint(
    payload: CreateRequestTypeRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    try:
        return create_request_type(db=db, admin_id=admin.id, data=payload)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# IT35-308 – Update, Deactivate & Activate Endpoints
# ============================================================================

@admin_router.patch(
    "/{request_type_id}",
    response_model=RequestTypeActionResponse,
)
def update_request_type_endpoint(
    request_type_id: int,
    payload: UpdateRequestTypeRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    PATCH /admin/request-types/{id}
    Updates the name and/or description of a request type.
    Prefix and slug are immutable.
    """
    try:
        result = update_request_type(
            db=db,
            admin_id=admin.id,
            request_type_id=request_type_id,
            name=payload.name,
            description=payload.description,
        )
    except ValueError as e:
        # Raised when neither name nor description is provided. In practice
        # the schema's model_validator already rejects this with a 422
        # before the route runs, so this is a defensive fallback.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except HTTPException:
        # Re-raise 404 and 409 from the service
        raise
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return result


@admin_router.patch(
    "/{request_type_id}/deactivate",
    response_model=RequestTypeActionResponse,
)
def deactivate_request_type_endpoint(
    request_type_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    PATCH /admin/request-types/{id}/deactivate
    Deactivates a request type. Idempotent.
    """
    try:
        result = set_request_type_active(
            db=db,
            admin_id=admin.id,
            request_type_id=request_type_id,
            is_active=False,
        )
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return result


@admin_router.patch(
    "/{request_type_id}/activate",
    response_model=RequestTypeActionResponse,
)
def activate_request_type_endpoint(
    request_type_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    PATCH /admin/request-types/{id}/activate
    Activates a previously deactivated request type. Idempotent.
    """
    try:
        result = set_request_type_active(
            db=db,
            admin_id=admin.id,
            request_type_id=request_type_id,
            is_active=True,
        )
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    return result
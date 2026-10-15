# app/services/request_type_service.py
# US-017 (IT35-74) — request type management.
#
# IT35-307 (this file's initial content): read + create.
# IT35-308: update_request_type() and set_request_type_active().

import logging
import re
from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.request_type import RequestType
from app.schemas.request_type import CreateRequestTypeRequest

logger = logging.getLogger(__name__)


def slugify(name: str) -> str:
    """
    Turns a display name into the value the API speaks:
    "Training & Courses" -> "training_courses".

    Every run of characters that is not a letter or a digit becomes ONE
    underscore (not one per character), and leading/trailing underscores are
    dropped — otherwise "Hardware & Devices" would come out as
    "hardware___devices".
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _add_audit(db: Session, admin_id: int, action: str, request_type_id: int,
               old_status: str = None, new_status: str = None) -> None:
    """
    Queues one audit row. Added to the session but NOT committed — the caller
    commits it together with the change itself, so an audit row can never
    survive a change that was rolled back.

    Decision U in openapi-sprint6.yaml: audit_log has no column for a request
    type and does not need one. resource_type="request_type" plus resource_id
    is enough to identify which type was affected.
    """
    db.add(AuditLog(
        user_id=admin_id,                 # the admin who performed the action
        action=action,
        resource_type="request_type",
        resource_id=request_type_id,      # the request type that was affected
        old_status=old_status,
        new_status=new_status,
    ))


def list_request_types(db: Session, active_only: bool = True) -> dict:
    """
    Returns request types sorted by name.

    active_only=True  -> GET /request-types        (every authenticated user)
    active_only=False -> GET /admin/request-types  (admin only)

    Deactivating a type only hides it here. Requests that already use it keep
    displaying it, because they store request_type_id and never read this list.
    """
    query = db.query(RequestType)

    if active_only:
        query = query.filter(RequestType.is_active.is_(True))

    items = query.order_by(RequestType.name.asc()).all()
    total = len(items)

    return {
        "items": items,
        "total": total,
        "empty_message": "No request types found." if total == 0 else None,
    }


def create_request_type(db: Session, admin_id: int, data: CreateRequestTypeRequest) -> dict:
    """
    Creates a request type. The whole point of US-017: a new category can be
    added without a code change.

    Raises:
        409 - the name, its derived slug, or the prefix is already taken
    """
    name = data.name                      # already trimmed by the schema
    slug = slugify(name)

    # Compared lowercased on both sides so "Hardware & Devices" and
    # "hardware & devices" count as the same name — the UI would otherwise
    # show two rows nobody can tell apart.
    name_taken = (
        db.query(RequestType)
        .filter(func.lower(RequestType.name) == name.lower())
        .first()
    )
    # Two different names can still produce the same slug ("A & B" and "A B"),
    # and the slug is what every request stores, so it has to be unique too.
    # It is derived from the name, so the name message is the one to show.
    slug_taken = db.query(RequestType).filter(RequestType.slug == slug).first()

    if name_taken or slug_taken:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="This request type name already exists. Please enter a unique name.",
        )

    prefix_taken = db.query(RequestType).filter(RequestType.prefix == data.prefix).first()
    if prefix_taken:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="This request type prefix already exists. Please enter a unique prefix.",
        )

    try:
        new_type = RequestType(
            slug=slug,
            name=name,
            description=data.description,
            prefix=data.prefix,
            counter=0,          # no requests of this type yet, so numbering starts at 0
            is_active=True,     # created active, so it shows up in the form immediately
        )
        db.add(new_type)
        # flush() sends the INSERT so the database assigns new_type.id, which
        # the audit row needs. It does not commit yet.
        db.flush()

        _add_audit(
            db,
            admin_id=admin_id,
            action="REQUEST_TYPE_CREATED",
            request_type_id=new_type.id,
            new_status="active",
        )

        db.commit()
        db.refresh(new_type)

    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error creating request type '%s': %s", name, e)
        raise RuntimeError("Failed to create request type") from e

    logger.info("REQUEST_TYPE_CREATED — id=%d slug=%s by admin_id=%d",
                new_type.id, new_type.slug, admin_id)

    return {
        "id": new_type.id,
        "slug": new_type.slug,
        "name": new_type.name,
        "description": new_type.description,
        "prefix": new_type.prefix,
        "is_active": new_type.is_active,
        "created_at": new_type.created_at,
        "message": "Request type created successfully.",
    }


# ============================================================================
# IT35-308 — Update, Deactivate & Activate
# ============================================================================

def update_request_type(
    db: Session,
    admin_id: int,
    request_type_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """
    Updates a request type's name and/or description.

    Rules (see openapi-sprint6.yaml, PATCH /admin/request-types/{id}):
    - Only name and description are editable — prefix and slug are immutable.
    - Name must be unique (case-insensitive, trimmed). 409 on conflict.
    - At least one of name or description must be provided.
    - Audit-logged as REQUEST_TYPE_UPDATED.

    Raises:
        HTTPException 404 if the request type does not exist.
        HTTPException 409 if the new name is already taken by another type.
        ValueError if neither name nor description is provided (the route
        turns this into 422 — in practice the schema's model_validator
        already catches this before the service is called).
    """
    if name is None and description is None:
        raise ValueError("At least one of 'name' or 'description' must be provided.")

    request_type = db.query(RequestType).filter(RequestType.id == request_type_id).first()
    if not request_type:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Request type not found.",
        )

    if name is not None:
        trimmed_name = name.strip()
        if not trimmed_name:
            raise ValueError("Request type name cannot be empty.")

        # Case-insensitive uniqueness check, excluding this row itself so
        # re-saving the same name (or just changing description) doesn't
        # false-positive as a collision.
        existing = (
            db.query(RequestType)
            .filter(
                func.lower(RequestType.name) == trimmed_name.lower(),
                RequestType.id != request_type_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="This request type name already exists. Please enter a unique name.",
            )

        request_type.name = trimmed_name

    if description is not None:
        request_type.description = description.strip() if description else None

    _add_audit(
        db,
        admin_id=admin_id,
        action="REQUEST_TYPE_UPDATED",
        request_type_id=request_type_id,
        # old_status/new_status are not relevant here — only active/inactive
        # transitions carry those, per the subtask spec.
    )

    try:
        db.commit()
        db.refresh(request_type)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error updating request type %d: %s", request_type_id, e)
        raise RuntimeError("Failed to update request type") from e

    logger.info(
        "REQUEST_TYPE_UPDATED — id=%d slug=%s by admin_id=%d",
        request_type.id, request_type.slug, admin_id,
    )

    return {
        "id": request_type.id,
        "slug": request_type.slug,
        "name": request_type.name,
        "description": request_type.description,
        "prefix": request_type.prefix,
        "is_active": request_type.is_active,
        "created_at": request_type.created_at,
        "message": "Request type updated successfully.",
    }


def set_request_type_active(
    db: Session,
    admin_id: int,
    request_type_id: int,
    is_active: bool,
) -> dict:
    """
    Activates or deactivates a request type. Idempotent: calling it with the
    same target state twice never errors and always ends in the same result —
    but per US-017 ("every ... deactivate action is recorded in the audit
    trail"), every successful call is still logged, even when it doesn't
    change state.

    Rules:
    - Deactivated types disappear from GET /request-types (active-only list).
    - Deactivated types are rejected by POST /requests with 400.
    - Existing requests are unaffected.
    - Audit-logged as REQUEST_TYPE_ACTIVATED or REQUEST_TYPE_DEACTIVATED.
    - old_status/new_status carry "active"/"inactive" (previous/next state).

    Raises:
        HTTPException 404 if the request type does not exist.
        RuntimeError on DB failure.
    """
    request_type = db.query(RequestType).filter(RequestType.id == request_type_id).first()
    if not request_type:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Request type not found.",
        )

    old_status = "active" if request_type.is_active else "inactive"
    new_status = "active" if is_active else "inactive"
    action = "REQUEST_TYPE_ACTIVATED" if is_active else "REQUEST_TYPE_DEACTIVATED"

    request_type.is_active = is_active

    _add_audit(
        db,
        admin_id=admin_id,
        action=action,
        request_type_id=request_type_id,
        old_status=old_status,
        new_status=new_status,
    )

    try:
        db.commit()
        db.refresh(request_type)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            "DB error setting active=%s for request type %d: %s",
            is_active, request_type_id, e,
        )
        raise RuntimeError("Failed to change request type active status") from e

    logger.info(
        "%s — request_type_id=%d by admin_id=%d",
        action, request_type_id, admin_id,
    )

    # FIX: was f"...{new_status}d successfully." which produced "actived" /
    # "inactived". The contract (openapi-sprint6.yaml) requires the exact
    # strings below.
    message = (
        "Request type activated successfully."
        if is_active
        else "Request type deactivated successfully."
    )

    return {
        "id": request_type.id,
        "slug": request_type.slug,
        "name": request_type.name,
        "description": request_type.description,
        "prefix": request_type.prefix,
        "is_active": request_type.is_active,
        "created_at": request_type.created_at,
        "message": message,
    }
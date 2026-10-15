# app/services/approver_service.py
import csv
import io
import logging
from datetime import date, datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from fastapi import HTTPException, status as http_status
from app.models.request import Request, RequestStatus
from app.models.request_type import RequestType
from app.models.user import User
from app.models.audit_log import AuditLog
from app.services.notification_service import notify_status_change

logger = logging.getLogger(__name__)

EMPTY_MESSAGES = {
    "pending":   "No pending requests found.",
    "approved":  "No approved requests found.",
    "rejected":  "No rejected requests found.",
    "completed": "No completed requests found.",
    "cancelled": "No cancelled requests found.",
}


def get_approval_queue(
    db: Session,
    approver_id: int,
    status: str = "pending",
    page: int = 1,
    limit: int = 20,
) -> dict:
    if limit > 100:
        limit = 100

    try:
        status_enum = RequestStatus(status)
    except ValueError:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status value: '{status}'"
        )

    try:
        query = (
            db.query(Request)
            .options(joinedload(Request.user), joinedload(Request.request_type))
            .filter(
                Request.approver_id == approver_id,
                Request.status == status_enum,
            )
        )

        if status == "pending":
            query = query.order_by(Request.created_at.asc())
        else:
            query = query.order_by(Request.updated_at.desc())

        total = query.count()
        items = query.offset((page - 1) * limit).limit(limit).all()

        for item in items:
            item.requester_name = item.user.name if item.user else "Unknown"
            # US-017 (M4): read the slug off the row instead of mapping the
            # prefix through the deleted REQUEST_TYPE_TO_PREFIX dict.
            item.request_type_str = item.request_type.slug if item.request_type else "other"

        empty_message = EMPTY_MESSAGES.get(status) if total == 0 else None

        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "empty_message": empty_message,
        }

    except SQLAlchemyError as e:
        logger.error("DB error fetching approval queue: %s", e)
        raise RuntimeError("Failed to fetch approval queue") from e


def get_status_counts(db: Session, approver_id: int) -> dict:
    rows = (
        db.query(Request.status, func.count(Request.id))
        .filter(Request.approver_id == approver_id)
        .group_by(Request.status)
        .all()
    )
    counts = {s.value: 0 for s in RequestStatus}
    for status_enum, count in rows:
        counts[status_enum.value] = count
    return {
        "pending":   counts.get("pending", 0),
        "approved":  counts.get("approved", 0),
        "rejected":  counts.get("rejected", 0),
        "completed": counts.get("completed", 0),
        "cancelled": counts.get("cancelled", 0),
    }


def _get_pending_request_for_approver(
    db: Session,
    request_number: str,
    approver_id: int,
    action: str,
) -> Request:
    request = (
        db.query(Request)
        .filter(Request.request_number == request_number)
        .first()
    )

    if not request:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_number} not found."
        )

    if request.user_id == approver_id:
        logger.warning(
            "SELF_APPROVAL_BLOCKED — request_number=%s user_id=%d attempted action=%s",
            request_number, approver_id, action,
        )
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You cannot approve or reject your own request."
        )

    if request.approver_id != approver_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="This request is not assigned to you."
        )

    if request.status != RequestStatus.pending:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Request is already {request.status.value}. Only pending requests can be approved or rejected."
        )

    return request


def approve_request(
    db: Session,
    request_number: str,
    approver_id: int,
    comment: str = None,
) -> dict:
    request = _get_pending_request_for_approver(db, request_number, approver_id, "approve")
    try:
        old_status = request.status.value
        request.status = RequestStatus.approved
        request.decision_date = datetime.now(timezone.utc)
        request.approval_comment = comment
        audit = AuditLog(
            user_id=approver_id,
            action="REQUEST_APPROVED",
            resource_type="request",
            resource_id=request.id,
            old_status=old_status,
            new_status=request.status.value,
        )
        db.add(audit)
        db.commit()
        db.refresh(request)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error approving request %s: %s", request_number, e)
        raise RuntimeError("Failed to approve request") from e

    logger.info(
        "REQUEST_APPROVED — request_number=%s approver_id=%d",
        request_number,
        approver_id,
    )
    # US-014 — tell the requester. After the commit on purpose: the approval is
    # already final, and notify_status_change() never raises.
    notify_status_change(db, request, request.decision_date)

    queue_result = get_approval_queue(db, approver_id)
    return {
        "request_id": request.request_number,
        "status": request.status.value,
        "message": "Request approved successfully.",
        "updated_at": request.updated_at,
        "queue": queue_result["items"],
    }


def reject_request(
    db: Session,
    request_number: str,
    approver_id: int,
    reason: str,
) -> dict:
    request = _get_pending_request_for_approver(db, request_number, approver_id, "reject")
    try:
        old_status = request.status.value
        request.status = RequestStatus.rejected
        request.decision_date = datetime.now(timezone.utc)
        request.rejection_reason = reason
        audit = AuditLog(
            user_id=approver_id,
            action="REQUEST_REJECTED",
            resource_type="request",
            resource_id=request.id,
            old_status=old_status,
            new_status=request.status.value,
        )
        db.add(audit)
        db.commit()
        db.refresh(request)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error rejecting request %s: %s", request_number, e)
        raise RuntimeError("Failed to reject request") from e

    logger.info(
        "REQUEST_REJECTED — request_number=%s approver_id=%d",
        request_number,
        approver_id,
    )
    # US-014 — see the note in approve_request().
    notify_status_change(db, request, request.decision_date)

    queue_result = get_approval_queue(db, approver_id)
    return {
        "request_id": request.request_number,
        "status": request.status.value,
        "message": "Request rejected successfully.",
        "updated_at": request.updated_at,
        "queue": queue_result["items"],
    }


def get_approver_request_details(
    db: Session,
    request_id: str,
    approver_id: int,
) -> Optional[Request]:
    request = (
        db.query(Request)
        .options(joinedload(Request.user), joinedload(Request.request_type))
        .filter(Request.request_number == request_id)
        .first()
    )

    if not request:
        return None

    if request.approver_id != approver_id:
        raise PermissionError(
            f"Request {request_id} is not assigned to this approver."
        )

    request.requester_name = request.user.name if request.user else "Unknown"
    request.approver_name = request.approver.name if request.approver else None
    request.request_type_name = (
        request.request_type.name if request.request_type else None
    )

    # comments field per OpenAPI spec:
    # approved â†’ approval_comment, rejected â†’ rejection_reason, else â†’ None
    if request.status == RequestStatus.approved:
        request.comments_display = getattr(request, 'approval_comment', None)
    elif request.status == RequestStatus.rejected:
        request.comments_display = request.rejection_reason
    else:
        request.comments_display = None

    return request


# ============================================================================
# US-012 (IT35-310) — GET /approver/requests/export
# ============================================================================

# Column order is fixed by the contract (openapi-sprint6.yaml, GET
# /approver/requests/export). The frontend and any acceptance test read the
# file positionally, so this order is part of the contract, not a detail.
APPROVER_EXPORT_COLUMNS = [
    "request_id",
    "approver_id",
    "decision",
    "decision_date",
    "comment",
]


def _csv_datetime(value) -> str:
    """
    Same ISO-with-Z formatting request_service.py uses for the requester
    export (IT35-309), so every CSV in the system agrees on one datetime
    shape. An empty cell means the request never reached that state — that
    is meaningful, so None must become "" and not the word "None".
    """
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else ""


def export_my_decisions_csv(
    db: Session,
    approver_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    request_type: Optional[str] = None,
    decision: Optional[str] = None,
) -> Tuple[str, int]:
    """
    US-012 (IT35-310) — CSV of the decisions the caller made themselves.

    Only DECIDED requests (approved/rejected) appear. A request still sitting
    pending in the queue has no decision to export, and a cancelled request
    was withdrawn by the requester rather than decided by the approver — see
    openapi-sprint6.yaml, GET /approver/requests/export.

    Scoping note (decision Q): approver_id comes from the token in the route;
    there is no parameter that could point at anybody else's decisions.

    Raises:
        400 - start_date is after end_date
        422 - decision is neither "approved" nor "rejected" (defensive — the
              route already validates this before calling the service, per
              the "role check, then filter validation" ordering used on the
              approval-queue endpoint above)
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date.",
        )

    query = (
        db.query(Request)
        .options(joinedload(Request.request_type))
        .filter(
            Request.approver_id == approver_id,
            Request.status.in_([RequestStatus.approved, RequestStatus.rejected]),
        )
    )

    # Dates filter on decision_date (not created_at) per the contract — both
    # ends inclusive, same combine() pattern request_service.py uses.
    if start_date:
        query = query.filter(
            Request.decision_date >= datetime.combine(start_date, datetime.min.time())
        )
    if end_date:
        query = query.filter(
            Request.decision_date <= datetime.combine(end_date, datetime.max.time())
        )

    if request_type:
        # A slug that does not exist matches nothing rather than erroring —
        # same shape as request_service.py's export.
        rt = db.query(RequestType).filter(RequestType.slug == request_type).first()
        if rt:
            query = query.filter(Request.request_type_id == rt.id)
        else:
            query = query.filter(False)

    if decision:
        try:
            query = query.filter(Request.status == RequestStatus(decision))
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid decision '{decision}'. Valid values: ['approved', 'rejected']",
            )

    requests = query.order_by(Request.decision_date.desc()).all()

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=APPROVER_EXPORT_COLUMNS)
    writer.writeheader()

    for req in requests:
        # Same pairing as RequestDetailsResponse.comments (and
        # get_approver_request_details above): approval_comment for an
        # approval, rejection_reason for a rejection.
        if req.status == RequestStatus.approved:
            comment = req.approval_comment
        else:
            comment = req.rejection_reason

        writer.writerow({
            "request_id": req.request_number,
            "approver_id": approver_id,
            "decision": req.status.value,
            "decision_date": _csv_datetime(req.decision_date),
            "comment": comment or "",
        })

    # Decision S: exporting personal data is itself an auditable event.
    db.add(AuditLog(
        user_id=approver_id,
        action="DATA_EXPORTED",
        resource_type="request",
        resource_id=None,
    ))
    db.commit()

    logger.info("DATA_EXPORTED — approver_id=%d rows=%d", approver_id, len(requests))

    return buffer.getvalue(), len(requests)


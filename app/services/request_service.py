# app/services/request_service.py

import csv
import io
import logging
from datetime import date, datetime, timezone
from typing import Optional, Tuple
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException, status as http_status

from app.models.comment import Comment
from app.models.request import Request, RequestStatus
from app.models.request_type import RequestType
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.schemas.request import RequestCreate
from app.services.notification_service import notify_status_change

logger = logging.getLogger(__name__)

# US-012 (IT35-309) — the requester export's columns, in the exact order the
# contract lists them. The order is part of the contract, not a detail: the
# frontend and the acceptance test both read the file positionally.
MY_REQUESTS_EXPORT_COLUMNS = [
    "request_id",
    "request_type",
    "title",
    "created_date",
    "current_status",
    "decision_date",
    "completion_date",
    "cancellation_date",
    "comments",
]


def _get_request_type_by_slug(db: Session, slug: str) -> RequestType:
    """
    US-017 (M4): looks the request type up in the database by its slug, instead
    of in the deleted REQUEST_TYPE_TO_PREFIX dict. A type an admin created five
    minutes ago works here immediately — that is the whole story.

    Two different failures, two different HTTP codes (decision M):
        LookupError -> the slug does not exist at all      -> 422
        ValueError  -> it exists but was deactivated       -> 400
    The second one is not a theoretical case: a browser tab opened while the
    type was still active can post it minutes after an admin turned it off.

    with_for_update() locks the row so two people submitting at the same moment
    cannot read the same counter and end up with the same request number.
    """
    request_type = (
        db.query(RequestType)
        .filter(RequestType.slug == slug)
        .with_for_update()
        .first()
    )
    if not request_type:
        raise LookupError(f"Invalid request_type '{slug}'.")

    if not request_type.is_active:
        raise ValueError("This request type is no longer available.")

    return request_type


def _generate_request_number(db: Session, request_type: RequestType) -> str:
    """Atomically increment counter and return formatted number."""
    request_type.counter += 1
    db.flush()
    return f"{request_type.prefix}-{request_type.counter:03d}"


def _assign_approver(db: Session, requester_id: Optional[int] = None) -> Optional[int]:
    """
    Round-robin approver assignment.

    IT35-261: a request must never be assigned to its own requester. If the
    next-in-rotation approver would be the requester, skip forward to the
    following approver in the rotation. If every active approver is the
    requester (e.g. the only active approver is the requester themself),
    no approver is assigned.
    """
    approvers = (
        db.query(User)
        .filter(User.role == UserRole.approver, User.is_active == True)
        .order_by(User.id)
        .all()
    )
    if not approvers:
        return None

    total_requests = db.query(Request).count()
    n = len(approvers)

    for offset in range(n):
        candidate = approvers[(total_requests + offset) % n]
        if candidate.id != requester_id:
            return candidate.id

    # Every active approver is the requester themself - no valid assignment.
    return None


def create_request(db: Session, user_id: int, data: RequestCreate) -> dict:
    """Creates a new request in the database."""
    try:
        request_type = _get_request_type_by_slug(db, data.request_type)
        request_number = _generate_request_number(db, request_type)
        approver_id = _assign_approver(db, requester_id=user_id)

        new_request = Request(
            request_number=request_number,
            user_id=user_id,
            request_type_id=request_type.id,
            title=data.title,
            justification=data.justification,
            status=RequestStatus.pending,
            approver_id=approver_id,
        )

        db.add(new_request)
        # flush() sends the INSERT so new_request.id exists, but keeps the
        # transaction open — the audit row is committed together with the
        # request, so we can never store one without the other (US-011, M6).
        db.flush()

        audit = AuditLog(
            user_id=user_id,
            action="REQUEST_CREATED",
            resource_type="request",
            resource_id=new_request.id,
            new_status=RequestStatus.pending.value,
        )
        db.add(audit)

        db.commit()
        db.refresh(new_request)

        logger.info(
            "REQUEST_CREATED — request_number=%s user_id=%d type=%s approver_id=%s",
            request_number,
            user_id,
            request_type.slug,
            approver_id,
        )

        return {
            "id": str(new_request.id),
            "request_number": new_request.request_number,
            "request_type": request_type.slug,
            "title": new_request.title,
            "justification": new_request.justification,
            "status": new_request.status.value,
            "approver_id": new_request.approver_id,
            "message": "Request submitted successfully.",
            "created_at": new_request.created_at,
            "updated_at": new_request.updated_at,
        }

    except (ValueError, LookupError):
        # Both come from _get_request_type_by_slug above; the route turns them
        # into 400 and 422 respectively.
        db.rollback()
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error creating request user_id=%d: %s", user_id, e)
        raise RuntimeError("Failed to create request — database error") from e


def get_user_requests(
    db: Session,
    user_id: int,
    page: int = 1,
    limit: int = 10,
    status: Optional[str] = None
) -> dict:
    """Returns paginated list of requests for a specific user."""
    if limit > 100:
        limit = 100

    query = (
        db.query(Request)
        .options(joinedload(Request.request_type))
        .filter(Request.user_id == user_id)
    )

    if status:
        try:
            status_enum = RequestStatus(status)
            query = query.filter(Request.status == status_enum)
        except ValueError:
            raise ValueError(
                f"Invalid status '{status}'. "
                f"Valid values: {[s.value for s in RequestStatus]}"
            )

    total = query.count()
    items = (
        query
        .order_by(Request.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    
    result_items = []
    for item in items:
        # US-017 (M4): the slug now comes straight off the row. Deactivated
        # types still resolve here — a request keeps the type it was created
        # with, whatever the admin does to that type afterwards.
        # IT35-331: was a per-row query (N+1) — now eager-loaded on the
        # query below instead, same pattern export_my_requests_csv already used.
        request_type_str = item.request_type.slug if item.request_type else "other"
        result_items.append({
            "request_number": item.request_number,
            "request_type": request_type_str,
            "created_at": item.created_at,
            "approver_id": item.approver_id,
            "status": item.status.value,
            "updated_at": item.updated_at,
            "decision_date": item.decision_date,
            "rejection_reason": item.rejection_reason,
        })

    return {
        "items": result_items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
        "empty_message": "No requests found. You have not submitted any requests yet." if total == 0 else None

    }
def _csv_datetime(value: Optional[datetime]) -> str:
    """
    Formats a timestamp the way the contract's CSV example shows it
    (2026-07-10T10:30:00Z). An empty cell means the request never reached that
    state — that is meaningful, so None must become "" and not the word "None".
    """
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else ""


def export_my_requests_csv(
    db: Session,
    user_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    request_type: Optional[str] = None,
    status: Optional[str] = None,
) -> Tuple[str, int]:
    """
    US-012 (IT35-309) — CSV of the caller's OWN requests.

    Returns (csv_text, row_count). The count goes into the X-Export-Row-Count
    header (decision T) so the frontend can say "12 rows exported" instead of
    just "done" — and so a genuinely empty export is distinguishable from a
    failed one.

    Scoping note (decision Q): `user_id` comes from the token in the route, and
    there is no parameter that could point at anybody else. "A user can only
    export their own data" is enforced by that absence, not by a permission
    check that could be got around.

    Raises:
        400 - start_date is after end_date
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date.",
        )

    query = (
        db.query(Request)
        .options(joinedload(Request.request_type))
        .filter(Request.user_id == user_id)
    )

    # The dates filter on the submission date, and both ends are inclusive:
    # combining end_date with max.time() keeps requests made later that same day.
    if start_date:
        query = query.filter(Request.created_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(Request.created_at <= datetime.combine(end_date, datetime.max.time()))

    if request_type:
        # A slug that does not exist matches nothing rather than erroring —
        # an empty CSV is a valid answer to "give me my TC requests" when the
        # user has none. Same shape as report_service.
        rt = db.query(RequestType).filter(RequestType.slug == request_type).first()
        if rt:
            query = query.filter(Request.request_type_id == rt.id)
        else:
            query = query.filter(False)

    if status:
        try:
            query = query.filter(Request.status == RequestStatus(status))
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Invalid status '{status}'. "
                    f"Valid values: {[s.value for s in RequestStatus]}"
                ),
            )

    # Newest first, matching GET /requests so the CSV and the page agree.
    requests = query.order_by(Request.created_at.desc()).all()

    # IT35-331: was one Comment query per request row (N+1) — with a large
    # export this alone could mean thousands of individual round trips,
    # which is what produced the Gateway Timeout. Fetch every comment for
    # every request in this export in a single query, then group them in
    # Python by request_id.
    request_ids = [req.id for req in requests]
    comments_by_request_id: dict[int, list] = {}
    if request_ids:
        all_comments = (
            db.query(Comment)
            .filter(Comment.request_id.in_(request_ids), Comment.author_id == user_id)
            .order_by(Comment.created_at.asc())
            .all()
        )
        for c in all_comments:
            comments_by_request_id.setdefault(c.request_id, []).append(c)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=MY_REQUESTS_EXPORT_COLUMNS)
    writer.writeheader()

    for req in requests:
        # US-012 asks for "comments (from the requester)", so this is the
        # caller's OWN comments only — an approver's approval comment and the
        # rejection reason belong to the approver export, not this one.
        own_comments = comments_by_request_id.get(req.id, [])

        writer.writerow({
            "request_id": req.request_number,
            "request_type": req.request_type.slug if req.request_type else "",
            "title": req.title,
            "created_date": _csv_datetime(req.created_at),
            "current_status": req.status.value,
            "decision_date": _csv_datetime(req.decision_date),
            "completion_date": _csv_datetime(req.completion_date),
            "cancellation_date": _csv_datetime(req.cancellation_date),
            "comments": " | ".join(c.content for c in own_comments),
        })

    # Decision S: exporting personal data is itself an auditable event.
    db.add(AuditLog(
        user_id=user_id,
        action="DATA_EXPORTED",
        resource_type="request",
        resource_id=None,
    ))
    db.commit()

    logger.info("DATA_EXPORTED — user_id=%d rows=%d", user_id, len(requests))

    return buffer.getvalue(), len(requests)


def get_request_details(db: Session, user_id: int, request_id: str) -> Optional[Request]:
    request = (
        db.query(Request)
        .options(
            joinedload(Request.request_type),
            joinedload(Request.user),
            joinedload(Request.approver),
        )
        .filter(Request.request_number == request_id)
        .first()
    )

    if not request:
        return None

    if request.user_id != user_id:
        raise PermissionError("You are unauthorized for this section.")

    request.request_type_name = (
        request.request_type.name if request.request_type else None
    )

    request.requester_name = request.user.name if request.user else None
    request.approver_name = request.approver.name if request.approver else None
    # +++ START: Add decision metadata for the schema +++
    # NOTE: 'comments' is a SQLAlchemy relationship on Request (-> Comment list).
    # Assigning a string directly to it breaks the ORM collection.
    # We set a separate transient attribute instead and map it via
    # validation_alias in RequestDetailsResponse (schemas/request.py).
    request.comments_display = request.approval_comment if request.status == RequestStatus.approved else request.rejection_reason  # Map rejection_reason for display
    # +++ END +++

    return request



def complete_request(db: Session, request_id: str, user_id: int) -> dict:
    """
    IT35-264 - mark an approved request as completed by its own requester.

    Raises:
        404 - request_id does not exist
        403 - caller is not the requester who owns this request
        400 - request is not currently in `approved` status
    """
    request = (
        db.query(Request)
        .filter(Request.request_number == request_id)
        .first()
    )

    if not request:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_id} not found."
        )

    if request.user_id != user_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Request does not belong to the authenticated requester."
        )

    if request.status != RequestStatus.approved:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Only approved requests can be marked as completed."
        )

    try:
        old_status = request.status.value
        request.status = RequestStatus.completed
        request.completion_date = datetime.now(timezone.utc)

        audit = AuditLog(
            user_id=user_id,
            action="REQUEST_COMPLETED",
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
        logger.error("DB error completing request %s: %s", request_id, e)
        raise RuntimeError("Failed to complete request") from e

    logger.info(
        "REQUEST_COMPLETED - request_number=%s user_id=%d",
        request_id,
        user_id,
    )
    # US-014 — the requester completes their own request, so here the recipient
    # and the actor happen to be the same person. Still routed off request.user_id.
    notify_status_change(db, request, request.completion_date)

    return {
        "request_id": request.request_number,
        "status": request.status.value,
        "message": "Request marked as completed successfully.",
        "completion_date": request.completion_date,
        "updated_at": request.updated_at,
    }


def cancel_request(db: Session, request_id: str, user_id: int, user_role: UserRole) -> dict:
    """
    US-015 (IT35-227) - cancel a pending request. Only the requester who owns
    it may cancel it, and only while it is still pending.

    US-019: approvers submit their own requests too, so an approver may cancel
    their own pending request (ownership is still enforced below).

    Raises:
        403 - caller's role is neither requester nor approver
        404 - request_id does not exist
        403 - caller is not the requester who owns this request
        400 - request is not currently in "pending" status
    """
    if user_role not in (UserRole.requester, UserRole.approver):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Unauthorized users cannot cancel requests."
        )

    request = (
        db.query(Request)
        .filter(Request.request_number == request_id)
        .first()
    )

    if not request:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Request {request_id} not found."
        )

    if request.user_id != user_id:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Request does not belong to the authenticated requester."
        )

    if request.status != RequestStatus.pending:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Only pending requests can be cancelled."
        )

    try:
        old_status = request.status.value
        request.status = RequestStatus.cancelled
        request.cancellation_date = datetime.now(timezone.utc)

        audit = AuditLog(
            user_id=user_id,
            action="REQUEST_CANCELLED",
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
        logger.error("DB error cancelling request %s: %s", request_id, e)
        raise RuntimeError("Failed to cancel request") from e

    logger.info(
        "REQUEST_CANCELLED - request_number=%s user_id=%d",
        request_id,
        user_id,
    )
    # US-014 — same as complete: the requester cancels their own request.
    notify_status_change(db, request, request.cancellation_date)

    return {
        "request_id": request.request_number,
        "status": request.status.value,
        "message": "Request cancelled successfully.",
        "cancellation_date": request.cancellation_date,
        "updated_at": request.updated_at,
    }

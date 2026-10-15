# app/services/notification_service.py
#
# IT35-282 (this file's initial content) - get_notifications() only.
# IT35-281 will add create_notification() to this same file - do not
# duplicate the file, add it as a second function below.

import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.models.notification import Notification  # IT35-281 - not yet on dev

logger = logging.getLogger(__name__)

# The request_types table stores display names ("Hardware & Devices"), but the
# OpenAPI contract wants the snake_case value ("hardware_devices"). US-017 (M5)
# added a `slug` column that holds exactly that, so the old prefix mapping is
# gone and we read the column directly.


def get_notifications(
    db: Session,
    user_id: int,
    unread_only: bool = False,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """IT35-282 - paginated list of the caller's own notifications, newest first."""
    if limit > 100:
        limit = 100

    query = db.query(Notification).filter(Notification.user_id == user_id)

    if unread_only:
        query = query.filter(Notification.is_read == False)  # noqa: E712

    total = query.count()
    items = (
        query
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    # unread_count always reflects ALL of the caller's unread notifications,
    # independent of unread_only/page/limit - it drives the bell badge, not
    # the current page.
    unread_count = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .count()
    )

    return {
        "items": items,
        "page": page,
        "limit": limit,
        "total": total,
        "unread_count": unread_count,
        "empty_message": "No notifications found." if total == 0 else None,
    }

NOTIFICATION_TEMPLATES = {
    "approved": {
        "title": "Request Approved",
        "message": "Your request {request_id} has been approved.",
    },
    "rejected": {
        "title": "Request Rejected",
        "message": "Your request {request_id} has been rejected.",
    },
    "completed": {
        "title": "Request Completed",
        "message": "Your request {request_id} has been completed.",
    },
    "cancelled": {
        "title": "Request Cancelled",
        "message": "Your request {request_id} has been cancelled.",
    },
}


def create_notification(
    db: Session,
    user_id: int,
    request_id: str,
    request_type: str,
    status: str,
    status_change_date: datetime,
) -> Optional[Notification]:
    """
    IT35-281 — Creates a notification for a status change.
    Only creates notifications for: approved, rejected, completed, cancelled.
    Does NOT create notifications for pending status.

    `request_type` and `status_change_date` are required by the OpenAPI contract
    and are NOT NULL in the database (5a1bc9c5c896), so callers must supply both.
    Passing None raises here rather than at commit time, where the IntegrityError
    would name the column but not the request that caused it.
    """
    # The pending check comes first: no notification is wanted at all for those,
    # so there is nothing to validate and no reason to make the caller care.
    template = NOTIFICATION_TEMPLATES.get(status)
    if not template:
        return None

    if request_type is None:
        raise ValueError("request_type is required to create a notification.")
    if status_change_date is None:
        raise ValueError("status_change_date is required to create a notification.")

    notification = Notification(
        user_id=user_id,
        request_id=request_id,
        request_type=request_type,
        status=status,
        status_change_date=status_change_date,
        title=template["title"],
        message=template["message"].format(request_id=request_id),
        is_read=False,
    )
    db.add(notification)
    return notification


def notify_status_change(
    db: Session,
    request,
    status_change_date: Optional[datetime] = None,
) -> Optional[Notification]:
    """
    IT35-281 — the bridge between a status change and a notification.

    approve / reject / complete / cancel each call this once, straight after
    their own db.commit(). It works out the four values create_notification()
    needs from the Request row itself, so the four call sites stay one line.

    Two things worth knowing:

    * The notification goes to `request.user_id` — the requester who owns the
      request — never to whoever performed the action. On an approval the actor
      is the approver, and they are not the one who needs telling.
    * It never raises. By the time we are called the status change is already
      committed, so letting a notification failure bubble up would turn a
      successful approval into a 500 and leave the caller thinking it failed.
      A missing notification is a much smaller problem than that, so it is
      logged and swallowed.
    """
    try:
        request_type = "other"
        if request.request_type is not None:
            request_type = request.request_type.slug or "other"

        notification = create_notification(
            db=db,
            user_id=request.user_id,
            request_id=request.request_number,
            request_type=request_type,
            status=request.status.value,
            status_change_date=status_change_date or datetime.now(timezone.utc),
        )

        # create_notification() returns None for statuses that get no
        # notification (pending) - nothing was added, so nothing to commit.
        if notification is None:
            return None

        db.commit()
        db.refresh(notification)
        return notification

    except Exception as e:
        # Rolls back only the notification insert; the status change was
        # committed in its own transaction before this function was called.
        db.rollback()
        logger.error(
            "Failed to create notification for request %s: %s",
            getattr(request, "request_number", "?"),
            e,
        )
        return None


def mark_notification_read(
    db: Session,
    notification_id: int,
    user_id: int,
) -> Optional[Notification]:
    """
    IT35-283 — marks one notification as read.

    Reading is not deleting: the row stays in the table, only `is_read` flips.
    Returns None when the notification does not exist (the route turns that into
    a 404), and raises PermissionError when it belongs to somebody else (403).
    """
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id)
        .first()
    )

    if notification is None:
        return None

    # Checked here rather than in the query on purpose: filtering by user_id too
    # would make somebody else's notification look like a missing one (404), and
    # the spec asks for 403.
    if notification.user_id != user_id:
        raise PermissionError("Notification belongs to another user.")

    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification
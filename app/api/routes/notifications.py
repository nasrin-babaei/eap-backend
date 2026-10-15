# app/api/routes/notifications.py
# IT35-282 - GET /notifications. Subtask 3 (IT35-283) adds the PATCH
# .../{notification_id}/read route below this one, same file.

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.schemas.notification import NotificationResponse, NotificationsResponse
from app.services.notification_service import get_notifications, mark_notification_read

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationsResponse)
def get_notifications_endpoint(
    unread_only: bool = Query(default=False),
    page: int = Query(default=1),
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # get_current_user already raises 401 if the token is missing/invalid.
    # Any authenticated role may read their own notifications - no role gate.
    return get_notifications(
        db=db,
        user_id=current_user.id,
        unread_only=unread_only,
        page=page,
        limit=limit,
    )


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read_endpoint(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """IT35-283 - mark one notification as read. Any authenticated role, own
    notifications only. The notification is kept, not deleted."""
    try:
        notification = mark_notification_read(
            db=db,
            notification_id=notification_id,
            user_id=current_user.id,
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )

    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )

    return notification
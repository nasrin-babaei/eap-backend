# app/services/comment_service.py

import logging
from typing import List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError

from app.models.audit_log import AuditLog
from app.models.comment import Comment
from app.models.request import Request
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


def create_comment(db: Session, request_id: str, author_id: int, content: str) -> Comment:
    """
    Creates a new comment on a request, only while the request is pending,
    and only by the owning requester.
    """
    request = db.query(Request).filter(Request.request_number == request_id).first()

    if not request:
        raise LookupError(f"Request {request_id} not found.")

    if request.user_id != author_id:
        raise PermissionError("You are unauthorized to comment on this request.")

    if request.status.value != "pending":
        raise ValueError("Comments can only be added while the request is pending.")

    if not content or not content.strip():
        raise ValueError("Comment content cannot be empty.")

    try:
        comment = Comment(
            request_id=request.id,
            author_id=author_id,
            content=content.strip(),
        )
        db.add(comment)

        # resource_type is "request", not "comment", on purpose. The Audit Logs
        # page has a Request ID column, and audit_service only resolves it for
        # rows whose resource_type is "request" — pointing this row at the
        # request is what makes "HD-001" show up next to the action (US-011, M6).
        audit = AuditLog(
            user_id=author_id,
            action="COMMENT_CREATED",
            resource_type="request",
            resource_id=request.id,
        )
        db.add(audit)

        db.commit()
        db.refresh(comment)

        logger.info(
            "COMMENT_CREATED — request_id=%s author_id=%d",
            request_id,
            author_id,
        )

        return comment

    except SQLAlchemyError as e:
        db.rollback()
        logger.error("DB error creating comment for request %s: %s", request_id, e)
        raise RuntimeError("Failed to create comment — database error") from e


def get_comments_for_requester(db: Session, request_id: str, user_id: int) -> List[dict]:
    """
    Returns all comments for a request, ordered chronologically (oldest first),
    accessible only by the requester who owns the request.
    """
    request = db.query(Request).filter(Request.request_number == request_id).first()

    if not request:
        return None

    if request.user_id != user_id:
        raise PermissionError("You are unauthorized to view comments on this request.")

    return _fetch_comments(db, request.id, request.request_number)


def get_comments_for_approver(db: Session, request_id: str, approver_id: int) -> List[dict]:
    """
    Returns all comments for a request, ordered chronologically (oldest first),
    accessible only by the approver assigned to the request.
    """
    request = db.query(Request).filter(Request.request_number == request_id).first()

    if not request:
        return None

    if request.approver_id != approver_id:
        raise PermissionError("This request is not assigned to you.")

    return _fetch_comments(db, request.id, request.request_number)


def _fetch_comments(db: Session, request_pk, request_number: str) -> List[dict]:
    """Shared query — fetches comments ordered by created_at ascending."""
    comments = (
        db.query(Comment)
        .options(joinedload(Comment.author))
        .filter(Comment.request_id == request_pk)
        .order_by(Comment.created_at.asc())
        .all()
    )

    return [
        {
            "id": c.id,
            "request_id": request_number,
            "author_id": c.author_id,
            "author_name": c.author.name if c.author else "Unknown",
            "content": c.content,
            "created_at": c.created_at,
        }
        for c in comments
    ]
















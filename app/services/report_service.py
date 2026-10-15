# app/services/report_service.py
# US-010 (IT35-63) — Report generation service

import logging
from datetime import date, datetime
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.request import Request, RequestStatus
from app.models.request_type import RequestType
from app.models.user import User

logger = logging.getLogger(__name__)


def validate_date_range(start_date: Optional[date], end_date: Optional[date]) -> None:
    """Raises ValueError if start_date is after end_date."""
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date cannot be after end_date.")


def _build_base_query(db: Session, start_date: Optional[date],
                      end_date: Optional[date], request_type: Optional[str],
                      status: Optional[str]):
    """Shared base query with all optional filters applied."""
    query = db.query(Request)

    if start_date:
        query = query.filter(Request.created_at >= datetime.combine(start_date, datetime.min.time()))
    if end_date:
        query = query.filter(Request.created_at <= datetime.combine(end_date, datetime.max.time()))
    if request_type:
        # US-017 (M4): resolve the slug against the table. A filter on a slug
        # that does not exist matches nothing, which is what filter(False) does.
        rt = db.query(RequestType).filter(RequestType.slug == request_type).first()
        if rt:
            query = query.filter(Request.request_type_id == rt.id)
        else:
            query = query.filter(False)
    if status:
        try:
            status_enum = RequestStatus(status)
            query = query.filter(Request.status == status_enum)
        except ValueError:
            query = query.filter(False)

    return query


def generate_report(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    request_type: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """
    Computes request statistics with optional filters.
    Returns totals, approval_rate, rejection_rate per OpenAPI spec.
    """
    validate_date_range(start_date, end_date)

    base = _build_base_query(db, start_date, end_date, request_type, status)

    total_requests = base.count()

    def count_status(s: RequestStatus) -> int:
        return base.filter(Request.status == s).count()

    pending   = count_status(RequestStatus.pending)
    approved  = count_status(RequestStatus.approved)
    rejected  = count_status(RequestStatus.rejected)
    completed = count_status(RequestStatus.completed)
    cancelled = count_status(RequestStatus.cancelled)

    decided = approved + completed + rejected
    if decided > 0:
        approval_rate  = round((approved + completed) / decided * 100, 2)
        rejection_rate = round(rejected / decided * 100, 2)
    else:
        approval_rate  = 0.0
        rejection_rate = 0.0

    return {
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "request_type": request_type,
            "status": status,
        },
        "totals": {
            "total_requests": total_requests,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "completed": completed,
            "cancelled": cancelled,
        },
        "approval_rate": approval_rate,
        "rejection_rate": rejection_rate,
        "generated_at": datetime.utcnow(),
    }


def fetch_report_rows(
    db: Session,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    request_type: Optional[str] = None,
    status: Optional[str] = None,
) -> List[dict]:
    """
    Returns raw per-request rows for CSV export.
    Joins users and request_types to resolve display names.
    """
    validate_date_range(start_date, end_date)

    query = _build_base_query(db, start_date, end_date, request_type, status)
    requests = query.order_by(Request.created_at.desc()).all()

    rows = []
    for req in requests:
        requester_name = req.user.name if req.user else "Unknown"
        approver_name  = req.approver.name if req.approver else None
        rt = req.request_type
        request_type_str = rt.slug if rt else "other"

        rows.append({
            "request_id":        req.request_number,
            "request_type":      request_type_str,
            "title":             req.title,
            "requester_name":    requester_name,
            "approver_name":     approver_name,
            "status":            req.status.value,
            "submission_date":   req.created_at,
            "decision_date":     req.decision_date,
            "completion_date":   getattr(req, "completion_date", None),
            "cancellation_date": getattr(req, "cancellation_date", None),
        })

    return rows
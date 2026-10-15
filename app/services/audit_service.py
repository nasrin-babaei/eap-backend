# app/services/audit_service.py
# EAP-IT35 — Audit logging service
# Called by the login route to record LOGIN_SUCCESS and LOGIN_FAIL events.
# GDPR: no passwords, no full JWT tokens stored here.

import csv
import io
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Tuple

from fastapi import HTTPException, status as http_status
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.request import Request

logger = logging.getLogger(__name__)


def log_login_success(db: Session, user_id: int, ip_address: str) -> None:
    """
    Record a successful login event.
    Called AFTER credentials are verified and token is created.
    """
    try:
        entry = AuditLog(
            user_id=user_id,
            action="LOGIN_SUCCESS",
            resource_type="auth",
            resource_id=user_id,
            ip_address=ip_address,
        )
        db.add(entry)
        db.commit()
        logger.info(f"LOGIN_SUCCESS — user_id={user_id} ip={ip_address}")
    except Exception as e:
        db.rollback()
        # Never let audit failure break the login flow
        logger.error(f"Failed to write LOGIN_SUCCESS audit log: {e}")


def log_login_failure(db: Session, ip_address: str, reason: str = "invalid_credentials") -> None:
    """
    Record a failed login attempt.
    user_id is None — we do NOT confirm whether the email exists.
    GDPR: we do NOT log the attempted email address.
    """
    try:
        entry = AuditLog(
            user_id=None,
            action="LOGIN_FAIL",
            resource_type="auth",
            resource_id=None,
            ip_address=ip_address,
        )
        db.add(entry)
        db.commit()
        logger.warning(f"LOGIN_FAIL — reason={reason} ip={ip_address}")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to write LOGIN_FAIL audit log: {e}")


def _build_audit_query(
    db: Session,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    search: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user_name: Optional[str] = None,
    request_id: Optional[str] = None,
):
    """
    Builds the filtered audit-log query shared by the paged list endpoint, the
    US-011 CSV export, and the US-012 admin personal-activity export. All must
    apply exactly the same date/action filtering, so it lives here once.

    Returns a query of (AuditLog, user name, request number) tuples, unsorted
    and unpaged; the callers decide about ordering, paging, and any extra
    scoping (e.g. filtering to one admin's own rows).
    """
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date.",
        )

    # M7: user_name needs a join to users; request_id (e.g. HD-001) needs to
    # resolve via requests.request_number, joined on resource_id — but only
    # for rows that are actually about a request (resource_id is a generic
    # column reused for user ids, request_type ids, etc, so the join must be
    # conditional on resource_type == "request", not just an id match).
    query = (
        db.query(AuditLog, User.name, Request.request_number)
        .outerjoin(User, AuditLog.user_id == User.id)
        .outerjoin(
            Request,
            and_(
                AuditLog.resource_type == "request",
                AuditLog.resource_id == Request.id,
            ),
        )
    )

    if action:
        query = query.filter(AuditLog.action == action)

    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)

    if resource_id is not None:
        query = query.filter(AuditLog.resource_id == resource_id)

    if start_date:
        query = query.filter(
            AuditLog.timestamp >= datetime.combine(start_date, datetime.min.time())
        )

    if end_date:
        end_of_day = datetime.combine(end_date, datetime.min.time()) + timedelta(days=1)
        query = query.filter(AuditLog.timestamp < end_of_day)

    if user_name:
        query = query.filter(User.name.ilike(f"%{user_name}%"))

    if request_id:
        query = query.filter(Request.request_number == request_id)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                AuditLog.action.ilike(pattern),
                User.name.ilike(pattern),
                Request.request_number.ilike(pattern),
            )
        )

    return query


def _row_to_item(log: AuditLog, name: Optional[str], req_number: Optional[str]) -> dict:
    """Turns one query row into the dict shape AuditLogItem expects."""
    return {
        "id": log.id,
        "user_id": log.user_id,
        "user_name": name,
        "action": log.action,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "request_id": req_number,
        "old_status": log.old_status,
        "new_status": log.new_status,
        "timestamp": log.timestamp,
    }


def get_audit_logs(
    db: Session,
    page: int = 1,
    limit: int = 10,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    search: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user_name: Optional[str] = None,
    request_id: Optional[str] = None,
):
    query = _build_audit_query(
        db=db,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        start_date=start_date,
        end_date=end_date,
        user_name=user_name,
        request_id=request_id,
    )

    total = query.count()

    rows = (
        query
        .order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    items = [_row_to_item(log, name, req_number) for log, name, req_number in rows]

    empty_message = (
        "No audit records match the selected filters." if total == 0 else None
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "empty_message": empty_message,
    }


# Column order is fixed by the contract (openapi-sprint6.yaml, GET /audit-logs/export).
# ip_address is deliberately absent: it is personal data under GDPR, US-011 never
# asks for it, and a CSV leaves the system the moment it is downloaded.
AUDIT_EXPORT_COLUMNS = [
    "id",
    "timestamp",
    "user_name",
    "user_id",
    "action",
    "resource_type",
    "request_id",
    "old_status",
    "new_status",
]


def export_audit_logs_csv(
    db: Session,
    admin_id: int,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    search: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user_name: Optional[str] = None,
    request_id: Optional[str] = None,
) -> str:
    """
    Builds the CSV text for GET /audit-logs/export (US-011).

    Same filters as the list endpoint, but NO paging: an export that silently
    stopped at row 10 would be useless as a compliance record, so every matching
    row is returned.
    """
    query = _build_audit_query(
        db=db,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        start_date=start_date,
        end_date=end_date,
        user_name=user_name,
        request_id=request_id,
    )

    rows = query.order_by(AuditLog.timestamp.desc()).all()

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=AUDIT_EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for log, name, req_number in rows:
        item = _row_to_item(log, name, req_number)
        # Timestamps go out in the ISO format the contract shows
        # (2026-07-20T10:30:00Z); they are stored as naive UTC.
        item["timestamp"] = (
            log.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") if log.timestamp else ""
        )
        writer.writerow(item)

    # Decision S: exporting the audit trail is itself an auditable admin action.
    db.add(AuditLog(
        user_id=admin_id,
        action="AUDIT_LOG_EXPORTED",
        resource_type="audit_log",
        resource_id=None,
    ))
    db.commit()

    logger.info("AUDIT_LOG_EXPORTED — admin_id=%d rows=%d", admin_id, len(rows))

    return buffer.getvalue()


# ============================================================================
# US-012 (IT35-310) — GET /admin/activity/export
# ============================================================================

# Column order is fixed by the contract (openapi-sprint6.yaml, GET
# /admin/activity/export).
ADMIN_ACTIVITY_EXPORT_COLUMNS = [
    "admin_id",
    "action_type",
    "timestamp",
]


def export_my_admin_activity_csv(
    db: Session,
    admin_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    action: Optional[str] = None,
) -> Tuple[str, int]:
    """
    US-012 (IT35-310) — CSV of the admin actions the caller performed
    themselves, e.g. USER_ROLE_CHANGED, USER_DEACTIVATED, REQUEST_TYPE_CREATED.

    This is NOT the system-wide audit log (GET /audit-logs, US-011) — it is
    one admin's own personal copy of their own activity, which US-012 grants
    to every role. Both endpoints read the same audit_log table.

    Decision R: no `user_name` filter here — the caller is already the only
    admin in the result set, so filtering by their own name would be
    meaningless. Only date_range and action_type are accepted.

    Reuses _build_audit_query for the date/action filtering and the same 400
    "start_date after end_date" check the other audit endpoints already use,
    then scopes the result to this admin's own rows.

    Scoping note (decision Q): admin_id comes from the token in the route;
    there is no parameter that could point at anybody else's activity.

    Raises:
        400 - start_date is after end_date
    """
    query = _build_audit_query(
        db=db,
        action=action,
        start_date=start_date,
        end_date=end_date,
    ).filter(AuditLog.user_id == admin_id)

    rows = query.order_by(AuditLog.timestamp.desc()).all()

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=ADMIN_ACTIVITY_EXPORT_COLUMNS)
    writer.writeheader()
    for log, _name, _req_number in rows:
        writer.writerow({
            "admin_id": log.user_id,
            "action_type": log.action,
            "timestamp": log.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") if log.timestamp else "",
        })

    # Decision S: exporting personal data is itself an auditable event.
    db.add(AuditLog(
        user_id=admin_id,
        action="DATA_EXPORTED",
        resource_type="admin_activity",
        resource_id=None,
    ))
    db.commit()

    logger.info("DATA_EXPORTED — admin_id=%d rows=%d", admin_id, len(rows))

    return buffer.getvalue(), len(rows)


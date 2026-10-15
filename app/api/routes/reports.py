# app/api/routes/reports.py
# IT35-276 (US-010, IT35-63) — GET /reports/requests JSON dashboard endpoint

import csv
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.schemas.report import RequestReportResponse
from app.services.report_service import generate_report, fetch_report_rows

# CSV column order per OpenAPI spec (IT35-277).
CSV_COLUMNS = [
    "request_id",
    "request_type",
    "title",
    "requester_name",
    "approver_name",
    "status",
    "submission_date",
    "decision_date",
    "completion_date",
    "cancellation_date",
]

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/requests", response_model=RequestReportResponse)
def get_request_report(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    request_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only admins can access reports."
        )

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date."
        )

    report = generate_report(
        db=db,
        start_date=start_date,
        end_date=end_date,
        request_type=request_type,
        status=status,
    )

    db.add(AuditLog(
        user_id=current_user.id,
        action="REPORT_GENERATED",
        resource_type="report",
        resource_id=None,
    ))
    db.commit()

    return report


@router.get("/requests/export")
def export_request_report(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    request_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # IT35-277 (US-010) — admin-only CSV export of the raw request rows.
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only admins can access reports."
        )

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date."
        )

    rows = fetch_report_rows(
        db=db,
        start_date=start_date,
        end_date=end_date,
        request_type=request_type,
        status=status,
    )

    # Build the CSV text in memory: header row first, then one line per request.
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    csv_text = buffer.getvalue()

    db.add(AuditLog(
        user_id=current_user.id,
        action="REPORT_EXPORTED",
        resource_type="report",
        resource_id=None,
    ))
    db.commit()

    filename = f"request-report-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User, UserRole
from app.schemas.audit_log import AuditLogListResponse
from app.services.audit_service import get_audit_logs, export_audit_logs_csv


router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit Logs"],
)


@router.get(
    "",
    response_model=AuditLogListResponse,
)
def list_audit_logs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100),
    action: Optional[str] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
    resource_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    user_name: Optional[str] = Query(default=None),
    request_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access audit logs.",
        )

    return get_audit_logs(
        db=db,
        page=page,
        limit=limit,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        start_date=start_date,
        end_date=end_date,
        user_name=user_name,
        request_id=request_id,
    )


@router.get("/export")
def export_audit_logs(
    action: Optional[str] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
    resource_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    user_name: Optional[str] = Query(default=None),
    request_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    IT35-306 (US-011) — admin-only CSV export of the audit trail.

    No page/limit here on purpose: the export always covers every row matching
    the filters (see openapi-sprint6.yaml, GET /audit-logs/export).
    """
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access audit logs.",
        )

    csv_text = export_audit_logs_csv(
        db=db,
        admin_id=current_user.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        search=search,
        start_date=start_date,
        end_date=end_date,
        user_name=user_name,
        request_id=request_id,
    )

    filename = f"audit-logs-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

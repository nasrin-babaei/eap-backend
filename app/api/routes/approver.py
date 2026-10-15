# app/api/routes/approver.py

# `status` is imported as `http_status` because the approval queue endpoint has a
# query parameter called `status` — a plain `status` import would be shadowed by it.
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.schemas.comment import CommentListResponse
from app.services.comment_service import get_comments_for_approver
from app.database import get_db
from app.api.dependencies import get_current_user
from app.models.request import RequestStatus
from app.models.user import User, UserRole
from app.schemas.approver import (
    ApprovalQueueResponse,
    ApproveRequestBody,
    RejectRequestBody,
    ApprovalDecisionResponse,
)
from app.schemas.request import RequestDetailsResponse
from app.services.approver_service import (
    get_approval_queue,
    get_status_counts,
    approve_request,
    reject_request,
    get_approver_request_details,
    export_my_decisions_csv,
)

router = APIRouter(
    prefix="/approver",
    tags=["Approver"]
)


@router.get(
    "/requests",
    response_model=ApprovalQueueResponse
)
def get_approval_queue_endpoint(
    status: str = Query(default="pending"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """US-024 — one endpoint serves all five dashboard tabs.

    The default is still `pending`, so a frontend that has not been updated yet
    keeps getting the same tab it got before Sprint 5.
    """
    if current_user.role not in [UserRole.approver, UserRole.admin]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only approvers and admins can access the approval queue"
        )

    # The role check comes first on purpose: an unauthorised caller must not be
    # able to tell a valid status from an invalid one.
    valid_statuses = [s.value for s in RequestStatus]
    if status not in valid_statuses:
        # The spec types this 422 as HTTPValidationError, so `detail` has to be a
        # list of {loc, msg, type} — the same shape FastAPI produces for `limit`.
        # A plain string here would give the frontend two shapes for one status code.
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "loc": ["query", "status"],
                    "msg": f"Invalid status value: '{status}'",
                    "type": "value_error",
                }
            ],
        )

    queue = get_approval_queue(
        db=db,
        approver_id=current_user.id,
        status=status,
        page=page,
        limit=limit,
    )

    # status_counts is deliberately fetched separately: the five tab badges must
    # show every status, not only the tab the approver is currently looking at.
    return {
        **queue,
        "status_counts": get_status_counts(db=db, approver_id=current_user.id),
    }


# US-012 (IT35-310) — this route MUST stay above /requests/{request_id}.
# FastAPI matches routes top to bottom, and request_id is a plain string, so
# /requests/export would otherwise be read as "the request whose id is export"
# and return 404. Same reasoning as /requests/export in requests.py (IT35-309).
@router.get("/requests/export")
def export_my_decisions(
    start_date: Optional[date] = Query(default=None, description="Inclusive, on decision_date"),
    end_date: Optional[date] = Query(default=None, description="Inclusive, on decision_date"),
    request_type: Optional[str] = Query(default=None, description="Request type slug"),
    decision: Optional[str] = Query(default=None, description="approved or rejected"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    US-012 (IT35-310) — the caller downloads the decisions they made
    themselves, as CSV. Open to approvers and admins (admins act as
    approvers too — see the queue endpoint above); there is no role
    check for requesters because they have no decisions to export.
    """
    # Role check first, same principle as the queue endpoint above: an
    # unauthorised caller must not be able to tell a valid decision value
    # from an invalid one.
    if current_user.role not in [UserRole.approver, UserRole.admin]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only approver or admin roles can export approval decisions."
        )

    if decision is not None and decision not in ("approved", "rejected"):
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "loc": ["query", "decision"],
                    "msg": f"Invalid decision value: '{decision}'. Valid values: ['approved', 'rejected']",
                    "type": "value_error",
                }
            ],
        )

    csv_text, row_count = export_my_decisions_csv(
        db=db,
        approver_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        request_type=request_type,
        decision=decision,
    )

    filename = f"my-decisions-{datetime.utcnow().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Decision T — lets the frontend show "N rows exported" as US-012's
            # success confirmation. The body is the file itself, so there is
            # nowhere else to put a number.
            "X-Export-Row-Count": str(row_count),
        },
    )


@router.get(
    "/requests/{request_id}",
    response_model=RequestDetailsResponse
)
def get_approver_request_details_endpoint(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.approver, UserRole.admin]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only approvers and admins can access this endpoint."
        )

    try:
        request = get_approver_request_details(db, request_id, current_user.id)
    except PermissionError as e:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )

    if not request:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Request not found."
        )

    return request


@router.patch(
    "/requests/{request_id}/approve",
    response_model=ApprovalDecisionResponse
)
def approve_request_endpoint(
    request_id: str,
    body: ApproveRequestBody = ApproveRequestBody(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.approver, UserRole.admin]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only approvers and admins can access this endpoint."
        )

    return approve_request(
        db=db,
        request_number=request_id,
        approver_id=current_user.id,
        comment=body.comment
    )


@router.patch(
    "/requests/{request_id}/reject",
    response_model=ApprovalDecisionResponse
)
def reject_request_endpoint(
    request_id: str,
    body: RejectRequestBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.approver, UserRole.admin]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only approvers and admins can access this endpoint."
        )

    return reject_request(
        db=db,
        request_number=request_id,
        approver_id=current_user.id,
        reason=body.reason
    )


@router.get(
    "/requests/{request_id}/comments",
    response_model=CommentListResponse
)
def get_approver_request_comments(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in [UserRole.approver, UserRole.admin]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Only approvers and admins can access this endpoint."
        )
    try:
        comments = get_comments_for_approver(
            db=db,
            request_id=request_id,
            approver_id=current_user.id
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    if comments is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Request not found."
        )
    return {"items": comments}


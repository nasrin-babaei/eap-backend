# app/api/routes/requests.py

from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.dependencies import get_current_user
from app.models.user import User, UserRole
from app.schemas.request import RequestCreate, RequestResponse, RequestListResponse, RequestDetailsResponse, RequestActionResponse
from app.services.request_service import (
    create_request,
    get_user_requests,
    get_request_details,
    complete_request,
    cancel_request,
    export_my_requests_csv,
)
from app.schemas.comment import CommentListResponse, CommentCreate, CommentResponse
from app.services.comment_service import get_comments_for_requester, create_comment

router = APIRouter(
    prefix="/requests",
    tags=["Requests"]
)


@router.post(
    "",
    response_model=RequestResponse,
    status_code=status.HTTP_201_CREATED
)
def submit_request(
    payload: RequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        return create_request(
            db=db,
            user_id=current_user.id,
            data=payload
        )
    except LookupError as e:
        # US-017 (decision M): a slug that does not exist is bad input -> 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except ValueError as e:
        # US-017 (decision M): the type exists but an admin deactivated it.
        # The input was valid when the form was rendered, so this is a 400,
        # not a validation error.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get(
    "",
    response_model=RequestListResponse
)
def list_requests(
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=10, ge=1, le=100, description="Items per page"),
    request_status: Optional[str] = Query(default=None, alias="status", description="Filter by status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # US-019: approvers submit requests of their own, so they may use the requester
    # endpoints too. Each service below still scopes the result to the caller's own
    # requests, so an approver can never reach someone else's request this way.
    if current_user.role not in (UserRole.requester, UserRole.approver):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are unauthorized for this section."
        )

    try:
        return get_user_requests(
            db=db,
            user_id=current_user.id,
            page=page,
            limit=limit,
            status=request_status
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# US-012 (IT35-309) — this route MUST stay above /{request_id}.
# FastAPI matches routes top to bottom, and request_id is a plain string, so
# /requests/export would otherwise be read as "the request whose id is export"
# and return 404. Moving this block down is a silent bug.
@router.get("/export")
def export_my_requests(
    start_date: Optional[date] = Query(default=None, description="Inclusive, on submission date"),
    end_date: Optional[date] = Query(default=None, description="Inclusive, on submission date"),
    request_type: Optional[str] = Query(default=None, description="Request type slug"),
    request_status: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    US-012 (IT35-309) — the caller downloads their OWN request history as CSV.

    Open to every authenticated role: approvers and admins submit requests of
    their own too (US-019), and US-012 gives every user the right to a copy of
    their data. There is no role check for that reason — the scoping is done by
    passing current_user.id, which the caller cannot influence.
    """
    csv_text, row_count = export_my_requests_csv(
        db=db,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        request_type=request_type,
        status=request_status,
    )

    filename = f"my-requests-{datetime.utcnow().strftime('%Y%m%d')}.csv"
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
    "/{request_id}",
    response_model=RequestDetailsResponse
)
def get_request_by_id(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in (UserRole.requester, UserRole.approver):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are unauthorized for this section."
        )

    try:
        request = get_request_details(
            db=db,
            user_id=current_user.id,
            request_id=request_id
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )

    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found."
        )

    return request


@router.get(
    "/{request_id}/comments",
    response_model=CommentListResponse
)
def get_request_comments(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in (UserRole.requester, UserRole.approver):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are unauthorized for this section."
        )
    try:
        comments = get_comments_for_requester(
            db=db,
            request_id=request_id,
            user_id=current_user.id
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    if comments is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Request not found."
        )
    return {
        "items": comments}


@router.post(
    "/{request_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED
)
def post_request_comment(
    request_id: str,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in (UserRole.requester, UserRole.approver):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are unauthorized for this section."
        )
    try:
        comment = create_comment(
            db=db,
            request_id=request_id,
            author_id=current_user.id,
            content=payload.comment
        )
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    return {
        "id": comment.id,
        "request_id": request_id,
        "author_id": comment.author_id,
        "author_name": current_user.name,
        "content": comment.content,
        "created_at": comment.created_at,
    }

@router.patch(
    "/{request_id}/complete",
    response_model=RequestActionResponse
)
def complete_request_endpoint(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in (UserRole.requester, UserRole.approver):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are unauthorized for this section."
        )

    return complete_request(db=db, request_id=request_id, user_id=current_user.id)


@router.patch(
    "/{request_id}/cancel",
    response_model=RequestActionResponse
)
def cancel_request_endpoint(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return cancel_request(
        db=db,
        request_id=request_id,
        user_id=current_user.id,
        user_role=current_user.role
    )

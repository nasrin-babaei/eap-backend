from fastapi import APIRouter, Depends
from app.api.dependencies import get_current_user, require_permission
from app.core.permission import REQUESTS, APPROVALS, ADMIN, DASHBOARD
from app.models.user import User


router = APIRouter(
    prefix="/rbac",
    tags=["RBAC"],
)


@router.get("/dashboard")
def get_dashboard(
    current_user: User = Depends(get_current_user),
):
    require_permission(current_user.role.value, DASHBOARD)

    return {
        "message": f"Welcome to the dashboard, {current_user.email}",
        "role": current_user.role.value,
    }


@router.get("/requests")
def get_requests(
    current_user: User = Depends(get_current_user),
):
    require_permission(current_user.role.value, REQUESTS)

    return {
        "message": "Requests list",
        "role": current_user.role.value,
        "accessible": True,
    }


@router.get("/approvals")
def get_approvals(
    current_user: User = Depends(get_current_user),
):
    require_permission(current_user.role.value, APPROVALS)

    return {
        "message": "Approvals list",
        "role": current_user.role.value,
        "accessible": True,
    }


@router.get("/admin")
def get_admin_panel(
    current_user: User = Depends(get_current_user),
):
    require_permission(current_user.role.value, ADMIN)

    return {
        "message": f"Admin panel — welcome {current_user.email}",
        "role": current_user.role.value,
        "accessible": True,
    }


@router.get("/admin/users")
def get_admin_users(
    current_user: User = Depends(get_current_user),
):
    require_permission(current_user.role.value, ADMIN)

    return {
        "message": "User management",
        "role": current_user.role.value,
        "accessible": True,
    }


@router.get("/me")
def get_me(
    current_user: User = Depends(get_current_user),
):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role.value,
    }
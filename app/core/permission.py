REQUESTS = "requests"
APPROVALS = "approvals"
ADMIN = "admin"
DASHBOARD = "dashboard"


ROLE_PERMISSIONS = {
    "requester": [REQUESTS],
    "approver": [APPROVALS, REQUESTS],
    "admin": [ADMIN, APPROVALS, REQUESTS, DASHBOARD],
}
def can_access(role: str, resource: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(role, [])
    return resource in permissions
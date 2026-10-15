# tests/unit/test_admin_routes.py
# US-012 (IT35-310) - GET /admin/activity/export route-level tests.
# Uses FastAPI's TestClient; the service function is patched so these tests
# never touch a database.

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.dependencies import get_current_user
from app.database import get_db
from app.models.user import User, UserRole


def make_user(role: UserRole, user_id: int = 1) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    return user


def client_as(role: UserRole):
    app.dependency_overrides[get_current_user] = lambda: make_user(role)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


class TestAdminActivityExportRoute:

    def test_admin_can_export(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.admin.export_my_admin_activity_csv",
            return_value=(
                "admin_id,action_type,timestamp\r\n"
                "1,USER_ROLE_CHANGED,2026-07-15T13:45:00Z\r\n",
                1,
            ),
        ) as mock_export:
            response = client.get(
                "/api/admin/activity/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        assert response.headers["x-export-row-count"] == "1"
        assert "attachment" in response.headers["content-disposition"]
        assert "my-admin-activity-" in response.headers["content-disposition"]
        assert mock_export.call_args.kwargs["admin_id"] == 1

    @pytest.mark.parametrize("role", [UserRole.requester, UserRole.approver])
    def test_non_admin_cannot_export(self, role):
        client = client_as(role)
        with patch("app.api.routes.admin.export_my_admin_activity_csv") as mock_export:
            response = client.get(
                "/api/admin/activity/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Only admins can export admin activity."
        mock_export.assert_not_called()

    def test_filters_are_passed_through(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.admin.export_my_admin_activity_csv",
            return_value=("", 0),
        ) as mock_export:
            client.get(
                "/api/admin/activity/export",
                params={
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "action": "USER_ROLE_CHANGED",
                },
                headers={"Authorization": "Bearer faketoken"},
            )

        kwargs = mock_export.call_args.kwargs
        assert str(kwargs["start_date"]) == "2026-07-01"
        assert str(kwargs["end_date"]) == "2026-07-31"
        assert kwargs["action"] == "USER_ROLE_CHANGED"

    def test_zero_rows_is_a_valid_success_not_an_error(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.admin.export_my_admin_activity_csv",
            return_value=("admin_id,action_type,timestamp\r\n", 0),
        ):
            response = client.get(
                "/api/admin/activity/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        assert response.headers["x-export-row-count"] == "0"


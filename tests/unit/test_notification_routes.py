# tests/unit/test_notification_routes.py
# IT35-283 (US-014) — PATCH /notifications/{id}/read route-level tests.
# Uses FastAPI's TestClient because what is under test lives in the route:
# turning the service's return value into 200/404, and PermissionError into 403.
# The service function is patched, so these tests never touch a database.

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.dependencies import get_current_user
from app.database import get_db
from app.models.user import User, UserRole


def make_user(role: UserRole = UserRole.requester, user_id: int = 1) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    return user


def make_notification(notification_id: int = 1, user_id: int = 1, is_read: bool = True):
    """A plain object shaped like the Notification model, so the response_model
    can be built from it without a database."""
    return SimpleNamespace(
        id=notification_id,
        user_id=user_id,
        request_id="HD-001",
        request_type="hardware_devices",
        status="approved",
        status_change_date=datetime(2026, 7, 1, 9, 0, 0),
        title="Request Approved",
        message="Your request HD-001 has been approved.",
        is_read=is_read,
        created_at=datetime(2026, 7, 1, 9, 0, 0),
    )


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides never leak between tests."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    """A TestClient authenticated as a normal requester, with no real database."""
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


class TestMarkNotificationReadRoute:

    def test_200_returns_notification_with_is_read_true(self, client):
        with patch(
            "app.api.routes.notifications.mark_notification_read",
            return_value=make_notification(is_read=True),
        ):
            response = client.patch("/api/notifications/1/read")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == 1
        assert body["is_read"] is True

    def test_service_is_called_with_the_caller_id(self, client):
        """The route must pass the logged-in user, never a value from the URL."""
        with patch(
            "app.api.routes.notifications.mark_notification_read",
            return_value=make_notification(),
        ) as mocked:
            client.patch("/api/notifications/7/read")

        assert mocked.call_args.kwargs["notification_id"] == 7
        assert mocked.call_args.kwargs["user_id"] == 1

    def test_404_when_notification_does_not_exist(self, client):
        with patch(
            "app.api.routes.notifications.mark_notification_read",
            return_value=None,
        ):
            response = client.patch("/api/notifications/999/read")

        assert response.status_code == 404
        assert response.json()["detail"] == "Notification not found."

    def test_403_when_notification_belongs_to_another_user(self, client):
        with patch(
            "app.api.routes.notifications.mark_notification_read",
            side_effect=PermissionError("Notification belongs to another user."),
        ):
            response = client.patch("/api/notifications/1/read")

        assert response.status_code == 403
        assert response.json()["detail"] == "Notification belongs to another user."

    def test_401_when_token_is_missing(self):
        """No dependency override here, so the real get_current_user runs and
        rejects the unauthenticated call."""
        app.dependency_overrides[get_db] = lambda: MagicMock()
        unauthenticated = TestClient(app)

        response = unauthenticated.patch("/api/notifications/1/read")

        assert response.status_code == 401

    def test_422_when_notification_id_is_not_an_integer(self, client):
        response = client.patch("/api/notifications/abc/read")

        assert response.status_code == 422
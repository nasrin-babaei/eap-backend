# tests/unit/test_approver_routes.py
# IT35-280 (US-024) — GET /approver/requests route-level tests.
# Uses FastAPI's TestClient because the checks under test (role guard, status
# validation, wiring the two service calls together) live in the route itself.
# The service functions are patched, so these tests never touch a database.

from datetime import datetime
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


def make_item(request_id: str, request_status: str) -> dict:
    """One row of the queue, shaped like ApprovalQueueItem."""
    return {
        "request_id": request_id,
        "requester_name": "Test Requester",
        "request_type": "hardware_devices",
        "submission_date": datetime(2026, 7, 1, 9, 0, 0),
        "request_status": request_status,
        "updated_at": datetime(2026, 7, 2, 9, 0, 0),
    }


def make_queue(status: str = "pending", items=None, empty_message=None) -> dict:
    """What the patched get_approval_queue() returns (Subtask 1's shape)."""
    items = [make_item("HD-001", status)] if items is None else items
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "limit": 20,
        "empty_message": empty_message,
    }


FAKE_COUNTS = {
    "pending": 4,
    "approved": 3,
    "rejected": 2,
    "completed": 1,
    "cancelled": 0,
}


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides never leak between tests."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def approver_client():
    """A TestClient authenticated as an approver, with no real database."""
    app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.approver)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


class TestApprovalQueueTabs:

    def test_default_status_is_pending(self, approver_client):
        """No ?status in the URL must still return the pending tab, so a frontend
        that has not been updated for Sprint 5 keeps working."""
        with patch(
            "app.api.routes.approver.get_approval_queue",
            return_value=make_queue("pending"),
        ) as mock_queue, patch(
            "app.api.routes.approver.get_status_counts", return_value=FAKE_COUNTS
        ):
            response = approver_client.get(
                "/api/approver/requests",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        _, kwargs = mock_queue.call_args
        assert kwargs["status"] == "pending"
        assert kwargs["page"] == 1
        assert kwargs["limit"] == 20

    def test_explicit_status_approved(self, approver_client):
        with patch(
            "app.api.routes.approver.get_approval_queue",
            return_value=make_queue("approved"),
        ) as mock_queue, patch(
            "app.api.routes.approver.get_status_counts", return_value=FAKE_COUNTS
        ):
            response = approver_client.get(
                "/api/approver/requests",
                params={"status": "approved"},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        assert response.json()["items"][0]["request_status"] == "approved"
        _, kwargs = mock_queue.call_args
        assert kwargs["status"] == "approved"

    def test_pagination_is_passed_to_the_service(self, approver_client):
        with patch(
            "app.api.routes.approver.get_approval_queue", return_value=make_queue()
        ) as mock_queue, patch(
            "app.api.routes.approver.get_status_counts", return_value=FAKE_COUNTS
        ):
            response = approver_client.get(
                "/api/approver/requests",
                params={"page": 2, "limit": 5},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        _, kwargs = mock_queue.call_args
        assert kwargs["page"] == 2
        assert kwargs["limit"] == 5

    @pytest.mark.parametrize(
        "status,expected_message",
        [
            ("pending", "No pending requests found."),
            ("approved", "No approved requests found."),
            ("rejected", "No rejected requests found."),
            ("completed", "No completed requests found."),
            ("cancelled", "No cancelled requests found."),
        ],
    )
    def test_empty_message_per_tab(self, approver_client, status, expected_message):
        with patch(
            "app.api.routes.approver.get_approval_queue",
            return_value=make_queue(status, items=[], empty_message=expected_message),
        ), patch(
            "app.api.routes.approver.get_status_counts", return_value=FAKE_COUNTS
        ):
            response = approver_client.get(
                "/api/approver/requests",
                params={"status": status},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["empty_message"] == expected_message


class TestApprovalQueueStatusCounts:

    @pytest.mark.parametrize(
        "status", ["pending", "approved", "rejected", "completed", "cancelled"]
    )
    def test_status_counts_returned_for_every_tab(self, approver_client, status):
        """The five tab badges come from one call, so status_counts must be present
        and identical no matter which tab is selected."""
        with patch(
            "app.api.routes.approver.get_approval_queue",
            return_value=make_queue(status),
        ), patch(
            "app.api.routes.approver.get_status_counts", return_value=FAKE_COUNTS
        ):
            response = approver_client.get(
                "/api/approver/requests",
                params={"status": status},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        assert response.json()["status_counts"] == FAKE_COUNTS


class TestApprovalQueueValidation:

    def test_invalid_status_returns_422(self, approver_client):
        with patch(
            "app.api.routes.approver.get_approval_queue"
        ) as mock_queue, patch(
            "app.api.routes.approver.get_status_counts"
        ) as mock_counts:
            response = approver_client.get(
                "/api/approver/requests",
                params={"status": "not_a_status"},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 422
        # Spec shape: detail is a list of {loc, msg, type}, not a bare string.
        detail = response.json()["detail"]
        assert isinstance(detail, list)
        assert detail[0]["loc"] == ["query", "status"]
        assert "not_a_status" in detail[0]["msg"]
        # The request must be rejected before any database work is done.
        mock_queue.assert_not_called()
        mock_counts.assert_not_called()

    def test_limit_above_maximum_returns_422(self, approver_client):
        """FastAPI's le=100 guard stops an oversized page before it reaches SQL."""
        with patch("app.api.routes.approver.get_approval_queue") as mock_queue:
            response = approver_client.get(
                "/api/approver/requests",
                params={"limit": 5000},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 422
        mock_queue.assert_not_called()

    def test_both_422s_have_the_same_body_shape(self, approver_client):
        """An invalid status and an oversized limit must not give the frontend two
        different shapes for the same status code."""
        with patch("app.api.routes.approver.get_approval_queue"):
            from_status = approver_client.get(
                "/api/approver/requests",
                params={"status": "not_a_status"},
                headers={"Authorization": "Bearer faketoken"},
            ).json()["detail"]
            from_limit = approver_client.get(
                "/api/approver/requests",
                params={"limit": 5000},
                headers={"Authorization": "Bearer faketoken"},
            ).json()["detail"]

        for detail in (from_status, from_limit):
            assert isinstance(detail, list)
            assert {"loc", "msg", "type"} <= set(detail[0].keys())


class TestApprovalQueueAuthorization:

    def test_requester_role_returns_403(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.requester)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.approver.get_approval_queue") as mock_queue:
            client = TestClient(app)
            response = client.get(
                "/api/approver/requests",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 403
        mock_queue.assert_not_called()

    def test_admin_role_is_allowed(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch(
            "app.api.routes.approver.get_approval_queue", return_value=make_queue()
        ), patch(
            "app.api.routes.approver.get_status_counts", return_value=FAKE_COUNTS
        ):
            client = TestClient(app)
            response = client.get(
                "/api/approver/requests",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200

    def test_role_is_checked_before_the_status_value(self):
        """A caller who is not allowed in must get 403, not 422 — otherwise the
        error code alone would tell them which status values exist."""
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.requester)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        client = TestClient(app)
        response = client.get(
            "/api/approver/requests",
            params={"status": "not_a_status"},
            headers={"Authorization": "Bearer faketoken"},
        )

        assert response.status_code == 403

    def test_missing_token_returns_401(self):
        """No dependency override here on purpose — the real get_current_user runs."""
        client = TestClient(app)
        response = client.get("/api/approver/requests")

        assert response.status_code == 401

# ============================================================================
# US-012 (IT35-310) - GET /approver/requests/export
# ============================================================================

def client_as(role: UserRole):
    app.dependency_overrides[get_current_user] = lambda: make_user(role)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


class TestApproverExportRoute:

    def test_approver_can_export(self):
        client = client_as(UserRole.approver)
        with patch(
            "app.api.routes.approver.export_my_decisions_csv",
            return_value=(
                "request_id,approver_id,decision,decision_date,comment\r\n"
                "HD-001,2,approved,2026-07-11T09:00:00Z,Approved.\r\n",
                1,
            ),
        ) as mock_export:
            response = client.get(
                "/api/approver/requests/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        assert response.headers["x-export-row-count"] == "1"
        assert "attachment" in response.headers["content-disposition"]
        assert "my-decisions-" in response.headers["content-disposition"]
        assert mock_export.call_args.kwargs["approver_id"] == 1

    def test_admin_can_also_export(self):
        """Admins act as approvers too - see the queue endpoint."""
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.approver.export_my_decisions_csv",
            return_value=("request_id,approver_id,decision,decision_date,comment\r\n", 0),
        ):
            response = client.get(
                "/api/approver/requests/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200

    def test_requester_cannot_export(self):
        client = client_as(UserRole.requester)
        with patch("app.api.routes.approver.export_my_decisions_csv") as mock_export:
            response = client.get(
                "/api/approver/requests/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Only approver or admin roles can export approval decisions."
        )
        mock_export.assert_not_called()

    def test_filters_are_passed_through(self):
        client = client_as(UserRole.approver)
        with patch(
            "app.api.routes.approver.export_my_decisions_csv",
            return_value=("", 0),
        ) as mock_export:
            client.get(
                "/api/approver/requests/export",
                params={
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "request_type": "hardware_devices",
                    "decision": "approved",
                },
                headers={"Authorization": "Bearer faketoken"},
            )

        kwargs = mock_export.call_args.kwargs
        assert str(kwargs["start_date"]) == "2026-07-01"
        assert str(kwargs["end_date"]) == "2026-07-31"
        assert kwargs["request_type"] == "hardware_devices"
        assert kwargs["decision"] == "approved"

    def test_invalid_decision_value_returns_422(self):
        client = client_as(UserRole.approver)
        with patch("app.api.routes.approver.export_my_decisions_csv") as mock_export:
            response = client.get(
                "/api/approver/requests/export",
                params={"decision": "maybe"},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 422
        mock_export.assert_not_called()

    def test_unauthorized_role_checked_before_invalid_decision_value(self):
        """Role check must come first: an unauthorised caller should get 403,
        not 422, even with an invalid filter value - otherwise they could
        learn the filter was invalid before being told they're forbidden."""
        client = client_as(UserRole.requester)
        response = client.get(
            "/api/approver/requests/export",
            params={"decision": "maybe"},
            headers={"Authorization": "Bearer faketoken"},
        )

        assert response.status_code == 403


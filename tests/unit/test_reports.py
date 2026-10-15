# tests/unit/test_reports.py
# IT35-276 (US-010) — GET /reports/requests route-level tests.
# Uses FastAPI's TestClient since the checks under test (role guard, date
# validation, audit logging) live in the route itself, not in a pure
# service function.

from datetime import date, datetime
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


FAKE_REPORT = {
    "filters": {
        "start_date": None,
        "end_date": None,
        "request_type": None,
        "status": None,
    },
    "totals": {
        "total_requests": 3,
        "pending": 2,
        "approved": 0,
        "rejected": 0,
        "completed": 0,
        "cancelled": 1,
    },
    "approval_rate": 0.0,
    "rejection_rate": 0.0,
    "generated_at": datetime.utcnow(),
}


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides never leak between tests."""
    yield
    app.dependency_overrides.clear()


class TestGetRequestReport:

    def test_200_all_filters_omitted(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.generate_report", return_value=FAKE_REPORT) as mock_gen:
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["totals"]["total_requests"] == 3
        mock_gen.assert_called_once()
        _, kwargs = mock_gen.call_args
        assert kwargs["start_date"] is None
        assert kwargs["end_date"] is None
        assert kwargs["request_type"] is None
        assert kwargs["status"] is None

    def test_200_all_filters_provided(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.generate_report", return_value=FAKE_REPORT) as mock_gen:
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests",
                params={
                    "start_date": "2026-01-01",
                    "end_date": "2026-07-01",
                    "request_type": "hardware_devices",
                    "status": "pending",
                },
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        mock_gen.assert_called_once()
        _, kwargs = mock_gen.call_args
        assert kwargs["start_date"] == date(2026, 1, 1)
        assert kwargs["end_date"] == date(2026, 7, 1)
        assert kwargs["request_type"] == "hardware_devices"
        assert kwargs["status"] == "pending"

    def test_400_invalid_date_range(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.generate_report") as mock_gen:
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests",
                params={"start_date": "2026-07-23", "end_date": "2026-01-01"},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "start_date cannot be after end_date."
        mock_gen.assert_not_called()

    def test_403_requester_forbidden(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.requester)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.generate_report") as mock_gen:
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Only admins can access reports."
        mock_gen.assert_not_called()

    def test_403_approver_forbidden(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.approver)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.generate_report") as mock_gen:
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Only admins can access reports."
        mock_gen.assert_not_called()

    def test_401_missing_token(self):
        # No dependency override for get_current_user here — the real
        # HTTPBearer security scheme should reject the request before
        # get_current_user (or the route) ever runs.
        client = TestClient(app)
        response = client.get("/api/reports/requests")

        assert response.status_code == 401

    def test_audit_log_written_on_success(self):
        db = MagicMock()
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin, user_id=7)
        app.dependency_overrides[get_db] = lambda: db

        with patch("app.api.routes.reports.generate_report", return_value=FAKE_REPORT):
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        db.add.assert_called_once()
        audit_entry = db.add.call_args[0][0]
        assert audit_entry.action == "REPORT_GENERATED"
        assert audit_entry.resource_type == "report"
        assert audit_entry.resource_id is None
        assert audit_entry.user_id == 7
        db.commit.assert_called_once()


FAKE_ROWS = [
    {
        "request_id": "HD-001",
        "request_type": "hardware_devices",
        "title": "Need a new laptop",
        "requester_name": "Nasrin Babaei",
        "approver_name": "Jane Manager",
        "status": "completed",
        "submission_date": "2026-07-10T10:30:00Z",
        "decision_date": "2026-07-11T09:00:00Z",
        "completion_date": "2026-07-12T08:15:00Z",
        "cancellation_date": None,
    },
]


class TestExportRequestReport:
    """IT35-277 (US-010) — GET /reports/requests/export CSV route tests."""

    def test_200_returns_csv_headers(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.fetch_report_rows", return_value=FAKE_ROWS):
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        assert "request-report-" in disposition
        assert disposition.endswith('.csv"')

    def test_csv_column_headers_in_correct_order(self):
        from app.api.routes.reports import CSV_COLUMNS

        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.fetch_report_rows", return_value=FAKE_ROWS):
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        first_line = response.text.splitlines()[0]
        assert first_line == ",".join(CSV_COLUMNS)

    def test_csv_rows_map_from_fetch_report_rows(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.fetch_report_rows", return_value=FAKE_ROWS):
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        body = response.text
        assert "HD-001" in body
        assert "Need a new laptop" in body
        assert "Jane Manager" in body
        assert "completed" in body

    def test_403_requester_forbidden(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.requester)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.fetch_report_rows") as mock_rows:
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 403
        assert response.json()["detail"] == "Only admins can access reports."
        mock_rows.assert_not_called()

    def test_400_invalid_date_range(self):
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin)
        app.dependency_overrides[get_db] = lambda: MagicMock()

        with patch("app.api.routes.reports.fetch_report_rows") as mock_rows:
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests/export",
                params={"start_date": "2026-07-23", "end_date": "2026-01-01"},
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "start_date cannot be after end_date."
        mock_rows.assert_not_called()

    def test_401_missing_token(self):
        client = TestClient(app)
        response = client.get("/api/reports/requests/export")

        assert response.status_code == 401

    def test_audit_log_written_on_success(self):
        db = MagicMock()
        app.dependency_overrides[get_current_user] = lambda: make_user(UserRole.admin, user_id=7)
        app.dependency_overrides[get_db] = lambda: db

        with patch("app.api.routes.reports.fetch_report_rows", return_value=FAKE_ROWS):
            client = TestClient(app)
            response = client.get(
                "/api/reports/requests/export",
                headers={"Authorization": "Bearer faketoken"},
            )

        assert response.status_code == 200
        db.add.assert_called_once()
        audit_entry = db.add.call_args[0][0]
        assert audit_entry.action == "REPORT_EXPORTED"
        assert audit_entry.resource_type == "report"
        assert audit_entry.resource_id is None
        assert audit_entry.user_id == 7
        db.commit.assert_called_once()
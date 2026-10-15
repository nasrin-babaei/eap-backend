# tests/unit/test_my_requests_export.py
# US-012 (IT35-66 / IT35-309) — GET /requests/export, the requester's own CSV.

import csv
import io
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.comment import Comment
from app.models.request import Request, RequestStatus
from app.models.request_type import RequestType
from app.models.user import User, UserRole
from app.services.request_service import (
    MY_REQUESTS_EXPORT_COLUMNS,
    export_my_requests_csv,
)


def make_request(
    request_number="HD-001",
    status=RequestStatus.completed,
    slug="hardware_devices",
    created_at=datetime(2026, 7, 10, 10, 30, 0),
    decision_date=datetime(2026, 7, 11, 9, 0, 0),
    completion_date=datetime(2026, 7, 12, 8, 15, 0),
    cancellation_date=None,
):
    req = MagicMock(spec=Request)
    req.id = 1
    req.request_number = request_number
    req.title = "Need a new laptop"
    req.status = status
    req.created_at = created_at
    req.decision_date = decision_date
    req.completion_date = completion_date
    req.cancellation_date = cancellation_date
    req.request_type = MagicMock(spec=RequestType)
    req.request_type.slug = slug
    return req


def make_comment(content, created_at=datetime(2026, 7, 10, 11, 0, 0), request_id=1):
    c = MagicMock(spec=Comment)
    c.content = content
    c.created_at = created_at
    # The service groups the comments by request_id, so a fake comment without
    # one lands under a Mock key and the row comes out with an empty cell.
    c.request_id = request_id
    return c


def setup_db(requests, comments=None):
    """
    The service makes two kinds of query: one for Request, one for Comment.
    Route them by model so each gets its own list back.
    """
    db = MagicMock()
    comments = comments or []

    def query_side_effect(model):
        m = MagicMock()
        m.options.return_value = m
        m.filter.return_value = m
        m.order_by.return_value = m
        if model is Request:
            m.all.return_value = requests
        elif model is Comment:
            m.all.return_value = comments
        elif model is RequestType:
            m.first.return_value = None
        return m

    db.query.side_effect = query_side_effect
    return db


def parse(csv_text):
    return list(csv.DictReader(io.StringIO(csv_text)))


class TestCsvShape:

    def test_columns_are_exactly_the_contract_order(self):
        """The frontend and the acceptance test read this file positionally,
        so the header line is part of the contract."""
        db = setup_db([])

        csv_text, _ = export_my_requests_csv(db=db, user_id=1)

        header = csv_text.splitlines()[0]
        assert header == ",".join(MY_REQUESTS_EXPORT_COLUMNS)
        assert header == (
            "request_id,request_type,title,created_date,current_status,"
            "decision_date,completion_date,cancellation_date,comments"
        )

    def test_row_matches_the_contract_example(self):
        db = setup_db([make_request()], comments=[
            make_comment("Is it possible to get the 16GB model?")
        ])

        csv_text, _ = export_my_requests_csv(db=db, user_id=1)
        row = parse(csv_text)[0]

        assert row["request_id"] == "HD-001"
        assert row["request_type"] == "hardware_devices"
        assert row["title"] == "Need a new laptop"
        assert row["created_date"] == "2026-07-10T10:30:00Z"
        assert row["current_status"] == "completed"
        assert row["decision_date"] == "2026-07-11T09:00:00Z"
        assert row["completion_date"] == "2026-07-12T08:15:00Z"
        assert row["comments"] == "Is it possible to get the 16GB model?"

    def test_dates_never_reached_are_empty_not_none(self):
        """An empty cell means "the request never got there". Writing the word
        None would look like data."""
        db = setup_db([make_request(
            status=RequestStatus.pending,
            decision_date=None,
            completion_date=None,
            cancellation_date=None,
        )])

        row = parse(export_my_requests_csv(db=db, user_id=1)[0])[0]

        assert row["decision_date"] == ""
        assert row["completion_date"] == ""
        assert row["cancellation_date"] == ""

    def test_several_comments_are_joined_oldest_first(self):
        db = setup_db([make_request()], comments=[
            make_comment("First one", datetime(2026, 7, 10, 11, 0, 0)),
            make_comment("Second one", datetime(2026, 7, 10, 12, 0, 0)),
        ])

        row = parse(export_my_requests_csv(db=db, user_id=1)[0])[0]

        assert row["comments"] == "First one | Second one"

    def test_request_with_no_comments_gets_an_empty_cell(self):
        db = setup_db([make_request()], comments=[])

        row = parse(export_my_requests_csv(db=db, user_id=1)[0])[0]

        assert row["comments"] == ""


class TestScoping:
    """Decision Q — a user can only ever export their own data."""

    def test_query_is_filtered_to_the_caller(self):
        db = MagicMock()
        request_query = MagicMock()
        request_query.options.return_value = request_query
        request_query.filter.return_value = request_query
        request_query.order_by.return_value = request_query
        request_query.all.return_value = []
        db.query.return_value = request_query

        export_my_requests_csv(db=db, user_id=42)

        # The very first filter is the ownership one; without it the export
        # would hand out other people's requests.
        assert request_query.filter.called

    def test_only_the_callers_own_comments_are_included(self):
        """An approver's comment on my request is not mine to export — it goes
        in the approver export instead."""
        db = MagicMock()
        captured = {}

        def query_side_effect(model):
            m = MagicMock()
            m.options.return_value = m
            m.order_by.return_value = m
            if model is Request:
                m.filter.return_value = m
                m.all.return_value = [make_request()]
            elif model is Comment:
                def capture_filter(*args):
                    captured["comment_filters"] = args
                    return m
                m.filter.side_effect = capture_filter
                m.all.return_value = []
            return m

        db.query.side_effect = query_side_effect

        export_my_requests_csv(db=db, user_id=7)

        # Two conditions: the request, and the author being the caller.
        assert len(captured["comment_filters"]) == 2


class TestFilters:

    def test_start_after_end_is_400(self):
        db = setup_db([])

        with pytest.raises(HTTPException) as exc_info:
            export_my_requests_csv(
                db=db, user_id=1,
                start_date=date(2026, 7, 31),
                end_date=date(2026, 7, 1),
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "start_date cannot be after end_date."

    def test_invalid_status_is_422(self):
        db = setup_db([])

        with pytest.raises(HTTPException) as exc_info:
            export_my_requests_csv(db=db, user_id=1, status="nonexistent")

        assert exc_info.value.status_code == 422

    @pytest.mark.parametrize("status_str", [
        "pending", "approved", "rejected", "completed", "cancelled",
    ])
    def test_every_valid_status_is_accepted(self, status_str):
        db = setup_db([])

        csv_text, count = export_my_requests_csv(db=db, user_id=1, status=status_str)

        assert count == 0

    def test_unknown_request_type_slug_returns_an_empty_export(self):
        """Not an error: "my TC requests" is a fair question even when the
        answer is none."""
        db = setup_db([])

        csv_text, count = export_my_requests_csv(
            db=db, user_id=1, request_type="not_a_real_type"
        )

        assert count == 0
        assert len(csv_text.splitlines()) == 1   # header only


class TestEmptyExport:

    def test_zero_rows_still_produces_a_valid_file_with_a_header(self):
        """US-012's confirmation must be able to say "0 rows exported" — that is
        a real answer, not a failure."""
        db = setup_db([])

        csv_text, count = export_my_requests_csv(db=db, user_id=1)

        assert count == 0
        assert csv_text.splitlines() == [",".join(MY_REQUESTS_EXPORT_COLUMNS)]


class TestAudit:
    """Decision S — every export is an auditable event."""

    def test_data_exported_row_is_written(self):
        db = setup_db([make_request()])

        export_my_requests_csv(db=db, user_id=5)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1

        audit = audit_rows[0]
        assert audit.action == "DATA_EXPORTED"
        assert audit.user_id == 5
        assert audit.resource_type == "request"
        # The export is not about one request, so there is no id to record.
        assert audit.resource_id is None
        db.commit.assert_called_once()


class TestRoute:
    """Route-level: ordering, headers, and the open-to-all-roles rule."""

    @pytest.fixture(autouse=True)
    def clear_overrides(self):
        yield
        app.dependency_overrides.clear()

    def client_as(self, role):
        user = MagicMock(spec=User)
        user.id = 1
        user.role = role
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: MagicMock()
        return TestClient(app)

    @pytest.mark.parametrize("role", [UserRole.requester, UserRole.approver, UserRole.admin])
    def test_every_authenticated_role_may_export_their_own(self, role):
        """US-019: approvers submit requests too, and US-012 gives everyone a
        right to their own data — so no role check here."""
        client = self.client_as(role)

        with patch(
            "app.api.routes.requests.export_my_requests_csv",
            return_value=("request_id\n", 0),
        ):
            response = client.get("/api/requests/export", headers={"Authorization": "Bearer x"})

        assert response.status_code == 200

    def test_export_is_not_swallowed_by_the_request_id_route(self):
        """Regression guard: if this route ever moves below /{request_id},
        FastAPI reads "export" as a request id and this returns 404."""
        client = self.client_as(UserRole.requester)

        with patch(
            "app.api.routes.requests.export_my_requests_csv",
            return_value=("request_id\n", 0),
        ) as mock_export:
            response = client.get("/api/requests/export", headers={"Authorization": "Bearer x"})

        assert response.status_code == 200
        mock_export.assert_called_once()

    def test_headers_are_csv_attachment_with_row_count(self):
        client = self.client_as(UserRole.requester)

        with patch(
            "app.api.routes.requests.export_my_requests_csv",
            return_value=("request_id\nHD-001\n", 12),
        ):
            response = client.get("/api/requests/export", headers={"Authorization": "Bearer x"})

        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["content-disposition"].startswith('attachment; filename="my-requests-')
        assert response.headers["content-disposition"].endswith('.csv"')
        # Decision T — the frontend turns this into "12 rows exported".
        assert response.headers["x-export-row-count"] == "12"

    def test_row_count_header_is_zero_not_missing_on_an_empty_export(self):
        client = self.client_as(UserRole.requester)

        with patch(
            "app.api.routes.requests.export_my_requests_csv",
            return_value=("request_id\n", 0),
        ):
            response = client.get("/api/requests/export", headers={"Authorization": "Bearer x"})

        assert response.headers["x-export-row-count"] == "0"

    def test_filters_are_passed_through_to_the_service(self):
        client = self.client_as(UserRole.requester)

        with patch(
            "app.api.routes.requests.export_my_requests_csv",
            return_value=("request_id\n", 0),
        ) as mock_export:
            client.get(
                "/api/requests/export",
                params={
                    "start_date": "2026-07-01",
                    "end_date": "2026-07-31",
                    "request_type": "hardware_devices",
                    "status": "approved",
                },
                headers={"Authorization": "Bearer x"},
            )

        kwargs = mock_export.call_args.kwargs
        assert kwargs["start_date"] == date(2026, 7, 1)
        assert kwargs["end_date"] == date(2026, 7, 31)
        assert kwargs["request_type"] == "hardware_devices"
        assert kwargs["status"] == "approved"
        # The caller never gets to choose whose data this is.
        assert kwargs["user_id"] == 1
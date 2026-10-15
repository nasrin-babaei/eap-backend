# tests/unit/test_report_service.py
# US-010 (IT35-63) — Report service unit tests

import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from app.services.report_service import generate_report, validate_date_range
from app.models.request import Request, RequestStatus


def make_mock_request(status=RequestStatus.pending, request_type_slug="hardware_devices"):
    req = MagicMock(spec=Request)
    req.status = status
    req.created_at = datetime(2026, 7, 1, 10, 0, 0)
    req.request_number = "HD-001"
    req.title = "Test"
    req.decision_date = None
    req.user = MagicMock()
    req.user.name = "Test Requester"
    req.approver = None
    rt = MagicMock()
    # US-017 (M4): the report reads the slug off the row instead of mapping
    # the prefix through the deleted REQUEST_TYPE_TO_PREFIX dict.
    rt.slug = request_type_slug
    req.request_type = rt
    return req


def setup_db_mock(requests):
    """Build a db mock that returns the given list for all .count() and .all() calls."""
    db = MagicMock()

    def count_side_effect():
        return len(requests)

    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.count.side_effect = count_side_effect
    query_mock.all.return_value = requests
    query_mock.order_by.return_value = query_mock
    db.query.return_value = query_mock

    return db


class TestValidateDateRange:

    def test_valid_range_passes(self):
        """Valid range should not raise."""
        validate_date_range(date(2026, 7, 1), date(2026, 7, 31))

    def test_same_date_passes(self):
        """Same start and end date is valid."""
        validate_date_range(date(2026, 7, 15), date(2026, 7, 15))

    def test_invalid_range_raises(self):
        """start_date after end_date should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_date_range(date(2026, 7, 31), date(2026, 7, 1))
        assert "start_date cannot be after end_date" in str(exc_info.value)

    def test_missing_start_date_passes(self):
        """None start_date should not raise."""
        validate_date_range(None, date(2026, 7, 31))

    def test_missing_end_date_passes(self):
        """None end_date should not raise."""
        validate_date_range(date(2026, 7, 1), None)

    def test_both_none_passes(self):
        """Both None should not raise."""
        validate_date_range(None, None)


class TestApprovalRejectionRates:

    def test_approval_rate_formula(self):
        """approval_rate = (approved + completed) / decided * 100"""
        db = setup_db_mock([])
        query_mock = db.query.return_value

        counts = {
            RequestStatus.pending:   5,
            RequestStatus.approved:  51,
            RequestStatus.rejected:  22,
            RequestStatus.completed: 28,
            RequestStatus.cancelled: 5,
        }

        def count_by_status():
            # Return total on first call, then per-status
            return sum(counts.values())

        call_count = [0]
        status_sequence = [
            sum(counts.values()),  # total
            counts[RequestStatus.pending],
            counts[RequestStatus.approved],
            counts[RequestStatus.rejected],
            counts[RequestStatus.completed],
            counts[RequestStatus.cancelled],
        ]

        def count_side():
            val = status_sequence[call_count[0]]
            call_count[0] += 1
            return val

        query_mock.count.side_effect = count_side

        result = generate_report(db)

        decided = 51 + 22 + 28  # approved + rejected + completed
        expected_approval  = round((51 + 28) / decided * 100, 2)
        expected_rejection = round(22 / decided * 100, 2)

        assert result["approval_rate"]  == expected_approval
        assert result["rejection_rate"] == expected_rejection

    def test_approval_rate_zero_when_no_decided_requests(self):
        """Both rates should be 0.0 when no decided requests exist."""
        db = setup_db_mock([])
        query_mock = db.query.return_value

        # All counts return 0
        query_mock.count.return_value = 0

        result = generate_report(db)

        assert result["approval_rate"]  == 0.0
        assert result["rejection_rate"] == 0.0

    def test_approval_and_rejection_rates_sum_to_100(self):
        """approval_rate + rejection_rate should equal 100 when decided > 0."""
        db = setup_db_mock([])
        query_mock = db.query.return_value

        counts = [111, 10, 70, 30, 0, 1]  # total, pending, approved, rejected, completed, cancelled
        call_count = [0]

        def count_side():
            val = counts[call_count[0]]
            call_count[0] += 1
            return val

        query_mock.count.side_effect = count_side

        result = generate_report(db)

        total = result["approval_rate"] + result["rejection_rate"]
        assert abs(total - 100.0) < 0.01


class TestStatusCounters:

    def test_each_status_counted_correctly(self):
        """Each status counter should be independently computed."""
        db = setup_db_mock([])
        query_mock = db.query.return_value

        expected = {
            "total":     50,
            "pending":   10,
            "approved":  15,
            "rejected":   5,
            "completed": 18,
            "cancelled":  2,
        }
        counts = list(expected.values())
        call_count = [0]

        def count_side():
            val = counts[call_count[0]]
            call_count[0] += 1
            return val

        query_mock.count.side_effect = count_side

        result = generate_report(db)

        assert result["totals"]["total_requests"] == expected["total"]
        assert result["totals"]["pending"]        == expected["pending"]
        assert result["totals"]["approved"]       == expected["approved"]
        assert result["totals"]["rejected"]       == expected["rejected"]
        assert result["totals"]["completed"]      == expected["completed"]
        assert result["totals"]["cancelled"]      == expected["cancelled"]

    def test_empty_database_returns_all_zeros(self):
        """All counters should be 0 when no requests exist."""
        db = setup_db_mock([])
        db.query.return_value.filter.return_value.count.return_value = 0
        db.query.return_value.count.return_value = 0

        result = generate_report(db)

        assert result["totals"]["total_requests"] == 0
        assert result["approval_rate"]  == 0.0
        assert result["rejection_rate"] == 0.0


class TestFilters:

    def test_invalid_date_range_raises(self):
        """generate_report should raise ValueError for invalid date range."""
        db = MagicMock()

        with pytest.raises(ValueError):
            generate_report(
                db,
                start_date=date(2026, 7, 31),
                end_date=date(2026, 7, 1)
            )

    def test_no_filters_runs_without_error(self):
        """generate_report with no filters should not raise."""
        db = setup_db_mock([])
        db.query.return_value.count.return_value = 0

        result = generate_report(db)

        assert result["filters"]["start_date"]    is None
        assert result["filters"]["end_date"]      is None
        assert result["filters"]["request_type"]  is None
        assert result["filters"]["status"]        is None

    def test_filters_echoed_in_response(self):
        """Applied filters should be echoed back in the response."""
        db = setup_db_mock([])
        db.query.return_value.count.return_value = 0
        db.query.return_value.filter.return_value = db.query.return_value

        result = generate_report(
            db,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            request_type="hardware_devices",
            status="pending"
        )

        assert result["filters"]["start_date"]   == date(2026, 7, 1)
        assert result["filters"]["end_date"]     == date(2026, 7, 31)
        assert result["filters"]["request_type"] == "hardware_devices"
        assert result["filters"]["status"]       == "pending"

    def test_generated_at_is_datetime(self):
        """generated_at should be a datetime instance."""
        db = setup_db_mock([])
        db.query.return_value.count.return_value = 0

        result = generate_report(db)

        assert isinstance(result["generated_at"], datetime)
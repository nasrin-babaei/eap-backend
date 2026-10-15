# tests/unit/test_approver_service.py

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from app.services.approver_service import (
    get_approval_queue,
    approve_request,
    reject_request,
    get_approver_request_details,
)
from app.models.request import Request, RequestStatus
from app.models.user import User
from app.models.audit_log import AuditLog


def make_mock_request(id, status=RequestStatus.pending, approver_id=99, user_id=1):
    req = MagicMock(spec=Request)
    req.id = id
    req.request_number = f"HD-00{id}"
    req.status = status
    req.approver_id = approver_id
    # user_id is the requester who submitted the request. It must differ from
    # approver_id, otherwise the US-019 self-approval check rejects the request.
    req.user_id = user_id
    req.request_type_id = 1
    req.created_at = "2026-06-14T10:00:00"
    req.updated_at = "2026-06-14T10:00:00"
    req.decision_date = None
    req.rejection_reason = None
    mock_user = MagicMock(spec=User)
    mock_user.name = "Test Requester"
    req.user = mock_user
    req.request_type = None
    return req


class TestGetApprovalQueue:
    def _setup_mock(self, db, items):
        main_mock = MagicMock()
        main_mock.options.return_value = main_mock
        main_mock.filter.return_value = main_mock
        main_mock.order_by.return_value = main_mock
        main_mock.count.return_value = len(items)
        main_mock.offset.return_value = main_mock
        main_mock.limit.return_value = main_mock
        main_mock.all.return_value = items

        counts_mock = MagicMock()
        counts_mock.filter.return_value = counts_mock
        counts_mock.group_by.return_value = counts_mock
        counts_mock.all.return_value = []  # empty status counts

        def query_side_effect(*args):
            # GROUP BY query passes multiple args (Request.status, func.count(...))
            if len(args) > 1:
                return counts_mock
            return main_mock

        db.query.side_effect = query_side_effect
        return main_mock
    def test_returns_pending_requests(self):
        """Should return pending requests for the given approver"""
        db = MagicMock()
        mock_requests = [make_mock_request(1), make_mock_request(2)]
        self._setup_mock(db, mock_requests)

        result = get_approval_queue(db=db, approver_id=99)

        assert len(result["items"]) == 2
        assert result["empty_message"] is None

    def test_returns_empty_list_when_no_pending(self):
        """Should return empty list with message when no pending requests"""
        db = MagicMock()
        self._setup_mock(db, [])

        result = get_approval_queue(db=db, approver_id=99)

        assert result["items"] == []
        assert result["empty_message"] == "No pending requests found."

    def test_requester_name_included(self):
        """Should include requester name from user relationship"""
        db = MagicMock()
        mock_request = make_mock_request(1)
        mock_request.user.name = "John Doe"
        self._setup_mock(db, [mock_request])

        result = get_approval_queue(db=db, approver_id=99)

        assert result["items"][0].requester_name == "John Doe"

    def test_unknown_requester_when_user_is_none(self):
        """Should handle missing user gracefully"""
        db = MagicMock()
        mock_request = make_mock_request(1)
        mock_request.user = None
        self._setup_mock(db, [mock_request])

        result = get_approval_queue(db=db, approver_id=99)

        assert result["items"][0].requester_name == "Unknown"
class TestSelfApprovalPrevention:
    """US-019 â€” an approver may not approve or reject a request they submitted."""

    def test_approve_own_request_is_forbidden(self):
        db = MagicMock()
        # Same person is both the requester and the assigned approver.
        mock_request = make_mock_request(1, approver_id=99, user_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            approve_request(db=db, request_number="HD-001", approver_id=99)

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "You cannot approve or reject your own request."
        # The request must be left untouched â€” no status change, nothing saved.
        assert mock_request.status == RequestStatus.pending
        db.commit.assert_not_called()

    def test_reject_own_request_is_forbidden(self):
        db = MagicMock()
        mock_request = make_mock_request(1, approver_id=99, user_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            reject_request(db=db, request_number="HD-001", approver_id=99, reason="No.")

        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "You cannot approve or reject your own request."
        assert mock_request.status == RequestStatus.pending
        db.commit.assert_not_called()

    def test_self_approval_check_wins_over_assignment_check(self):
        """Own request assigned to someone else still gives the self-approval message."""
        db = MagicMock()
        mock_request = make_mock_request(1, approver_id=42, user_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            approve_request(db=db, request_number="HD-001", approver_id=99)

        assert exc_info.value.detail == "You cannot approve or reject your own request."

    def test_approving_someone_elses_request_still_works(self):
        """Guard against over-blocking: a normal approval must not be affected."""
        db = MagicMock()
        mock_request = make_mock_request(1, approver_id=99, user_id=1)

        def query_side_effect(model):
            m = MagicMock()
            m.filter.return_value.first.return_value = mock_request
            m.options.return_value = m
            m.order_by.return_value = m
            m.all.return_value = []
            return m

        db.query.side_effect = query_side_effect

        result = approve_request(db=db, request_number="HD-001", approver_id=99)

        assert result["status"] == "approved"
        assert mock_request.status == RequestStatus.approved


class TestApproveRequest:

    def test_approve_success(self):
        """Approving a pending request assigned to this approver should succeed"""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.pending, approver_id=99)

        db.query.return_value.filter.return_value.first.return_value = mock_request

        # mock the queue refresh call inside approve_request
        queue_query_mock = MagicMock()
        queue_query_mock.options.return_value = queue_query_mock
        queue_query_mock.filter.return_value = queue_query_mock
        queue_query_mock.order_by.return_value = queue_query_mock
        queue_query_mock.all.return_value = []

        def query_side_effect(model):
            if model is Request:
                # first call (lookup) returns the filter chain with .first()
                # second call (queue refresh) returns the queue chain with .all()
                m = MagicMock()
                m.filter.return_value.first.return_value = mock_request
                m.options.return_value = m
                m.order_by.return_value = m
                m.all.return_value = []
                return m
            return MagicMock()

        db.query.side_effect = query_side_effect

        result = approve_request(db=db, request_number="HD-001", approver_id=99)

        assert mock_request.status == RequestStatus.approved
        assert mock_request.decision_date is not None
        assert mock_request.approval_comment is None
        assert result["status"] == "approved"

        # US-014 added a second db.add() for the notification, so pick the audit
        # row out of the calls rather than assuming it is the only one.
        audit_logs = [
            c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], AuditLog)
        ]
        assert len(audit_logs) == 1
        audit_log = audit_logs[0]

        assert audit_log.user_id == 99
        assert audit_log.action == "REQUEST_APPROVED"
        assert audit_log.resource_type == "request"
        assert audit_log.resource_id == mock_request.id
        assert audit_log.old_status == "pending"
        assert audit_log.new_status == "approved"
        assert result["request_id"] == "HD-001"
        assert "queue" in result

    def test_approve_with_comment_success(self):
        """Approving with a comment should store it on approval_comment"""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.pending, approver_id=99)

        db.query.return_value.filter.return_value.first.return_value = mock_request

        def query_side_effect(model):
            if model is Request:
                m = MagicMock()
                m.filter.return_value.first.return_value = mock_request
                m.options.return_value = m
                m.order_by.return_value = m
                m.all.return_value = []
                return m
            return MagicMock()

        db.query.side_effect = query_side_effect

        result = approve_request(
            db=db, request_number="HD-001", approver_id=99, comment="Test approval comment"
        )

        assert mock_request.approval_comment == "Test approval comment"
        assert result["status"] == "approved"

        

    def test_approve_not_found(self):
        """Approving a non-existent request should raise 404"""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            approve_request(db=db, request_number="HD-999", approver_id=99)

        assert exc_info.value.status_code == 404

    def test_approve_wrong_approver(self):
        """Approving a request not assigned to this approver should raise 403"""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.pending, approver_id=5)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            approve_request(db=db, request_number="HD-001", approver_id=99)

        assert exc_info.value.status_code == 403

    def test_approve_invalid_status_transition(self):
        """Approving an already-approved request should raise 400"""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.approved, approver_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            approve_request(db=db, request_number="HD-001", approver_id=99)

        assert exc_info.value.status_code == 400


class TestRejectRequest:

    def test_reject_success(self):
        """Rejecting a pending request assigned to this approver should succeed"""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.pending, approver_id=99)

        def query_side_effect(model):
            m = MagicMock()
            m.filter.return_value.first.return_value = mock_request
            m.options.return_value = m
            m.order_by.return_value = m
            m.all.return_value = []
            return m

        db.query.side_effect = query_side_effect

        result = reject_request(
            db=db, request_number="HD-001", approver_id=99, reason="Not justified"
        )

        assert mock_request.status == RequestStatus.rejected
        assert mock_request.rejection_reason == "Not justified"
        assert mock_request.decision_date is not None
        assert result["status"] == "rejected"

        audit_logs = [
            c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], AuditLog)
        ]
        assert len(audit_logs) == 1
        audit_log = audit_logs[0]

        assert audit_log.user_id == 99
        assert audit_log.action == "REQUEST_REJECTED"
        assert audit_log.resource_type == "request"
        assert audit_log.resource_id == mock_request.id
        assert audit_log.old_status == "pending"
        assert audit_log.new_status == "rejected"

    def test_reject_not_found(self):
        """Rejecting a non-existent request should raise 404"""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            reject_request(db=db, request_number="HD-999", approver_id=99, reason="x")

        assert exc_info.value.status_code == 404

    def test_reject_wrong_approver(self):
        """Rejecting a request not assigned to this approver should raise 403"""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.pending, approver_id=5)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            reject_request(db=db, request_number="HD-001", approver_id=99, reason="x")

        assert exc_info.value.status_code == 403

    def test_reject_invalid_status_transition(self):
        """Rejecting an already-rejected request should raise 400"""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.rejected, approver_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            reject_request(db=db, request_number="HD-001", approver_id=99, reason="x")

        assert exc_info.value.status_code == 400


class TestGetApproverRequestDetails:

    def test_returns_details_for_assigned_request(self):
        """Should return request details when assigned to this approver"""
        db = MagicMock()
        mock_request = make_mock_request(1, approver_id=99)

        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = mock_request

        result = get_approver_request_details(db=db, request_id="HD-001", approver_id=99)

        assert result.requester_name == "Test Requester"

    def test_returns_none_when_not_found(self):
        """Should return None when request_id does not exist"""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = None

        result = get_approver_request_details(db=db, request_id="HD-999", approver_id=99)

        assert result is None

    def test_raises_permission_error_for_wrong_approver(self):
        """Should raise PermissionError when request is not assigned to this approver"""
        db = MagicMock()
        mock_request = make_mock_request(1, approver_id=5)

        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = mock_request

        with pytest.raises(PermissionError):
            get_approver_request_details(db=db, request_id="HD-001", approver_id=99)


from sqlalchemy.exc import SQLAlchemyError


class TestApproveRequestDbFailure:

    def test_approve_wraps_db_error_as_runtime_error(self):
        """Regression for IT35-222/IT35-233: a DB failure during approve
        must raise RuntimeError (not leak the raw SQLAlchemyError), and
        must roll back before re-raising. This is the exact site of
        IT35-233 â€” the exception handler must actually execute
        logger.error() and raise RuntimeError(...) from e."""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.pending, approver_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        with pytest.raises(RuntimeError):
            approve_request(db=db, request_number="HD-001", approver_id=99)

        db.rollback.assert_called_once()

    def test_approve_db_error_does_not_leak_sqlalchemy_exception(self):
        """The raw SQLAlchemyError must never reach the route layer â€”
        only RuntimeError should surface."""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.pending, approver_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        try:
            approve_request(db=db, request_number="HD-001", approver_id=99)
            assert False, "expected RuntimeError to be raised"
        except SQLAlchemyError:
            assert False, "raw SQLAlchemyError leaked â€” IT35-233 regression"
        except RuntimeError:
            pass


class TestRejectRequestDbFailure:

    def test_reject_wraps_db_error_as_runtime_error(self):
        """Same regression as approve, for the reject path."""
        db = MagicMock()
        mock_request = make_mock_request(1, status=RequestStatus.pending, approver_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        with pytest.raises(RuntimeError):
            reject_request(db=db, request_number="HD-001", approver_id=99, reason="x")

        db.rollback.assert_called_once()


class TestApprovalQueueSortOrder:

    def test_queue_is_sorted_ascending_by_created_at(self):
        """Regression: GET /approver/requests must sort oldest-first
        (ascending), per IT35-135 â€” now documented in the OpenAPI contract."""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = []

        get_approval_queue(db=db, approver_id=99)

        args, kwargs = query_mock.order_by.call_args
        assert str(args[0]) == str(Request.created_at.asc())

class TestGetStatusCounts:

    def test_returns_counts_for_all_five_statuses(self):
        """status_counts should include all 5 statuses."""
        db = MagicMock()
        from app.models.request import RequestStatus
        db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
            (RequestStatus.pending, 3),
            (RequestStatus.approved, 12),
            (RequestStatus.rejected, 2),
            (RequestStatus.completed, 8),
            (RequestStatus.cancelled, 1),
        ]

        from app.services.approver_service import get_status_counts
        result = get_status_counts(db=db, approver_id=99)

        assert result["pending"]   == 3
        assert result["approved"]  == 12
        assert result["rejected"]  == 2
        assert result["completed"] == 8
        assert result["cancelled"] == 1

    def test_missing_statuses_default_to_zero(self):
        """Statuses with no requests should return 0, not KeyError."""
        db = MagicMock()
        from app.models.request import RequestStatus
        db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
            (RequestStatus.pending, 5),
        ]

        from app.services.approver_service import get_status_counts
        result = get_status_counts(db=db, approver_id=99)

        assert result["pending"]   == 5
        assert result["approved"]  == 0
        assert result["rejected"]  == 0
        assert result["completed"] == 0
        assert result["cancelled"] == 0

    def test_independent_of_status_filter(self):
        """status_counts is always all five tabs regardless of selected status."""
        db = MagicMock()
        from app.models.request import RequestStatus
        db.query.return_value.filter.return_value.group_by.return_value.all.return_value = [
            (RequestStatus.pending,   3),
            (RequestStatus.approved, 12),
            (RequestStatus.rejected,  2),
            (RequestStatus.completed, 8),
            (RequestStatus.cancelled, 1),
        ]

        from app.services.approver_service import get_status_counts
        # Called with approver_id only â€” no status/page/limit
        result = get_status_counts(db=db, approver_id=99)

        # All five tabs always present
        assert set(result.keys()) == {"pending", "approved", "rejected", "completed", "cancelled"}


class TestGetApprovalQueuePagination:

    def _setup_queue_mock(self, db, items, total=None):
        main_mock = MagicMock()
        main_mock.options.return_value = main_mock
        main_mock.filter.return_value = main_mock
        main_mock.order_by.return_value = main_mock
        main_mock.count.return_value = total if total is not None else len(items)
        main_mock.offset.return_value = main_mock
        main_mock.limit.return_value = main_mock
        main_mock.all.return_value = items

        counts_mock = MagicMock()
        counts_mock.filter.return_value = counts_mock
        counts_mock.group_by.return_value = counts_mock
        counts_mock.group_by.return_value.all.return_value = []

        # Use side_effect that distinguishes single vs multiple args
        def query_side_effect(*args):
            if len(args) > 1:
                return counts_mock
            return main_mock

        db.query.side_effect = query_side_effect
        return main_mock

    def test_pending_tab_sorted_created_at_asc(self):
        """Pending tab must ORDER BY created_at ASC."""
        db = MagicMock()
        self._setup_queue_mock(db, [])

        from app.services.approver_service import get_approval_queue
        get_approval_queue(db=db, approver_id=99, status="pending")

        from app.models.request import Request
        from sqlalchemy import asc
        # Check order_by was called with created_at ascending
        call_args = db.query.return_value.order_by.call_args or \
                    db.query.side_effect(Request).order_by.call_args
        assert call_args is not None
        expr = call_args[0][0]
        assert str(expr) == str(Request.created_at.asc())

    def test_non_pending_tab_sorted_updated_at_desc(self):
        """Non-pending tabs must ORDER BY updated_at DESC."""
        db = MagicMock()
        self._setup_queue_mock(db, [])

        from app.services.approver_service import get_approval_queue
        get_approval_queue(db=db, approver_id=99, status="approved")

        from app.models.request import Request
        call_args = db.query.return_value.order_by.call_args or \
                    db.query.side_effect(Request).order_by.call_args
        assert call_args is not None
        expr = call_args[0][0]
        assert str(expr) == str(Request.updated_at.desc())

    def test_pagination_page2_applies_correct_offset(self):
        """Page 2 with limit 10 should apply offset=10."""
        db = MagicMock()
        main_mock = self._setup_queue_mock(db, [], total=25)

        from app.services.approver_service import get_approval_queue
        result = get_approval_queue(db=db, approver_id=99, status="pending", page=2, limit=10)

        # Verify offset called with 10 (page-1) * limit = 1*10
        assert main_mock.offset.called
        offset_arg = main_mock.offset.call_args[0][0]
        assert offset_arg == 10
        assert result["page"] == 2
        assert result["limit"] == 10
        assert result["total"] == 25

    def test_empty_pending_tab_returns_correct_message(self):
        """Empty pending tab should return 'No pending requests found.'"""
        db = MagicMock()
        self._setup_queue_mock(db, [], total=0)

        from app.services.approver_service import get_approval_queue
        result = get_approval_queue(db=db, approver_id=99, status="pending")

        assert result["empty_message"] == "No pending requests found."

    def test_empty_approved_tab_returns_correct_message(self):
        """Empty approved tab should return 'No approved requests found.'"""
        db = MagicMock()
        self._setup_queue_mock(db, [], total=0)

        from app.services.approver_service import get_approval_queue
        result = get_approval_queue(db=db, approver_id=99, status="approved")

        assert result["empty_message"] == "No approved requests found."

    def test_non_empty_tab_has_no_empty_message(self):
        """Non-empty tab should return empty_message=None."""
        db = MagicMock()
        mock_req = make_mock_request(1)
        self._setup_queue_mock(db, [mock_req], total=1)

        from app.services.approver_service import get_approval_queue
        result = get_approval_queue(db=db, approver_id=99, status="pending")

        assert result["empty_message"] is None

    def test_limit_capped_at_100(self):
        """limit > 100 should be silently capped to 100."""
        db = MagicMock()
        self._setup_queue_mock(db, [], total=0)

        from app.services.approver_service import get_approval_queue
        result = get_approval_queue(db=db, approver_id=99, status="pending", limit=999)

        assert result["limit"] == 100

        
def test_request_type_name_is_attached_for_approver_detail():
    """IT35-301 â€” approver detail must expose request_type_name, matching RequestDetailsResponse."""
    db = MagicMock()
    req = MagicMock(spec=Request)
    req.request_number = "HD-026"
    req.approver_id = 2
    req.user = MagicMock(name="Jane")
    req.request_type = MagicMock()
    req.request_type.name = "Hardware & Devices"
    db.query.return_value.options.return_value.filter.return_value.first.return_value = req

    result = get_approver_request_details(db, "HD-026", approver_id=2)

    assert result.request_type_name == "Hardware & Devices"

# ============================================================================
# US-012 (IT35-310) - GET /approver/requests/export
# ============================================================================

from datetime import date
from datetime import datetime
from app.services.approver_service import export_my_decisions_csv
from app.models.request_type import RequestType


def make_decided_request(id, status=RequestStatus.approved, approver_id=99,
                          decision_date=None,
                          approval_comment=None, rejection_reason=None,
                          request_type_slug="hardware_devices"):
    req = MagicMock(spec=Request)
    req.id = id
    req.request_number = f"HD-00{id}"
    req.status = status
    req.approver_id = approver_id
    req.decision_date = decision_date if decision_date is not None else datetime(2026, 7, 11, 9, 0, 0)
    req.approval_comment = approval_comment
    req.rejection_reason = rejection_reason
    rt = MagicMock(spec=RequestType)
    rt.slug = request_type_slug
    req.request_type = rt
    req.request_type_id = 1
    return req


class TestExportMyDecisionsCsv:

    def _setup_mock(self, db, items):
        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = items
        return query_mock

    def test_returns_csv_text_and_row_count(self):
        db = MagicMock()
        req = make_decided_request(1, status=RequestStatus.approved,
                                    approval_comment="Approved, go ahead.")
        self._setup_mock(db, [req])

        csv_text, row_count = export_my_decisions_csv(db=db, approver_id=99)

        assert row_count == 1
        assert "request_id,approver_id,decision,decision_date,comment" in csv_text
        assert "HD-001" in csv_text
        assert "approved" in csv_text

    def test_approved_uses_approval_comment(self):
        db = MagicMock()
        req = make_decided_request(1, status=RequestStatus.approved,
                                    approval_comment="Budget approved.")
        self._setup_mock(db, [req])

        csv_text, _ = export_my_decisions_csv(db=db, approver_id=99)

        assert "Budget approved." in csv_text

    def test_rejected_uses_rejection_reason(self):
        db = MagicMock()
        req = make_decided_request(1, status=RequestStatus.rejected,
                                    rejection_reason="Over budget.")
        self._setup_mock(db, [req])

        csv_text, _ = export_my_decisions_csv(db=db, approver_id=99)

        assert "rejected" in csv_text
        assert "Over budget." in csv_text
        assert "Budget approved." not in csv_text

    def test_empty_comment_becomes_empty_cell_not_the_word_none(self):
        db = MagicMock()
        req = make_decided_request(1, status=RequestStatus.approved, approval_comment=None)
        self._setup_mock(db, [req])

        csv_text, _ = export_my_decisions_csv(db=db, approver_id=99)

        assert "None" not in csv_text

    def test_no_results_returns_zero_rows_and_header_only(self):
        db = MagicMock()
        self._setup_mock(db, [])

        csv_text, row_count = export_my_decisions_csv(db=db, approver_id=99)

        assert row_count == 0
        assert "request_id,approver_id,decision,decision_date,comment" in csv_text

    def test_start_date_after_end_date_raises_400(self):
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            export_my_decisions_csv(
                db=db, approver_id=99,
                start_date=date(2026, 7, 31), end_date=date(2026, 7, 1),
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "start_date cannot be after end_date."

    def test_unknown_request_type_slug_returns_empty_result(self):
        """A slug that matches nothing is a valid empty answer, not an error -
        same convention as request_service.py's requester export."""
        db = MagicMock()
        query_mock = self._setup_mock(db, [])
        rt_query_mock = MagicMock()
        rt_query_mock.filter.return_value.first.return_value = None

        def query_side_effect(model):
            if model is RequestType:
                return rt_query_mock
            return query_mock

        db.query.side_effect = query_side_effect

        csv_text, row_count = export_my_decisions_csv(
            db=db, approver_id=99, request_type="nonexistent_slug",
        )

        assert row_count == 0

    def test_writes_data_exported_audit_row(self):
        db = MagicMock()
        req = make_decided_request(1)
        self._setup_mock(db, [req])

        export_my_decisions_csv(db=db, approver_id=99)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1
        assert audit_rows[0].action == "DATA_EXPORTED"
        assert audit_rows[0].user_id == 99
        assert audit_rows[0].resource_type == "request"
        db.commit.assert_called_once()

    def test_invalid_decision_value_raises_422(self):
        """Defensive check at the service layer - the route already
        validates this before calling the service."""
        db = MagicMock()
        self._setup_mock(db, [])

        with pytest.raises(HTTPException) as exc_info:
            export_my_decisions_csv(db=db, approver_id=99, decision="maybe")

        assert exc_info.value.status_code == 422



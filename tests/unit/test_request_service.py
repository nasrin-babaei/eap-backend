# tests/unit/test_request_service.py
# IT35-132 — updated: options() mock, empty_message, request_type_name tests
# IT35-status-list-view — added: all 5 status values, freshness after decision

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from app.services.request_service import get_user_requests, get_request_details, create_request, complete_request, cancel_request
from app.models.request_type import RequestType
from app.models.user import User, UserRole
from app.models.request import Request, RequestStatus
from app.models.audit_log import AuditLog


def make_mock_request(id, status=RequestStatus.pending, type_name="Hardware & Devices"):
    req = MagicMock(spec=Request)
    req.id = id
    req.status = status
    req.user_id = 1
    req.request_type = MagicMock()
    req.request_type.name = type_name
    return req


def make_mock_request_with_details(
    id,
    status=RequestStatus.pending,
    requester_id=1,
    approver_id=2,
    decision_date=None,
    rejection_reason=None,
    approval_comment=None,
    request_type_name="Hardware & Devices"
):
    req = MagicMock(spec=Request)
    req.id = id
    req.request_number = f"HD-00{id}"
    req.status = status
    req.user_id = requester_id
    req.approver_id = approver_id
    req.decision_date = decision_date
    req.rejection_reason = rejection_reason
    req.approval_comment = approval_comment
    req.request_type = MagicMock()
    req.request_type.name = request_type_name
    return req


def setup_query_mock(db, items, count=None):
    """Builds full mock chain including .options() for joinedload."""
    qm = db.query.return_value
    qm.options.return_value = qm   # ← required after adding joinedload
    qm.filter.return_value = qm
    qm.count.return_value = count if count is not None else len(items)
    qm.order_by.return_value = qm
    qm.offset.return_value = qm
    qm.limit.return_value = qm
    qm.all.return_value = items
    return qm


class TestGetUserRequests:

    def test_success_returns_paginated_results(self):
        """Success case — returns correct pagination metadata"""
        db = MagicMock()
        setup_query_mock(db, [make_mock_request(i) for i in range(3)])

        result = get_user_requests(db=db, user_id=1, page=1, limit=10)

        assert result["total"] == 3
        assert result["page"] == 1
        assert result["limit"] == 10
        assert result["pages"] == 1
        assert len(result["items"]) == 3

    def test_empty_state_returns_correct_message(self):
        """Empty state — correct message per US-004 AC"""
        db = MagicMock()
        setup_query_mock(db, [], count=0)

        result = get_user_requests(db=db, user_id=1)

        assert result["total"] == 0
        assert result["items"] == []
        assert result["pages"] == 0
        assert result["empty_message"] == (
            "No requests found. You have not submitted any requests yet."
        )

    def test_non_empty_has_no_empty_message(self):
        """When requests exist, empty_message must be None"""
        db = MagicMock()
        setup_query_mock(db, [make_mock_request(1)])

        result = get_user_requests(db=db, user_id=1)

        assert result["empty_message"] is None

    def test_request_type_name_is_attached(self):
        """US-017 (M4): the slug is read straight off the eager-loaded
        request_type relationship (IT35-331: no longer a per-row query)."""
        db = MagicMock()
        req = make_mock_request(1, type_name="Software & Access")
        req.request_type.slug = "software_access"
        setup_query_mock(db, [req])

        result = get_user_requests(db=db, user_id=1)

        assert result["items"][0]["request_type"] == "software_access"

    def test_deactivated_type_still_shows_on_existing_requests(self):
        """AC8 — deactivating a type must never change requests that already
        use it. The list reads the row, and the row is untouched."""
        db = MagicMock()
        req = make_mock_request(1)
        req.request_type.slug = "training_courses"
        req.request_type.is_active = False
        setup_query_mock(db, [req])

        result = get_user_requests(db=db, user_id=1)

        assert result["items"][0]["request_type"] == "training_courses"

    def test_request_type_name_none_when_no_relationship(self):
        """Graceful handling when request_type relationship is None - fallback to 'other'"""
        db = MagicMock()
        req = make_mock_request(1)
        req.request_type = None
        setup_query_mock(db, [req])

        # Mock the RequestType query to return None
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_user_requests(db=db, user_id=1)

        assert result["items"][0]["request_type"] == "other"

    def test_pagination_page_calculation(self):
        """25 items with limit 10 should give 3 pages"""
        db = MagicMock()
        setup_query_mock(db, [], count=25)

        result = get_user_requests(db=db, user_id=1, limit=10)

        assert result["pages"] == 3

    def test_status_filter_valid(self):
        """Valid status filter should work without error"""
        db = MagicMock()
        setup_query_mock(db, [make_mock_request(1, RequestStatus.approved)], count=1)

        result = get_user_requests(db=db, user_id=1, status="approved")

        assert result["total"] == 1

    def test_status_filter_invalid_raises(self):
        """Invalid status string must raise ValueError"""
        db = MagicMock()
        setup_query_mock(db, [], count=0)

        with pytest.raises(ValueError) as exc_info:
            get_user_requests(db=db, user_id=1, status="nonexistent")

        assert "Invalid status" in str(exc_info.value)

    def test_limit_capped_at_100(self):
        """limit > 100 is silently capped"""
        db = MagicMock()
        setup_query_mock(db, [], count=0)

        result = get_user_requests(db=db, user_id=1, limit=999)

        assert result["limit"] == 100


class TestGetRequestDetails:

    def test_returns_decision_metadata_for_approved_request(self):
        """Approved request: decision_date present, approver_comments = None"""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1,
            status=RequestStatus.approved,
            decision_date="2024-07-26T10:00:00",
            rejection_reason=None
        )

        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = mock_request

        result = get_request_details(db, user_id=1, request_id="HD-001")

        assert result.decision_date == "2024-07-26T10:00:00"
        assert result.comments_display is None

    def test_returns_decision_metadata_for_rejected_request(self):
        """Rejected request: decision_date and rejection_reason returned as approver_comments"""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1,
            status=RequestStatus.rejected,
            decision_date="2024-07-26T11:00:00",
            rejection_reason="Budget not available."
        )

        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = mock_request

        result = get_request_details(db, user_id=1, request_id="HD-001")

        assert result.decision_date == "2024-07-26T11:00:00"
        assert result.comments_display == "Budget not available."

    def test_decision_metadata_is_null_for_pending_request(self):
        """Pending request: decision_date and approver_comments are None"""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1,
            status=RequestStatus.pending,
            decision_date=None,
            rejection_reason=None
        )

        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = mock_request

        result = get_request_details(db, user_id=1, request_id="HD-001")

        assert result.decision_date is None
        assert result.comments_display is None

    def test_returns_none_if_request_not_found(self):
        """Request not found -> return None"""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = None

        result = get_request_details(db, user_id=1, request_id="HD-999")

        assert result is None

    def test_raises_permission_error_if_not_owner(self):
        """User tries to access another user's request -> PermissionError"""
        db = MagicMock()
        mock_request = make_mock_request_with_details(1, requester_id=2)
        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = mock_request

        with pytest.raises(PermissionError) as exc_info:
            get_request_details(db, user_id=1, request_id="HD-001")

        assert "unauthorized" in str(exc_info.value).lower()


class TestAllStatusValues:
    """US-007/IT35-status-list-view — verify all 5 status values work correctly."""

    @pytest.mark.parametrize("status_enum,status_str", [
        (RequestStatus.pending, "pending"),
        (RequestStatus.approved, "approved"),
        (RequestStatus.rejected, "rejected"),
        (RequestStatus.completed, "completed"),
        (RequestStatus.cancelled, "cancelled"),
    ])
    def test_each_status_value_returned_correctly(self, status_enum, status_str):
        """Each of the 5 status values should serialize correctly in list items."""
        db = MagicMock()
        req = make_mock_request(1, status=status_enum)
        setup_query_mock(db, [req])

        db.query.return_value.filter.return_value.first.return_value = None

        result = get_user_requests(db=db, user_id=1)

        assert result["items"][0]["status"] == status_str

    @pytest.mark.parametrize("status_str", [
        "pending", "approved", "rejected", "completed", "cancelled",
    ])
    def test_each_status_value_accepted_as_filter(self, status_str):
        """Each of the 5 status values should be accepted as a valid filter without error."""
        db = MagicMock()
        setup_query_mock(db, [], count=0)

        result = get_user_requests(db=db, user_id=1, status=status_str)

        assert result["total"] == 0  # no error raised, filter accepted


class TestStatusFreshnessAfterDecision:
    """US-007 — confirm no caching/stale data after an approve/reject decision."""

    def test_list_reflects_approved_status_with_no_caching(self):
        """
        Simulates calling get_user_requests twice: once while pending,
        once after a decision changed the status to approved. Since the
        service always issues a fresh DB query (no in-memory cache),
        the second call must reflect the new status.
        """
        db = MagicMock()

        pending_req = make_mock_request(1, status=RequestStatus.pending)
        setup_query_mock(db, [pending_req])
        db.query.return_value.filter.return_value.first.return_value = None

        first_result = get_user_requests(db=db, user_id=1)
        assert first_result["items"][0]["status"] == "pending"

        # Simulate the approve_request service committing a status change
        approved_req = make_mock_request(1, status=RequestStatus.approved)
        setup_query_mock(db, [approved_req])
        db.query.return_value.filter.return_value.first.return_value = None

        second_result = get_user_requests(db=db, user_id=1)
        assert second_result["items"][0]["status"] == "approved"

    def test_list_reflects_rejected_status_with_no_caching(self):
        """Same freshness check for rejection."""
        db = MagicMock()

        pending_req = make_mock_request(1, status=RequestStatus.pending)
        setup_query_mock(db, [pending_req])
        db.query.return_value.filter.return_value.first.return_value = None

        first_result = get_user_requests(db=db, user_id=1)
        assert first_result["items"][0]["status"] == "pending"

        rejected_req = make_mock_request(1, status=RequestStatus.rejected)
        setup_query_mock(db, [rejected_req])
        db.query.return_value.filter.return_value.first.return_value = None

        second_result = get_user_requests(db=db, user_id=1)
        assert second_result["items"][0]["status"] == "rejected"

class TestCreateRequest:

    def test_create_success(self):
        """Regression for IT35-175: creating a request with a valid
        payload must succeed and return all expected fields, not 500."""
        db = MagicMock()
        mock_request_type = MagicMock(spec=RequestType)
        mock_request_type.id = 1
        mock_request_type.slug = "hardware_devices"
        mock_request_type.prefix = "HD"
        mock_request_type.counter = 0
        mock_request_type.is_active = True

        mock_approver = MagicMock(spec=User)
        mock_approver.id = 5
        mock_approver.role = UserRole.approver
        mock_approver.is_active = True

        def query_side_effect(model):
            m = MagicMock()
            if model is RequestType:
                m.filter.return_value.with_for_update.return_value.first.return_value = mock_request_type
            elif model is User:
                m.filter.return_value.order_by.return_value.all.return_value = [mock_approver]
            elif model is Request:
                m.count.return_value = 0
            return m

        db.query.side_effect = query_side_effect

        data = MagicMock()
        data.request_type = "hardware_devices"
        data.title = "Need a new laptop"
        data.justification = "Current one is too slow"

        result = create_request(db=db, user_id=1, data=data)

        assert result["request_number"] == "HD-001"
        assert result["status"] == "pending"
        assert result["approver_id"] == 5
        assert result["message"] == "Request submitted successfully."
        # Two rows now: the request itself plus its REQUEST_CREATED audit row
        # (IT35-306). They share one commit so neither can exist alone.
        assert db.add.call_count == 2
        db.commit.assert_called_once()

    def test_create_writes_request_created_audit_row(self):
        """IT35-306 / US-011 AC1: request creation must land in audit_log.
        Before this it was only a logger.info line, so the Audit Logs page
        could never show it (see M6 in openapi-sprint6.yaml)."""
        db = MagicMock()
        mock_request_type = MagicMock(spec=RequestType)
        mock_request_type.id = 1
        mock_request_type.slug = "hardware_devices"
        mock_request_type.prefix = "HD"
        mock_request_type.counter = 0
        mock_request_type.is_active = True

        mock_approver = MagicMock(spec=User)
        mock_approver.id = 5
        mock_approver.role = UserRole.approver
        mock_approver.is_active = True

        def query_side_effect(model):
            m = MagicMock()
            if model is RequestType:
                m.filter.return_value.with_for_update.return_value.first.return_value = mock_request_type
            elif model is User:
                m.filter.return_value.order_by.return_value.all.return_value = [mock_approver]
            elif model is Request:
                m.count.return_value = 0
            return m

        db.query.side_effect = query_side_effect

        data = MagicMock()
        data.request_type = "hardware_devices"
        data.title = "Need a new laptop"
        data.justification = "Current one is too slow"

        create_request(db=db, user_id=1, data=data)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1

        audit = audit_rows[0]
        assert audit.action == "REQUEST_CREATED"
        assert audit.user_id == 1
        assert audit.resource_type == "request"
        assert audit.new_status == "pending"
        # A brand new request has no previous status to record.
        assert audit.old_status is None

    def test_create_unknown_request_type_raises_lookup_error(self):
        """US-017 (decision M): a slug that is not in request_types at all is
        bad input — LookupError, which the route turns into 422."""
        db = MagicMock()
        db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None

        data = MagicMock()
        data.request_type = "not_a_real_type"
        data.title = "x"
        data.justification = "y"

        with pytest.raises(LookupError):
            create_request(db=db, user_id=1, data=data)

        db.commit.assert_not_called()

    def test_create_deactivated_request_type_raises_value_error(self):
        """US-017 (decision M): the type exists but an admin switched it off.
        A stale browser tab can still post it, so the API has to say no —
        ValueError, which the route turns into 400."""
        db = MagicMock()
        deactivated = MagicMock(spec=RequestType)
        deactivated.id = 8
        deactivated.slug = "training_courses"
        deactivated.prefix = "TC"
        deactivated.counter = 0
        deactivated.is_active = False
        db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = deactivated

        data = MagicMock()
        data.request_type = "training_courses"
        data.title = "x"
        data.justification = "y"

        with pytest.raises(ValueError) as exc_info:
            create_request(db=db, user_id=1, data=data)

        assert str(exc_info.value) == "This request type is no longer available."
        db.commit.assert_not_called()

    def test_create_accepts_a_type_that_is_not_one_of_the_original_seven(self):
        """The point of US-017: a type an admin just created works with no
        code change, because the lookup is a database query now."""
        db = MagicMock()
        new_type = MagicMock(spec=RequestType)
        new_type.id = 8
        new_type.slug = "training_courses"
        new_type.prefix = "TC"
        new_type.counter = 0
        new_type.is_active = True

        def query_side_effect(model):
            m = MagicMock()
            if model is RequestType:
                m.filter.return_value.with_for_update.return_value.first.return_value = new_type
            elif model is User:
                m.filter.return_value.order_by.return_value.all.return_value = []
            elif model is Request:
                m.count.return_value = 0
            return m

        db.query.side_effect = query_side_effect

        data = MagicMock()
        data.request_type = "training_courses"
        data.title = "x"
        data.justification = "y"

        result = create_request(db=db, user_id=1, data=data)

        assert result["request_number"] == "TC-001"
        assert result["request_type"] == "training_courses"

    def test_create_no_approvers_available_sets_approver_id_none(self):
        """Should succeed with approver_id=None when no active approvers exist."""
        db = MagicMock()
        mock_request_type = MagicMock(spec=RequestType)
        mock_request_type.id = 1
        mock_request_type.slug = "hardware_devices"
        mock_request_type.prefix = "HD"
        mock_request_type.counter = 0
        mock_request_type.is_active = True

        def query_side_effect(model):
            m = MagicMock()
            if model is RequestType:
                m.filter.return_value.with_for_update.return_value.first.return_value = mock_request_type
            elif model is User:
                m.filter.return_value.order_by.return_value.all.return_value = []
            elif model is Request:
                m.count.return_value = 0
            return m

        db.query.side_effect = query_side_effect

        data = MagicMock()
        data.request_type = "hardware_devices"
        data.title = "x"
        data.justification = "y"

        result = create_request(db=db, user_id=1, data=data)

        assert result["approver_id"] is None

    def test_create_db_error_wraps_as_runtime_error(self):
        """Regression for IT35-175: a DB failure during creation must
        raise RuntimeError, not leak the raw SQLAlchemyError, and must
        roll back."""
        from sqlalchemy.exc import SQLAlchemyError

        db = MagicMock()
        mock_request_type = MagicMock(spec=RequestType)
        mock_request_type.id = 1
        mock_request_type.slug = "hardware_devices"
        mock_request_type.prefix = "HD"
        mock_request_type.counter = 0
        mock_request_type.is_active = True

        def query_side_effect(model):
            m = MagicMock()
            if model is RequestType:
                m.filter.return_value.with_for_update.return_value.first.return_value = mock_request_type
            elif model is User:
                m.filter.return_value.order_by.return_value.all.return_value = []
            elif model is Request:
                m.count.return_value = 0
            return m

        db.query.side_effect = query_side_effect
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        data = MagicMock()
        data.request_type = "hardware_devices"
        data.title = "x"
        data.justification = "y"

        with pytest.raises(RuntimeError):
            create_request(db=db, user_id=1, data=data)

        db.rollback.assert_called()


class TestGetRequestDetailsNames:

    def test_requester_and_approver_name_populated(self):
        """Regression for IT35-234: requester_name and approver_name
        must be populated from the relationships, not null."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(1, requester_id=1)
        mock_request.user = MagicMock()
        mock_request.user.name = "Test Requester"
        mock_request.approver = MagicMock()
        mock_request.approver.name = "Test Approver"

        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = mock_request

        result = get_request_details(db, user_id=1, request_id="HD-001")

        assert result.requester_name == "Test Requester"
        assert result.approver_name == "Test Approver"

    def test_approver_name_none_when_not_yet_assigned(self):
        """approver_name should be None (not crash) when no approver
        relationship exists yet."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(1, requester_id=1)
        mock_request.user = MagicMock()
        mock_request.user.name = "Test Requester"
        mock_request.approver = None

        query_mock = db.query.return_value
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.first.return_value = mock_request

        result = get_request_details(db, user_id=1, request_id="HD-001")

        assert result.approver_name is None


class TestAssignApproverSkipsRequester:
    """IT35-261 - round-robin assignment must never assign a request to its own requester."""

    def test_requester_is_next_in_rotation_skips_to_following_approver(self):
        """If the requester is next up in rotation, the following approver gets it instead."""
        db = MagicMock()
        mock_request_type = MagicMock(spec=RequestType)
        mock_request_type.id = 1
        mock_request_type.slug = "hardware_devices"
        mock_request_type.prefix = "HD"
        mock_request_type.counter = 0
        mock_request_type.is_active = True

        requester = MagicMock(spec=User)
        requester.id = 5
        requester.role = UserRole.approver
        requester.is_active = True

        other_approver = MagicMock(spec=User)
        other_approver.id = 7
        other_approver.role = UserRole.approver
        other_approver.is_active = True

        def query_side_effect(model):
            m = MagicMock()
            if model is RequestType:
                m.filter.return_value.with_for_update.return_value.first.return_value = mock_request_type
            elif model is User:
                m.filter.return_value.order_by.return_value.all.return_value = [requester, other_approver]
            elif model is Request:
                m.count.return_value = 0
            return m

        db.query.side_effect = query_side_effect

        data = MagicMock()
        data.request_type = "hardware_devices"
        data.title = "x"
        data.justification = "y"

        result = create_request(db=db, user_id=5, data=data)

        assert result["approver_id"] == 7

    def test_requester_is_only_active_approver_results_in_no_assignment(self):
        """If the requester is the only active approver, no assignment can be made."""
        db = MagicMock()
        mock_request_type = MagicMock(spec=RequestType)
        mock_request_type.id = 1
        mock_request_type.slug = "hardware_devices"
        mock_request_type.prefix = "HD"
        mock_request_type.counter = 0
        mock_request_type.is_active = True

        requester = MagicMock(spec=User)
        requester.id = 5
        requester.role = UserRole.approver
        requester.is_active = True

        def query_side_effect(model):
            m = MagicMock()
            if model is RequestType:
                m.filter.return_value.with_for_update.return_value.first.return_value = mock_request_type
            elif model is User:
                m.filter.return_value.order_by.return_value.all.return_value = [requester]
            elif model is Request:
                m.count.return_value = 0
            return m

        db.query.side_effect = query_side_effect

        data = MagicMock()
        data.request_type = "hardware_devices"
        data.title = "x"
        data.justification = "y"

        result = create_request(db=db, user_id=5, data=data)
        assert result["approver_id"] is None

    def test_normal_rotation_unaffected_when_requester_not_in_rotation(self):
        """A requester outside the approver pool doesn't change normal round-robin behavior."""
        db = MagicMock()
        mock_request_type = MagicMock(spec=RequestType)
        mock_request_type.id = 1
        mock_request_type.slug = "hardware_devices"
        mock_request_type.prefix = "HD"
        mock_request_type.counter = 0
        mock_request_type.is_active = True

        approver_a = MagicMock(spec=User)
        approver_a.id = 10
        approver_b = MagicMock(spec=User)
        approver_b.id = 11

        def query_side_effect(model):
            m = MagicMock()
            if model is RequestType:
                m.filter.return_value.with_for_update.return_value.first.return_value = mock_request_type
            elif model is User:
                m.filter.return_value.order_by.return_value.all.return_value = [approver_a, approver_b]
            elif model is Request:
                m.count.return_value = 1
            return m

        db.query.side_effect = query_side_effect

        data = MagicMock()
        data.request_type = "hardware_devices"
        data.title = "x"
        data.justification = "y"

        result = create_request(db=db, user_id=1, data=data)

        assert result["approver_id"] == 11


class TestCompleteRequest:
    """IT35-264 - PATCH /requests/{request_id}/complete."""

    def test_complete_success(self):
        """Approved request owned by the caller can be completed."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.approved, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        result = complete_request(db=db, request_id="HD-001", user_id=1)

        assert mock_request.status == RequestStatus.completed
        assert mock_request.completion_date is not None
        assert result["status"] == "completed"
        assert result["request_id"] == "HD-001"
        assert result["message"] == "Request marked as completed successfully."

        # US-014 added a second db.add() for the notification, so pick the audit
        # row out of the calls rather than assuming it is the only one.
        audit_logs = [
            c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], AuditLog)
        ]
        assert len(audit_logs) == 1
        audit_log = audit_logs[0]

        assert audit_log.user_id == 1
        assert audit_log.action == "REQUEST_COMPLETED"
        assert audit_log.resource_type == "request"
        assert audit_log.resource_id == mock_request.id
        assert audit_log.old_status == "approved"
        assert audit_log.new_status == "completed"

    def test_complete_not_found(self):
        """Completing a non-existent request should raise 404."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            complete_request(db=db, request_id="HD-999", user_id=1)

        assert exc_info.value.status_code == 404

    def test_complete_wrong_owner(self):
        """Completing someone else's request should raise 403."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.approved, requester_id=2
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            complete_request(db=db, request_id="HD-001", user_id=1)

        assert exc_info.value.status_code == 403
        assert mock_request.status == RequestStatus.approved

    def test_complete_invalid_status_transition(self):
        """Completing a request that isn't approved should raise 400."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.pending, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            complete_request(db=db, request_id="HD-001", user_id=1)

        assert exc_info.value.status_code == 400
        assert mock_request.status == RequestStatus.pending

    def test_complete_db_error_wraps_as_runtime_error(self):
        """A DB failure during completion must raise RuntimeError, not leak
        the raw SQLAlchemyError, and must roll back."""
        from sqlalchemy.exc import SQLAlchemyError

        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.approved, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        with pytest.raises(RuntimeError):
            complete_request(db=db, request_id="HD-001", user_id=1)

        db.rollback.assert_called_once()


class TestCancelRequest:
    """US-015 (IT35-227) - PATCH /requests/{request_id}/cancel."""

    def test_cancel_success(self):
        """Pending request owned by the caller can be cancelled."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.pending, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        result = cancel_request(db=db, request_id="HD-001", user_id=1, user_role=UserRole.requester)

        assert mock_request.status == RequestStatus.cancelled
        assert mock_request.cancellation_date is not None
        assert result["status"] == "cancelled"
        assert result["request_id"] == "HD-001"
        assert result["message"] == "Request cancelled successfully."
        assert result["cancellation_date"] is not None
        assert result["cancellation_date"] == mock_request.cancellation_date

        audit_logs = [
            c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], AuditLog)
        ]
        assert len(audit_logs) == 1
        audit_log = audit_logs[0]

        assert audit_log.user_id == 1
        assert audit_log.action == "REQUEST_CANCELLED"
        assert audit_log.resource_type == "request"
        assert audit_log.resource_id == mock_request.id
        assert audit_log.old_status == "pending"
        assert audit_log.new_status == "cancelled"

    def test_cancel_allowed_for_approver_owner(self):
        """US-019: an approver may cancel their own pending request."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.pending, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        result = cancel_request(db=db, request_id="HD-001", user_id=1, user_role=UserRole.approver)

        assert result["status"] == "cancelled"
        assert result["cancellation_date"] is not None

    def test_cancel_blocked_for_unauthorized_role(self):
        """A caller whose role is neither requester nor approver gets 403."""
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            cancel_request(db=db, request_id="HD-001", user_id=1, user_role=UserRole.admin)

        assert exc_info.value.status_code == 403

    def test_cancel_not_found(self):
        """Cancelling a non-existent request should raise 404."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            cancel_request(db=db, request_id="HD-999", user_id=1, user_role=UserRole.requester)

        assert exc_info.value.status_code == 404

    def test_cancel_wrong_owner(self):
        """Cancelling someone else's request should raise 403."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.pending, requester_id=2
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            cancel_request(db=db, request_id="HD-001", user_id=1, user_role=UserRole.requester)

        assert exc_info.value.status_code == 403
        assert mock_request.status == RequestStatus.pending

    def test_cancel_invalid_status_transition(self):
        """Cancelling a request that isn't pending should raise 400."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.approved, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            cancel_request(db=db, request_id="HD-001", user_id=1, user_role=UserRole.requester)

        assert exc_info.value.status_code == 400
        assert mock_request.status == RequestStatus.approved

    def test_cancel_db_error_wraps_as_runtime_error(self):
        """A DB failure during cancellation must raise RuntimeError, not leak
        the raw SQLAlchemyError, and must roll back."""
        from sqlalchemy.exc import SQLAlchemyError

        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.pending, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        with pytest.raises(RuntimeError):
            cancel_request(db=db, request_id="HD-001", user_id=1, user_role=UserRole.requester)

        db.rollback.assert_called_once()


class TestCompleteRequestStatusGuard:
    """DO - Verify Complete Request Workflow: only `approved` requests may
    transition to `completed`; every other status must be rejected."""

    @pytest.mark.parametrize("blocked_status", [
        RequestStatus.pending,
        RequestStatus.rejected,
        RequestStatus.completed,
        RequestStatus.cancelled,
    ])
    def test_complete_blocked_for_non_approved_statuses(self, blocked_status):
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=blocked_status, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(HTTPException) as exc_info:
            complete_request(db=db, request_id="HD-001", user_id=1)

        assert exc_info.value.status_code == 400
        assert "Only approved requests can be marked as completed." in exc_info.value.detail
        assert mock_request.status == blocked_status
        db.add.assert_not_called()
        db.commit.assert_not_called()


class TestCompleteRequestResponseAndAudit:
    """DO - Verify completion_date in response, and GDPR-safe audit logs."""

    def test_completion_date_is_stored_and_returned_in_response(self):
        """Regression: completion_date must be set on the model AND present
        in the response dict (RequestActionResponse), not just the DB row."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.approved, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        result = complete_request(db=db, request_id="HD-001", user_id=1)

        assert mock_request.completion_date is not None
        assert "completion_date" in result
        assert result["completion_date"] == mock_request.completion_date

    def test_audit_log_does_not_contain_password_or_token_fields(self):
        """GDPR - the AuditLog record written on completion must never carry
        password or JWT/token data in any of the fields the service sets."""
        db = MagicMock()
        mock_request = make_mock_request_with_details(
            1, status=RequestStatus.approved, requester_id=1
        )
        db.query.return_value.filter.return_value.first.return_value = mock_request

        complete_request(db=db, request_id="HD-001", user_id=1)

        audit_logs = [
            c[0][0] for c in db.add.call_args_list if isinstance(c[0][0], AuditLog)
        ]
        assert len(audit_logs) == 1
        audit_log = audit_logs[0]

        import re
        jwt_pattern = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
        sensitive_keywords = ("password", "bearer ", "jwt", "token")

        for field in ["action", "resource_type", "old_status", "new_status"]:
            value = getattr(audit_log, field, None)
            if isinstance(value, str):
                assert not jwt_pattern.search(value)
                assert not any(kw in value.lower() for kw in sensitive_keywords)
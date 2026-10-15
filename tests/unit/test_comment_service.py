# tests/unit/test_comment_service.py

import pytest
from unittest.mock import MagicMock
from app.services.comment_service import (
    create_comment,
    get_comments_for_requester,
    get_comments_for_approver,
)
from app.models.request import Request, RequestStatus
from app.models.comment import Comment


def make_mock_request(request_number="HD-001", status=RequestStatus.pending, user_id=1, approver_id=3, req_uuid="uuid-123"):
    req = MagicMock(spec=Request)
    req.id = req_uuid
    req.request_number = request_number
    req.status = status
    req.user_id = user_id
    req.approver_id = approver_id
    return req


def make_mock_comment(content="Test comment", author_name="Test User", created_at="2026-06-30T10:00:00"):
    comment = MagicMock(spec=Comment)
    comment.id = "comment-uuid-1"
    comment.content = content
    comment.created_at = created_at
    mock_author = MagicMock()
    mock_author.name = author_name
    comment.author = mock_author
    return comment


class TestCreateComment:

    def test_create_success(self):
        """Should successfully create a comment on a pending request owned by the user"""
        db = MagicMock()
        mock_request = make_mock_request(status=RequestStatus.pending, user_id=1)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        comment = create_comment(db=db, request_id="HD-001", author_id=1, content="Please expedite")

        # Two rows now: the comment plus its COMMENT_CREATED audit row
        # (IT35-306), committed together.
        assert db.add.call_count == 2
        db.commit.assert_called_once()

    def test_create_writes_comment_created_audit_row(self):
        """IT35-306 / US-011 AC1: comment creation must land in audit_log,
        not only in the application logger. resource_type is "request" so the
        Audit Logs page can show which request the comment belongs to."""
        from app.models.audit_log import AuditLog

        db = MagicMock()
        mock_request = make_mock_request(status=RequestStatus.pending, user_id=1)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        create_comment(db=db, request_id="HD-001", author_id=1, content="Please expedite")

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1

        audit = audit_rows[0]
        assert audit.action == "COMMENT_CREATED"
        assert audit.user_id == 1
        assert audit.resource_type == "request"
        assert audit.resource_id == mock_request.id

    def test_audit_row_is_added_before_commit(self):
        """The audit row must be queued while the transaction is still open,
        so a failed commit rolls back the comment AND its audit entry."""
        from app.models.audit_log import AuditLog

        db = MagicMock()
        mock_request = make_mock_request(status=RequestStatus.pending, user_id=1)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        order = []
        db.add.side_effect = lambda obj: order.append(
            "audit" if isinstance(obj, AuditLog) else "comment"
        )
        db.commit.side_effect = lambda: order.append("commit")

        create_comment(db=db, request_id="HD-001", author_id=1, content="Please expedite")

        assert order == ["comment", "audit", "commit"]

    def test_create_fails_request_not_found(self):
        """Should raise LookupError when request_id does not exist"""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(LookupError):
            create_comment(db=db, request_id="HD-999", author_id=1, content="Hello")

    def test_create_fails_not_owner(self):
        """Should raise PermissionError when the user does not own the request"""
        db = MagicMock()
        mock_request = make_mock_request(status=RequestStatus.pending, user_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(PermissionError):
            create_comment(db=db, request_id="HD-001", author_id=1, content="Hello")

    def test_create_fails_not_pending(self):
        """Should raise ValueError when request is not in pending status"""
        db = MagicMock()
        mock_request = make_mock_request(status=RequestStatus.approved, user_id=1)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(ValueError) as exc_info:
            create_comment(db=db, request_id="HD-001", author_id=1, content="Too late")

        assert "pending" in str(exc_info.value).lower()

    def test_create_fails_empty_content(self):
        """Should raise ValueError when content is empty or whitespace only"""
        db = MagicMock()
        mock_request = make_mock_request(status=RequestStatus.pending, user_id=1)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(ValueError) as exc_info:
            create_comment(db=db, request_id="HD-001", author_id=1, content="   ")

        assert "empty" in str(exc_info.value).lower()


class TestGetCommentsForRequester:

    def test_returns_comments_in_chronological_order(self):
        """Should return comments ordered oldest first"""
        db = MagicMock()
        mock_request = make_mock_request(user_id=1)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        comment1 = make_mock_comment(content="First", created_at="2026-06-30T09:00:00")
        comment2 = make_mock_comment(content="Second", created_at="2026-06-30T10:00:00")

        query_mock = MagicMock()
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = [comment1, comment2]

        def query_side_effect(model):
            if model is Comment:
                return query_mock
            m = MagicMock()
            m.filter.return_value.first.return_value = mock_request
            return m

        db.query.side_effect = query_side_effect

        result = get_comments_for_requester(db=db, request_id="HD-001", user_id=1)

        assert len(result) == 2
        assert result[0]["content"] == "First"
        assert result[1]["content"] == "Second"

    def test_returns_none_when_request_not_found(self):
        """Should return None when request_id does not exist"""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_comments_for_requester(db=db, request_id="HD-999", user_id=1)

        assert result is None

    def test_raises_permission_error_for_non_owner(self):
        """Should raise PermissionError when requester does not own the request"""
        db = MagicMock()
        mock_request = make_mock_request(user_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(PermissionError):
            get_comments_for_requester(db=db, request_id="HD-001", user_id=1)


class TestGetCommentsForApprover:

    def test_returns_comments_for_assigned_approver(self):
        """Should return comments when approver is assigned to the request"""
        db = MagicMock()
        mock_request = make_mock_request(approver_id=3)

        comment1 = make_mock_comment(content="Hello")

        query_mock = MagicMock()
        query_mock.options.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = [comment1]

        def query_side_effect(model):
            if model is Comment:
                return query_mock
            m = MagicMock()
            m.filter.return_value.first.return_value = mock_request
            return m

        db.query.side_effect = query_side_effect

        result = get_comments_for_approver(db=db, request_id="HD-001", approver_id=3)

        assert len(result) == 1
        assert result[0]["content"] == "Hello"

    def test_returns_none_when_request_not_found(self):
        """Should return None when request_id does not exist"""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_comments_for_approver(db=db, request_id="HD-999", approver_id=3)

        assert result is None

    def test_raises_permission_error_for_unassigned_approver(self):
        """Should raise PermissionError when approver is not assigned to the request"""
        db = MagicMock()
        mock_request = make_mock_request(approver_id=99)
        db.query.return_value.filter.return_value.first.return_value = mock_request

        with pytest.raises(PermissionError):
            get_comments_for_approver(db=db, request_id="HD-001", approver_id=3)
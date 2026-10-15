# tests/unit/test_notification_service.py
# IT35-282 - GET /notifications, mocked DB (Notification model per IT35-281).

from datetime import datetime

import pytest
from unittest.mock import MagicMock
from app.services.notification_service import get_notifications
from app.models.notification import Notification


def make_mock_notification(id, user_id=1, is_read=False):
    n = MagicMock(spec=Notification)
    n.id = id
    n.user_id = user_id
    n.request_id = f"HD-00{id}"
    n.request_type = "hardware_devices"
    n.status = "approved"
    n.is_read = is_read
    return n


class TestGetNotifications:
    """IT35-282 - get_notifications()."""

    def test_returns_only_callers_own_notifications(self):
        db = MagicMock()
        own = [make_mock_notification(1, user_id=1)]
        query = db.query.return_value.filter.return_value
        query.count.return_value = 1
        query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = own
        db.query.return_value.filter.return_value.count.return_value = 0  # unread_count query

        result = get_notifications(db=db, user_id=1)

        assert result["items"] == own
        # Two SQLAlchemy expressions are never `==` to each other (comparing them
        # builds a third expression), so assert_any_call cannot match one. Compare
        # the rendered SQL instead.
        filter_args = [str(c[0][0]) for c in db.query.return_value.filter.call_args_list]
        assert str(Notification.user_id == 1) in filter_args

    def test_sorted_newest_first(self):
        db = MagicMock()
        query = db.query.return_value.filter.return_value
        query.count.return_value = 2
        get_notifications(db=db, user_id=1)

        query.order_by.assert_called_once()
        # confirms .desc() ordering was requested on created_at
        call_arg = query.order_by.call_args[0][0]
        assert "DESC" in str(call_arg).upper()

    def test_unread_only_filters(self):
        db = MagicMock()
        get_notifications(db=db, user_id=1, unread_only=True)

        # filtered at least twice: user_id, then is_read == False
        assert db.query.return_value.filter.call_count >= 1
        assert db.query.return_value.filter.return_value.filter.called

    def test_unread_count_independent_of_filter_and_page(self):
        db = MagicMock()
        query = db.query.return_value.filter.return_value
        query.count.return_value = 5
        db.query.return_value.filter.return_value.count.return_value = 3

        result_all = get_notifications(db=db, user_id=1, unread_only=False, page=2, limit=1)
        result_unread = get_notifications(db=db, user_id=1, unread_only=True, page=1, limit=50)

        assert result_all["unread_count"] == result_unread["unread_count"]

    def test_pagination(self):
        db = MagicMock()
        query = db.query.return_value.filter.return_value
        query.count.return_value = 45

        result = get_notifications(db=db, user_id=1, page=2, limit=20)

        assert result["total"] == 45
        assert result["page"] == 2
        assert result["limit"] == 20
        query.order_by.return_value.offset.assert_called_once_with(20)
        query.order_by.return_value.offset.return_value.limit.assert_called_once_with(20)

    def test_empty_message_when_no_results(self):
        db = MagicMock()
        query = db.query.return_value.filter.return_value
        query.count.return_value = 0
        query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_notifications(db=db, user_id=1)

        assert result["total"] == 0
        assert result["empty_message"] == "No notifications found."

    def test_limit_clamped_to_100(self):
        db = MagicMock()
        query = db.query.return_value.filter.return_value
        query.count.return_value = 0

        result = get_notifications(db=db, user_id=1, limit=500)

        assert result["limit"] == 100

class TestCreateNotification:
    """IT35-281 - create_notification()."""

    from app.services.notification_service import create_notification

    @pytest.mark.parametrize("status,expected_title,expected_message", [
        ("approved",  "Request Approved",  "Your request HD-001 has been approved."),
        ("rejected",  "Request Rejected",  "Your request HD-001 has been rejected."),
        ("completed", "Request Completed", "Your request HD-001 has been completed."),
        ("cancelled", "Request Cancelled", "Your request HD-001 has been cancelled."),
    ])
    def test_correct_title_and_message_per_status(self, status, expected_title, expected_message):
        """create_notification writes correct title/message for each status."""
        from app.services.notification_service import create_notification
        db = MagicMock()

        notification = create_notification(
            db=db,
            user_id=1,
            request_id="HD-001",
            request_type="hardware_devices",
            status=status,
            status_change_date=datetime(2026, 7, 20, 10, 30, 0),
        )

        assert notification is not None
        assert notification.title == expected_title
        assert notification.message == expected_message
        db.add.assert_called_once_with(notification)

    def test_is_read_defaults_to_false(self):
        """New notifications must be unread."""
        from app.services.notification_service import create_notification
        db = MagicMock()

        notification = create_notification(
            db=db,
            user_id=1,
            request_id="HD-001",
            request_type="hardware_devices",
            status="approved",
            status_change_date=datetime(2026, 7, 20, 10, 30, 0),
        )

        assert notification.is_read is False

    def test_not_created_for_pending_status(self):
        """Pending status must NOT trigger a notification."""
        from app.services.notification_service import create_notification
        db = MagicMock()

        result = create_notification(
            db=db,
            user_id=1,
            request_id="HD-001",
            request_type="hardware_devices",
            status="pending",
            status_change_date=datetime(2026, 7, 20, 10, 30, 0),
        )

        assert result is None
        db.add.assert_not_called()

    @pytest.mark.parametrize("field", ["request_type", "status_change_date"])
    def test_rejects_none_for_required_fields(self, field):
        """Both columns are NOT NULL (5a1bc9c5c896) and required by the spec, so
        create_notification must refuse None instead of writing a row that
        NotificationResponse cannot serialize."""
        from app.services.notification_service import create_notification
        db = MagicMock()

        kwargs = {
            "db": db,
            "user_id": 1,
            "request_id": "HD-001",
            "request_type": "hardware_devices",
            "status": "approved",
            "status_change_date": datetime(2026, 7, 20, 10, 30, 0),
        }
        kwargs[field] = None

        with pytest.raises(ValueError):
            create_notification(**kwargs)

        db.add.assert_not_called()

    def test_pending_is_skipped_before_validation(self):
        """A pending status short-circuits, so incomplete data never reaches the
        required-field check - callers should not have to care."""
        from app.services.notification_service import create_notification
        db = MagicMock()

        result = create_notification(
            db=db,
            user_id=1,
            request_id="HD-001",
            request_type=None,
            status="pending",
            status_change_date=None,
        )

        assert result is None
        db.add.assert_not_called()


class TestNotifyStatusChange:
    """IT35-281 - the bridge approve/reject/complete/cancel call after commit."""

    def make_request(self, status="approved", slug="hardware_devices", owner_id=3):
        request = MagicMock()
        request.user_id = owner_id
        request.request_number = "HD-001"
        request.status = MagicMock()
        request.status.value = status
        request.request_type = MagicMock()
        request.request_type.slug = slug
        return request

    def test_notification_goes_to_the_request_owner(self):
        """On an approval the actor is the approver, but the notification must
        be addressed to the requester who owns the request."""
        from app.services.notification_service import notify_status_change
        db = MagicMock()

        notification = notify_status_change(
            db, self.make_request(owner_id=3), datetime(2026, 7, 20, 10, 30, 0)
        )

        assert notification.user_id == 3

    @pytest.mark.parametrize("slug", [
        "hardware_devices",
        "software_access",
        "other",
        "training_courses",   # US-017: a type an admin added, unknown to any dict
    ])
    def test_notification_carries_the_slug_from_the_row(self, slug):
        """US-017 (M5): the slug lives in the request_types table now, so any
        type works — including ones created after this code was written."""
        from app.services.notification_service import notify_status_change
        db = MagicMock()

        notification = notify_status_change(
            db, self.make_request(slug=slug), datetime(2026, 7, 20, 10, 30, 0)
        )

        assert notification.request_type == slug

    def test_missing_request_type_falls_back_to_other(self):
        from app.services.notification_service import notify_status_change
        db = MagicMock()
        request = self.make_request()
        request.request_type = None

        notification = notify_status_change(
            db, request, datetime(2026, 7, 20, 10, 30, 0)
        )

        assert notification.request_type == "other"

    def test_a_broken_notification_does_not_raise(self):
        """The status change is already committed when we are called, so a
        failure here must not turn a successful approval into a 500."""
        from app.services.notification_service import notify_status_change
        db = MagicMock()
        db.commit.side_effect = RuntimeError("database is on fire")

        result = notify_status_change(
            db, self.make_request(), datetime(2026, 7, 20, 10, 30, 0)
        )

        assert result is None
        db.rollback.assert_called_once()

    def test_pending_writes_nothing(self):
        """Pending must not produce a notification, and must not commit."""
        from app.services.notification_service import notify_status_change
        db = MagicMock()

        result = notify_status_change(
            db, self.make_request(status="pending"), datetime(2026, 7, 20, 10, 30, 0)
        )

        assert result is None
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_missing_status_change_date_falls_back_to_now(self):
        """The column is NOT NULL, so a caller that forgets the date still gets
        a usable row rather than an IntegrityError."""
        from app.services.notification_service import notify_status_change
        db = MagicMock()

        notification = notify_status_change(db, self.make_request(), None)

        assert notification.status_change_date is not None


class TestMarkNotificationRead:
    """IT35-283 - mark_notification_read()."""

    def test_sets_is_read_true_and_commits(self):
        from app.services.notification_service import mark_notification_read
        db = MagicMock()
        notification = make_mock_notification(1, user_id=1, is_read=False)
        db.query.return_value.filter.return_value.first.return_value = notification

        result = mark_notification_read(db=db, notification_id=1, user_id=1)

        assert result is notification
        assert notification.is_read is True
        db.commit.assert_called_once()

    def test_returns_none_when_not_found(self):
        """Route turns this into a 404."""
        from app.services.notification_service import mark_notification_read
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = mark_notification_read(db=db, notification_id=999, user_id=1)

        assert result is None
        db.commit.assert_not_called()

    def test_raises_permission_error_for_other_users_notification(self):
        """Route turns this into a 403."""
        from app.services.notification_service import mark_notification_read
        db = MagicMock()
        notification = make_mock_notification(1, user_id=2, is_read=False)
        db.query.return_value.filter.return_value.first.return_value = notification

        with pytest.raises(PermissionError):
            mark_notification_read(db=db, notification_id=1, user_id=1)

        assert notification.is_read is False
        db.commit.assert_not_called()

    def test_does_not_delete_the_notification(self):
        """Marking as read keeps the row - the bell list still shows it."""
        from app.services.notification_service import mark_notification_read
        db = MagicMock()
        notification = make_mock_notification(1, user_id=1, is_read=False)
        db.query.return_value.filter.return_value.first.return_value = notification

        mark_notification_read(db=db, notification_id=1, user_id=1)

        db.delete.assert_not_called()
# tests/unit/test_approver_schemas.py
# IT35-279 (US-024) — schema validation only, no DB involved.

from datetime import datetime

from app.schemas.approver import (
    ApprovalQueueStatusCounts,
    ApprovalQueueResponse,
    ApprovalQueueItem,
)


class TestApprovalQueueStatusCounts:

    def test_serialises_all_five_fields_correctly(self):
        counts = ApprovalQueueStatusCounts(
            pending=3,
            approved=12,
            rejected=2,
            completed=8,
            cancelled=1,
        )

        data = counts.model_dump()

        assert data == {
            "pending": 3,
            "approved": 12,
            "rejected": 2,
            "completed": 8,
            "cancelled": 1,
        }


class TestApprovalQueueResponse:

    def _make_item(self):
        return ApprovalQueueItem(
            request_id="HD-001",
            requester_name="Test Requester",
            request_type="hardware_devices",
            submission_date=datetime(2026, 1, 1, 9, 0, 0),
            request_status="pending",
            updated_at=datetime(2026, 1, 2, 9, 0, 0),
        )

    def test_serialises_page_limit_total_status_counts(self):
        response = ApprovalQueueResponse(
            items=[self._make_item()],
            page=2,
            limit=10,
            total=25,
            status_counts=ApprovalQueueStatusCounts(
                pending=3, approved=12, rejected=2, completed=8, cancelled=1
            ),
            empty_message=None,
        )

        data = response.model_dump()

        assert data["page"] == 2
        assert data["limit"] == 10
        assert data["total"] == 25
        assert data["status_counts"] == {
            "pending": 3,
            "approved": 12,
            "rejected": 2,
            "completed": 8,
            "cancelled": 1,
        }
        assert len(data["items"]) == 1

    def test_empty_message_is_nullable(self):
        response = ApprovalQueueResponse(
            items=[],
            page=1,
            limit=20,
            total=0,
            status_counts=ApprovalQueueStatusCounts(
                pending=0, approved=0, rejected=0, completed=0, cancelled=0
            ),
            empty_message=None,
        )

        data = response.model_dump()

        assert data["empty_message"] is None

    def test_empty_message_when_provided_serialises_as_string(self):
        response = ApprovalQueueResponse(
            items=[],
            page=1,
            limit=20,
            total=0,
            status_counts=ApprovalQueueStatusCounts(
                pending=0, approved=0, rejected=0, completed=0, cancelled=0
            ),
            empty_message="No pending requests found.",
        )

        data = response.model_dump()

        assert data["empty_message"] == "No pending requests found."
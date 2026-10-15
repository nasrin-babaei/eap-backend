# tests/unit/test_audit_log.py

import csv
import io
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.models.audit_log import AuditLog
from app.services.audit_service import (
    AUDIT_EXPORT_COLUMNS,
    export_audit_logs_csv,
    get_audit_logs,
)


class TestGetAuditLogs:

    def test_filters_by_integer_resource_id_without_type_error(self):
        """Regression for IT35-228: resource_id filter must accept an
        integer, matching AuditLog.resource_id's Integer column
        (converted back from String — see migration
        c8d83176fac8_convert_audit_log_resource_id_to_integer)."""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.outerjoin.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 0
        query_mock.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_audit_logs(db=db, resource_id=1)

        assert result["items"] == []
        assert result["total"] == 0
        query_mock.filter.assert_called()

    def test_no_resource_id_filter_skips_filter_call_for_it(self):
        """When resource_id isn't provided, no filter should be applied
        for it (only action/resource_type filters would apply, and none
        are given here, so filter() should not be called at all)."""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.outerjoin.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 5
        query_mock.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_audit_logs(db=db)

        assert result["total"] == 5
        query_mock.filter.assert_not_called()


    def test_start_date_after_end_date_raises_400(self):
        """IT35-305 / US-011 AC: 400 when start_date is after end_date."""
        import pytest
        from datetime import date
        from fastapi import HTTPException

        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            get_audit_logs(
                db=db,
                start_date=date(2026, 8, 10),
                end_date=date(2026, 8, 1),
            )

        assert exc_info.value.status_code == 400
        assert "start_date" in exc_info.value.detail

    def test_user_name_filter_applies_filter(self):
        """IT35-305 / US-011 AC: filter by User Name."""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.outerjoin.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 0
        query_mock.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        get_audit_logs(db=db, user_name="Jane")

        query_mock.filter.assert_called()

    def test_request_id_filter_applies_filter(self):
        """IT35-305 / US-011 AC: filter by Request ID (human id, e.g. HD-001)."""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.outerjoin.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 0
        query_mock.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        get_audit_logs(db=db, request_id="HD-001")

        query_mock.filter.assert_called()

    def test_search_filter_applies_filter(self):
        """IT35-305 / US-011 AC: administrators can search audit logs."""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.outerjoin.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 0
        query_mock.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        get_audit_logs(db=db, search="approved")

        query_mock.filter.assert_called()

    def test_empty_results_sets_empty_message(self):
        """IT35-305 / US-011 AC: filtered results show an empty-state message,
        not a blank table, when nothing matches."""
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.outerjoin.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 0
        query_mock.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

        result = get_audit_logs(db=db, action="REQUEST_APPROVED")

        assert result["empty_message"] == "No audit records match the selected filters."

    def test_nonempty_results_have_no_empty_message(self):
        """empty_message should be null when there ARE matching rows."""
        from unittest.mock import MagicMock as MM
        from datetime import datetime

        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.outerjoin.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.count.return_value = 1

        mock_log = MM()
        mock_log.id = 501
        mock_log.user_id = 2
        mock_log.action = "REQUEST_APPROVED"
        mock_log.resource_type = "request"
        mock_log.resource_id = 1
        mock_log.old_status = "pending"
        mock_log.new_status = "approved"
        mock_log.timestamp = datetime(2026, 7, 20, 10, 30, 0)

        query_mock.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            (mock_log, "Jane Manager", "HD-001")
        ]

        result = get_audit_logs(db=db)

        assert result["empty_message"] is None
        assert result["items"][0]["user_name"] == "Jane Manager"
        assert result["items"][0]["request_id"] == "HD-001"


def make_export_db(rows):
    """Mock chain for the export: no offset/limit, straight order_by().all()."""
    db = MagicMock()
    query_mock = db.query.return_value
    query_mock.outerjoin.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value.all.return_value = rows
    return db, query_mock


def make_log_row(
    log_id=501,
    user_id=2,
    action="REQUEST_APPROVED",
    resource_type="request",
    resource_id=1,
    old_status="pending",
    new_status="approved",
    timestamp=datetime(2026, 7, 20, 10, 30, 0),
):
    log = MagicMock()
    log.id = log_id
    log.user_id = user_id
    log.action = action
    log.resource_type = resource_type
    log.resource_id = resource_id
    log.ip_address = "192.168.1.10"
    log.old_status = old_status
    log.new_status = new_status
    log.timestamp = timestamp
    return log


class TestExportAuditLogsCsv:
    """IT35-306 / US-011 AC: 'Audit records can be exported in CSV format.'"""

    def test_header_matches_the_contract_column_order(self):
        db, _ = make_export_db([])

        csv_text = export_audit_logs_csv(db=db, admin_id=9)

        header = csv_text.splitlines()[0]
        assert header == ",".join(AUDIT_EXPORT_COLUMNS)
        assert header == (
            "id,timestamp,user_name,user_id,action,"
            "resource_type,request_id,old_status,new_status"
        )

    def test_ip_address_is_never_exported(self):
        """GDPR: ip_address is personal data, US-011 does not ask for it, and a
        CSV leaves the system the moment it is downloaded."""
        db, _ = make_export_db([(make_log_row(), "Jane Manager", "HD-001")])

        csv_text = export_audit_logs_csv(db=db, admin_id=9)

        assert "ip_address" not in csv_text
        assert "192.168.1.10" not in csv_text

    def test_row_values_land_in_the_right_columns(self):
        db, _ = make_export_db([(make_log_row(), "Jane Manager", "HD-001")])

        csv_text = export_audit_logs_csv(db=db, admin_id=9)

        row = list(csv.DictReader(io.StringIO(csv_text)))[0]
        assert row["id"] == "501"
        assert row["timestamp"] == "2026-07-20T10:30:00Z"
        assert row["user_name"] == "Jane Manager"
        assert row["user_id"] == "2"
        assert row["action"] == "REQUEST_APPROVED"
        assert row["resource_type"] == "request"
        assert row["request_id"] == "HD-001"
        assert row["old_status"] == "pending"
        assert row["new_status"] == "approved"

    def test_null_user_name_and_request_id_become_empty_cells(self):
        """LOGIN_FAIL records no user (GDPR) and no request — both columns are
        nullable in the contract, so they must not crash the writer."""
        log = make_log_row(
            log_id=7, user_id=None, action="LOGIN_FAIL",
            resource_type="auth", resource_id=None,
            old_status=None, new_status=None,
        )
        db, _ = make_export_db([(log, None, None)])

        csv_text = export_audit_logs_csv(db=db, admin_id=9)

        row = list(csv.DictReader(io.StringIO(csv_text)))[0]
        assert row["user_name"] == ""
        assert row["request_id"] == ""
        assert row["action"] == "LOGIN_FAIL"

    def test_export_writes_its_own_audit_row(self):
        """Decision S: exporting the audit trail is itself an auditable action."""
        db, _ = make_export_db([])

        export_audit_logs_csv(db=db, admin_id=9)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1
        assert audit_rows[0].action == "AUDIT_LOG_EXPORTED"
        assert audit_rows[0].user_id == 9
        assert audit_rows[0].resource_type == "audit_log"
        db.commit.assert_called_once()

    def test_export_is_not_paged(self):
        """An export that silently stopped at row 10 would be worse than
        useless as a compliance record — no offset/limit may be applied."""
        db, query_mock = make_export_db([])

        export_audit_logs_csv(db=db, admin_id=9)

        query_mock.order_by.return_value.offset.assert_not_called()
        query_mock.order_by.return_value.limit.assert_not_called()

    def test_start_date_after_end_date_raises_400(self):
        db, _ = make_export_db([])

        with pytest.raises(HTTPException) as exc_info:
            export_audit_logs_csv(
                db=db,
                admin_id=9,
                start_date=date(2026, 8, 10),
                end_date=date(2026, 8, 1),
            )

        assert exc_info.value.status_code == 400
        # The failed export must not be audited — nothing was exported.
        db.commit.assert_not_called()

    def test_filters_are_applied(self):
        """The export takes the same filters as the list endpoint, so the admin
        exports exactly what they are looking at."""
        db, query_mock = make_export_db([])

        export_audit_logs_csv(
            db=db, admin_id=9, user_name="Jane", request_id="HD-001", search="approved"
        )

        assert query_mock.filter.call_count == 3

# ============================================================================
# US-012 (IT35-310) - GET /admin/activity/export
# ============================================================================

from app.services.audit_service import export_my_admin_activity_csv


class TestExportMyAdminActivityCsv:

    def _setup_mock(self, db, rows):
        """rows is a list of (AuditLog, name, request_number) tuples, matching
        what _build_audit_query's underlying query yields."""
        query_mock = db.query.return_value
        query_mock.outerjoin.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.all.return_value = rows
        return query_mock

    def _make_log(self, user_id=5, action="USER_ROLE_CHANGED", timestamp=None):
        log = MagicMock(spec=AuditLog)
        log.user_id = user_id
        log.action = action
        log.timestamp = timestamp or datetime(2026, 7, 15, 13, 45, 0)
        return log

    def test_returns_csv_text_and_row_count(self):
        db = MagicMock()
        log = self._make_log()
        self._setup_mock(db, [(log, "Admin Name", None)])

        csv_text, row_count = export_my_admin_activity_csv(db=db, admin_id=5)

        assert row_count == 1
        assert "admin_id,action_type,timestamp" in csv_text
        assert "USER_ROLE_CHANGED" in csv_text

    def test_no_results_returns_zero_rows(self):
        db = MagicMock()
        self._setup_mock(db, [])

        csv_text, row_count = export_my_admin_activity_csv(db=db, admin_id=5)

        assert row_count == 0
        assert "admin_id,action_type,timestamp" in csv_text

    def test_start_date_after_end_date_raises_400(self):
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            export_my_admin_activity_csv(
                db=db, admin_id=5,
                start_date=date(2026, 7, 31), end_date=date(2026, 7, 1),
            )

        assert exc_info.value.status_code == 400

    def test_scopes_to_the_calling_admins_own_rows(self):
        """Decision Q - there is no parameter that can point at somebody
        else's activity; the scoping filter is always applied on top of
        whatever _build_audit_query already added."""
        db = MagicMock()
        self._setup_mock(db, [])

        export_my_admin_activity_csv(db=db, admin_id=5)

        assert db.query.return_value.filter.called

    def test_writes_data_exported_audit_row(self):
        db = MagicMock()
        self._setup_mock(db, [])

        export_my_admin_activity_csv(db=db, admin_id=5)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1
        assert audit_rows[0].action == "DATA_EXPORTED"
        assert audit_rows[0].user_id == 5
        assert audit_rows[0].resource_type == "admin_activity"
        db.commit.assert_called_once()

    def test_timestamp_formatted_as_iso_with_z(self):
        db = MagicMock()
        log = self._make_log(timestamp=datetime(2026, 7, 15, 13, 45, 0))
        self._setup_mock(db, [(log, None, None)])

        csv_text, _ = export_my_admin_activity_csv(db=db, admin_id=5)

        assert "2026-07-15T13:45:00Z" in csv_text


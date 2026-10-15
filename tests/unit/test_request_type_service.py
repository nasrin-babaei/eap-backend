# tests/unit/test_request_type_service.py
# US-017 (IT35-74 / IT35-307 / IT35-308) — request type read, create, update,
# deactivate, activate.

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

from app.models.audit_log import AuditLog
from app.models.request_type import RequestType
from app.services.request_type_service import (
    create_request_type,
    list_request_types,
    slugify,
    update_request_type,
    set_request_type_active,
)


def make_mock_type(id=1, slug="hardware_devices", name="Hardware & Devices",
                   prefix="HD", is_active=True, description="Laptop, monitor, peripherals etc."):
    rt = MagicMock(spec=RequestType)
    rt.id = id
    rt.slug = slug
    rt.name = name
    rt.prefix = prefix
    rt.is_active = is_active
    rt.description = description
    return rt


def make_payload(name="Training & Courses", prefix="TC", description=None):
    """A stand-in for CreateRequestTypeRequest — the service only reads fields."""
    payload = MagicMock()
    payload.name = name
    payload.prefix = prefix
    payload.description = description
    return payload


def setup_list_mock(db, items):
    qm = db.query.return_value
    qm.filter.return_value = qm
    qm.order_by.return_value = qm
    qm.all.return_value = items
    return qm


class TestSlugify:
    """The slug is what every request stores, so the rule has to be exact."""

    @pytest.mark.parametrize("name,expected", [
        ("Hardware & Devices", "hardware_devices"),
        ("Software & Access", "software_access"),
        ("Workplace & Facilities", "workplace_facilities"),
        ("Human Resources", "human_resources"),
        ("Financial & Travel", "financial_travel"),
        ("Security & Compliance", "security_compliance"),
        ("Other", "other"),
    ])
    def test_seeded_names_keep_their_existing_slugs(self, name, expected):
        """The seven live types must not change slug — every request already
        created carries the old value."""
        assert slugify(name) == expected

    def test_runs_of_symbols_collapse_into_one_underscore(self):
        """" & " is three non-alphanumeric characters but only one separator."""
        assert slugify("Training & Courses") == "training_courses"

    def test_leading_and_trailing_symbols_are_dropped(self):
        assert slugify("  !Travel!  ") == "travel"


class TestListRequestTypes:

    def test_active_only_filters_and_sorts(self):
        """GET /request-types — the submission form list."""
        db = MagicMock()
        qm = setup_list_mock(db, [make_mock_type()])

        result = list_request_types(db=db, active_only=True)

        assert result["total"] == 1
        assert result["empty_message"] is None
        qm.filter.assert_called_once()   # the is_active filter was applied
        qm.order_by.assert_called_once()  # sorted by name, per the contract

    def test_admin_list_does_not_filter(self):
        """GET /admin/request-types — an admin must see inactive types too,
        otherwise they could never reactivate one."""
        db = MagicMock()
        qm = setup_list_mock(db, [make_mock_type(), make_mock_type(id=2, is_active=False)])

        result = list_request_types(db=db, active_only=False)

        assert result["total"] == 2
        qm.filter.assert_not_called()

    def test_empty_list_has_empty_message(self):
        db = MagicMock()
        setup_list_mock(db, [])

        result = list_request_types(db=db, active_only=True)

        assert result["total"] == 0
        assert result["empty_message"] == "No request types found."


class TestCreateRequestType:

    def _db_with_no_collisions(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        return db

    def test_create_success_returns_derived_slug_and_message(self):
        db = self._db_with_no_collisions()

        result = create_request_type(db=db, admin_id=9, data=make_payload())

        assert result["slug"] == "training_courses"
        assert result["name"] == "Training & Courses"
        assert result["prefix"] == "TC"
        assert result["is_active"] is True
        assert result["message"] == "Request type created successfully."
        db.commit.assert_called_once()

    def test_create_writes_request_type_created_audit_row(self):
        """AC12 + decision U — the affected type is identified by
        resource_type/resource_id, no new audit column needed."""
        db = self._db_with_no_collisions()

        create_request_type(db=db, admin_id=9, data=make_payload())

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1

        audit = audit_rows[0]
        assert audit.action == "REQUEST_TYPE_CREATED"
        assert audit.user_id == 9              # the admin who did it
        assert audit.resource_type == "request_type"
        assert audit.new_status == "active"
        assert audit.old_status is None        # nothing existed before

    def test_create_and_audit_share_one_commit(self):
        """A type must never be saved without its audit row, or the other way
        round — one commit for both."""
        db = self._db_with_no_collisions()

        create_request_type(db=db, admin_id=9, data=make_payload())

        assert db.add.call_count == 2          # the type + the audit row
        db.commit.assert_called_once()

    def test_duplicate_name_returns_409_with_exact_message(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = make_mock_type()

        with pytest.raises(HTTPException) as exc_info:
            create_request_type(db=db, admin_id=9, data=make_payload())

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == (
            "This request type name already exists. Please enter a unique name."
        )
        db.commit.assert_not_called()

    def test_duplicate_prefix_returns_409_with_exact_message(self):
        """Name and slug are free, only the prefix collides."""
        db = MagicMock()
        existing = make_mock_type()

        calls = {"n": 0}

        def first_side_effect():
            # 1st call: name lookup, 2nd: slug lookup, 3rd: prefix lookup.
            calls["n"] += 1
            return existing if calls["n"] == 3 else None

        db.query.return_value.filter.return_value.first.side_effect = first_side_effect

        with pytest.raises(HTTPException) as exc_info:
            create_request_type(db=db, admin_id=9, data=make_payload())

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == (
            "This request type prefix already exists. Please enter a unique prefix."
        )
        db.commit.assert_not_called()

    def test_nothing_is_saved_when_the_name_is_taken(self):
        """AC14 — a failed create must not leave a half-written row behind."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = make_mock_type()

        with pytest.raises(HTTPException):
            create_request_type(db=db, admin_id=9, data=make_payload())

        db.add.assert_not_called()

    def test_db_error_wraps_as_runtime_error_and_rolls_back(self):
        from sqlalchemy.exc import SQLAlchemyError

        db = self._db_with_no_collisions()
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        with pytest.raises(RuntimeError):
            create_request_type(db=db, admin_id=9, data=make_payload())

        db.rollback.assert_called_once()


class TestUpdateRequestType:
    """IT35-308 — PATCH /admin/request-types/{id}."""

    def _db_found_no_name_collision(self, existing_type):
        """1st query().filter().first() call -> fetch by id (found).
        2nd call (only made if name provided) -> uniqueness check (none)."""
        db = MagicMock()
        calls = {"n": 0}

        def first_side_effect():
            calls["n"] += 1
            return existing_type if calls["n"] == 1 else None

        db.query.return_value.filter.return_value.first.side_effect = first_side_effect
        return db

    def test_update_name_only_success(self):
        existing = make_mock_type(id=8, name="Training & Courses")
        db = self._db_found_no_name_collision(existing)

        result = update_request_type(
            db=db, admin_id=9, request_type_id=8,
            name="Training & Certification", description=None,
        )

        assert existing.name == "Training & Certification"
        assert result["name"] == "Training & Certification"
        assert result["message"] == "Request type updated successfully."
        db.commit.assert_called_once()

    def test_update_trims_the_new_name(self):
        existing = make_mock_type(id=8)
        db = self._db_found_no_name_collision(existing)

        update_request_type(db=db, admin_id=9, request_type_id=8,
                             name="  Training & Certification  ", description=None)

        assert existing.name == "Training & Certification"

    def test_update_description_only_success(self):
        """No name given -> the uniqueness-check query never runs, only the
        fetch-by-id call."""
        existing = make_mock_type(id=8)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing

        result = update_request_type(
            db=db, admin_id=9, request_type_id=8,
            name=None, description="New description",
        )

        assert existing.description == "New description"
        assert result["message"] == "Request type updated successfully."

    def test_update_both_fields_success(self):
        existing = make_mock_type(id=8, name="Training & Courses")
        db = self._db_found_no_name_collision(existing)

        result = update_request_type(
            db=db, admin_id=9, request_type_id=8,
            name="Training & Certification", description="Updated desc",
        )

        assert result["name"] == "Training & Certification"
        assert existing.description == "Updated desc"

    def test_update_not_found_returns_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            update_request_type(db=db, admin_id=9, request_type_id=999,
                                 name="New Name", description=None)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Request type not found."
        db.commit.assert_not_called()

    def test_update_duplicate_name_returns_409_with_exact_message(self):
        """1st call finds the target row, 2nd call finds a DIFFERENT row
        already using the requested name."""
        target = make_mock_type(id=8, name="Training & Courses")
        conflicting = make_mock_type(id=3, name="Human Resources")
        db = MagicMock()
        calls = {"n": 0}

        def first_side_effect():
            calls["n"] += 1
            return target if calls["n"] == 1 else conflicting

        db.query.return_value.filter.return_value.first.side_effect = first_side_effect

        with pytest.raises(HTTPException) as exc_info:
            update_request_type(db=db, admin_id=9, request_type_id=8,
                                 name="Human Resources", description=None)

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == (
            "This request type name already exists. Please enter a unique name."
        )
        db.commit.assert_not_called()

    def test_update_renaming_to_its_own_current_name_is_not_a_conflict(self):
        """The uniqueness query excludes the row's own id, so this must not
        raise 409 even though the name technically 'already exists'."""
        existing = make_mock_type(id=8, name="Training & Courses")
        db = self._db_found_no_name_collision(existing)

        result = update_request_type(db=db, admin_id=9, request_type_id=8,
                                      name="Training & Courses", description=None)

        assert result["name"] == "Training & Courses"

    def test_update_neither_field_raises_value_error(self):
        """Defensive check at the service layer — the route/schema normally
        catches this first via the model_validator."""
        db = MagicMock()

        with pytest.raises(ValueError):
            update_request_type(db=db, admin_id=9, request_type_id=8,
                                 name=None, description=None)

        db.query.assert_not_called()

    def test_update_writes_request_type_updated_audit_row(self):
        existing = make_mock_type(id=8)
        db = self._db_found_no_name_collision(existing)

        update_request_type(db=db, admin_id=9, request_type_id=8,
                             name="New Name", description=None)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1
        audit = audit_rows[0]
        assert audit.action == "REQUEST_TYPE_UPDATED"
        assert audit.user_id == 9
        assert audit.resource_type == "request_type"
        assert audit.resource_id == 8

    def test_update_and_audit_share_one_commit(self):
        existing = make_mock_type(id=8)
        db = self._db_found_no_name_collision(existing)

        update_request_type(db=db, admin_id=9, request_type_id=8,
                             name="New Name", description=None)

        assert db.add.call_count == 1          # only the audit row (type already existed)
        db.commit.assert_called_once()

    def test_db_error_wraps_as_runtime_error_and_rolls_back(self):
        from sqlalchemy.exc import SQLAlchemyError

        existing = make_mock_type(id=8)
        db = self._db_found_no_name_collision(existing)
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        with pytest.raises(RuntimeError):
            update_request_type(db=db, admin_id=9, request_type_id=8,
                                 name="New Name", description=None)

        db.rollback.assert_called_once()


class TestSetRequestTypeActive:
    """IT35-308 — PATCH /admin/request-types/{id}/deactivate and /activate."""

    def _db_returning(self, existing_type):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing_type
        return db

    def test_deactivate_success(self):
        existing = make_mock_type(id=8, is_active=True)
        db = self._db_returning(existing)

        result = set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=False)

        assert existing.is_active is False
        assert result["is_active"] is False
        assert result["message"] == "Request type deactivated successfully."
        db.commit.assert_called_once()

    def test_activate_success(self):
        existing = make_mock_type(id=8, is_active=False)
        db = self._db_returning(existing)

        result = set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=True)

        assert existing.is_active is True
        assert result["is_active"] is True
        assert result["message"] == "Request type activated successfully."

    def test_deactivate_message_is_not_actived_typo(self):
        """Regression guard for the f-string bug: {new_status}d produced
        'actived'/'inactived' instead of the contract's exact wording."""
        existing = make_mock_type(id=8, is_active=True)
        db = self._db_returning(existing)

        result = set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=False)

        assert "actived" not in result["message"]
        assert result["message"] == "Request type deactivated successfully."

    def test_activate_message_is_not_actived_typo(self):
        existing = make_mock_type(id=8, is_active=False)
        db = self._db_returning(existing)

        result = set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=True)

        assert result["message"] == "Request type activated successfully."

    def test_deactivate_is_idempotent(self):
        """Already inactive -> deactivating again must not error and must
        still return a 200-style success result."""
        existing = make_mock_type(id=8, is_active=False)
        db = self._db_returning(existing)

        result = set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=False)

        assert existing.is_active is False
        assert result["message"] == "Request type deactivated successfully."
        db.commit.assert_called_once()

    def test_activate_is_idempotent(self):
        existing = make_mock_type(id=8, is_active=True)
        db = self._db_returning(existing)

        result = set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=True)

        assert existing.is_active is True
        assert result["message"] == "Request type activated successfully."

    def test_not_found_returns_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            set_request_type_active(db=db, admin_id=9, request_type_id=999, is_active=False)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Request type not found."
        db.commit.assert_not_called()

    def test_deactivate_writes_audit_row_with_old_and_new_status(self):
        existing = make_mock_type(id=8, is_active=True)
        db = self._db_returning(existing)

        set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=False)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1
        audit = audit_rows[0]
        assert audit.action == "REQUEST_TYPE_DEACTIVATED"
        assert audit.user_id == 9
        assert audit.resource_type == "request_type"
        assert audit.resource_id == 8
        assert audit.old_status == "active"
        assert audit.new_status == "inactive"

    def test_activate_writes_audit_row_with_old_and_new_status(self):
        existing = make_mock_type(id=8, is_active=False)
        db = self._db_returning(existing)

        set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=True)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        audit = audit_rows[0]
        assert audit.action == "REQUEST_TYPE_ACTIVATED"
        assert audit.old_status == "inactive"
        assert audit.new_status == "active"

    def test_idempotent_repeat_call_still_writes_an_audit_row(self):
        """US-017: 'every ... deactivate action is recorded' — even a no-op
        repeat call is still logged."""
        existing = make_mock_type(id=8, is_active=False)
        db = self._db_returning(existing)

        set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=False)

        audit_rows = [
            call.args[0] for call in db.add.call_args_list
            if isinstance(call.args[0], AuditLog)
        ]
        assert len(audit_rows) == 1
        assert audit_rows[0].old_status == "inactive"
        assert audit_rows[0].new_status == "inactive"

    def test_db_error_wraps_as_runtime_error_and_rolls_back(self):
        from sqlalchemy.exc import SQLAlchemyError

        existing = make_mock_type(id=8, is_active=True)
        db = self._db_returning(existing)
        db.commit.side_effect = SQLAlchemyError("simulated DB failure")

        with pytest.raises(RuntimeError):
            set_request_type_active(db=db, admin_id=9, request_type_id=8, is_active=False)

        db.rollback.assert_called_once()
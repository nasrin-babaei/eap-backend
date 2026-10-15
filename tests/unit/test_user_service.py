# tests/unit/test_user_service.py
# US-009 — Admin user & role management

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from pydantic import ValidationError

from app.services.user_service import (
    list_users,
    create_user,
    update_user,
    update_user_role,
    set_user_active,
)
from app.schemas.user import CreateUserRequest, UpdateUserRequest
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog


ADMIN_ID = 1


def make_mock_user(id=5, email="bob@company.com", name="Bob",
                   role=UserRole.requester, is_active=True):
    user = MagicMock(spec=User)
    user.id = id
    user.email = email
    user.name = name
    user.role = role
    user.is_active = is_active
    return user


def collect_added(db):
    """
    Records every object passed to db.add(), so a test can inspect the User and
    the AuditLog the service created. db.flush() is faked to assign an id, which
    is what the real database would do.
    """
    added = []

    def fake_add(obj):
        added.append(obj)

    def fake_flush():
        # The first object added is the new user — give it the id the DB would.
        added[0].id = 7

    db.add.side_effect = fake_add
    db.flush.side_effect = fake_flush
    return added


def get_audit(added):
    """Returns the single AuditLog entry out of everything that was added."""
    entries = [obj for obj in added if isinstance(obj, AuditLog)]
    assert len(entries) == 1, f"expected exactly 1 audit entry, got {len(entries)}"
    return entries[0]


class TestListUsers:

    def test_returns_paginated_users(self):
        db = MagicMock()
        users = [make_mock_user(id=1), make_mock_user(id=2)]

        query_mock = db.query.return_value
        query_mock.count.return_value = 2
        query_mock.order_by.return_value = query_mock
        query_mock.offset.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.all.return_value = users

        result = list_users(db=db, page=1, limit=20)

        assert result["items"] == users
        assert result["total"] == 2
        assert result["page"] == 1
        assert result["limit"] == 20
        assert result["empty_message"] is None

    def test_empty_message_when_no_users(self):
        db = MagicMock()
        query_mock = db.query.return_value
        query_mock.count.return_value = 0
        query_mock.order_by.return_value = query_mock
        query_mock.offset.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.all.return_value = []

        result = list_users(db=db, page=1, limit=20)

        assert result["items"] == []
        assert result["empty_message"] == "No users found."


class TestCreateUser:

    def _payload(self, role=UserRole.requester):
        return CreateUserRequest(
            email="new@company.com",
            name="New Person",
            password="Password123!",
            role=role,
        )

    def test_create_user_success(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None  # email free
        added = collect_added(db)

        user = create_user(db=db, admin_id=ADMIN_ID, data=self._payload(UserRole.approver))

        assert user.email == "new@company.com"
        assert user.name == "New Person"
        assert user.role == UserRole.approver
        assert user.is_active is True
        db.commit.assert_called_once()

    def test_password_is_hashed_not_stored_raw(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        collect_added(db)

        user = create_user(db=db, admin_id=ADMIN_ID, data=self._payload())

        assert user.hashed_password != "Password123!"
        assert user.hashed_password.startswith("$2")  # bcrypt hash prefix

    def test_duplicate_email_raises_409(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = make_mock_user()

        with pytest.raises(HTTPException) as exc_info:
            create_user(db=db, admin_id=ADMIN_ID, data=self._payload())

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "A user with this email already exists."
        db.commit.assert_not_called()

    def test_writes_audit_log(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        added = collect_added(db)

        create_user(db=db, admin_id=ADMIN_ID, data=self._payload(UserRole.approver))

        audit = get_audit(added)
        assert audit.user_id == ADMIN_ID       # who did it
        assert audit.action == "USER_CREATED"
        assert audit.resource_type == "user"
        assert audit.resource_id == 7          # who it happened to
        assert audit.new_status == "approver"


class TestUpdateUser:

    def test_update_name_only(self):
        db = MagicMock()
        user = make_mock_user(name="Bob")
        db.query.return_value.filter.return_value.first.return_value = user
        added = collect_added(db)

        result = update_user(
            db=db, admin_id=ADMIN_ID, user_id=5,
            data=UpdateUserRequest(name="Bob Smith"),
        )

        assert result.name == "Bob Smith"
        assert result.email == "bob@company.com"  # untouched
        db.commit.assert_called_once()

    def test_update_email_when_free(self):
        db = MagicMock()
        user = make_mock_user()
        # 1st query: find the user. 2nd query: check nobody else owns the new email.
        db.query.return_value.filter.return_value.first.side_effect = [user, None]
        collect_added(db)

        result = update_user(
            db=db, admin_id=ADMIN_ID, user_id=5,
            data=UpdateUserRequest(email="bob.smith@company.com"),
        )

        assert result.email == "bob.smith@company.com"

    def test_email_taken_by_another_user_raises_400(self):
        db = MagicMock()
        user = make_mock_user()
        other = make_mock_user(id=6, email="taken@company.com")
        db.query.return_value.filter.return_value.first.side_effect = [user, other]

        with pytest.raises(HTTPException) as exc_info:
            update_user(
                db=db, admin_id=ADMIN_ID, user_id=5,
                data=UpdateUserRequest(email="taken@company.com"),
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Email already in use by another user."
        db.commit.assert_not_called()

    def test_unknown_user_raises_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            update_user(
                db=db, admin_id=ADMIN_ID, user_id=999,
                data=UpdateUserRequest(name="Ghost"),
            )

        assert exc_info.value.status_code == 404
        db.commit.assert_not_called()

    def test_writes_audit_log(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = make_mock_user()
        added = collect_added(db)

        update_user(db=db, admin_id=ADMIN_ID, user_id=5,
                    data=UpdateUserRequest(name="Bob Smith"))

        audit = get_audit(added)
        assert audit.action == "USER_UPDATED"
        assert audit.resource_id == 5


class TestUnknownFieldsAreRejected:
    """
    An unknown field must be a loud 422, not a silently dropped key.
    Without extra="forbid", PATCH {"full_name": "Bob"} returned 200 and changed
    nothing — the caller was told it succeeded when it had not.
    """

    def test_update_rejects_unknown_field(self):
        with pytest.raises(ValidationError) as exc_info:
            UpdateUserRequest(full_name="Bob Smith")

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("full_name",) and e["type"] == "extra_forbidden"
                   for e in errors)

    def test_update_still_accepts_the_real_fields(self):
        payload = UpdateUserRequest(name="Bob Smith", email="bob@company.com")
        assert payload.name == "Bob Smith"
        assert payload.email == "bob@company.com"

    def test_update_still_accepts_a_single_field(self):
        assert UpdateUserRequest(name="Bob Smith").email is None

    def test_create_rejects_unknown_fields(self):
        # The exact body the frontend was sending: Sprint 3 field names.
        with pytest.raises(ValidationError) as exc_info:
            CreateUserRequest(
                email="ada@company.com",
                full_name="Ada Lovelace",
                roles=["approver"],
                password="Password123!",
            )

        rejected = {e["loc"][0] for e in exc_info.value.errors()
                    if e["type"] == "extra_forbidden"}
        assert rejected == {"full_name", "roles"}

    def test_create_still_accepts_the_real_fields(self):
        payload = CreateUserRequest(
            email="ada@company.com",
            name="Ada Lovelace",
            password="Password123!",
            role=UserRole.approver,
        )
        assert payload.name == "Ada Lovelace"
        assert payload.role == UserRole.approver


class TestUpdateUserRole:

    def test_assign_each_role(self):
        for new_role in [UserRole.requester, UserRole.approver, UserRole.admin]:
            db = MagicMock()
            user = make_mock_user(role=UserRole.requester)
            db.query.return_value.filter.return_value.first.return_value = user
            collect_added(db)

            result = update_user_role(
                db=db, admin_id=ADMIN_ID, user_id=5, new_role=new_role
            )

            assert result.role == new_role
            db.commit.assert_called_once()

    def test_audit_log_records_old_and_new_role(self):
        db = MagicMock()
        user = make_mock_user(role=UserRole.requester)
        db.query.return_value.filter.return_value.first.return_value = user
        added = collect_added(db)

        update_user_role(db=db, admin_id=ADMIN_ID, user_id=5, new_role=UserRole.approver)

        audit = get_audit(added)
        assert audit.action == "USER_ROLE_CHANGED"
        assert audit.old_status == "requester"
        assert audit.new_status == "approver"

    def test_admin_cannot_change_own_role(self):
        """Guardrail: a self-demotion could lock every admin out of user management."""
        db = MagicMock()
        admin = make_mock_user(id=ADMIN_ID, role=UserRole.admin)
        db.query.return_value.filter.return_value.first.return_value = admin

        with pytest.raises(HTTPException) as exc_info:
            update_user_role(
                db=db, admin_id=ADMIN_ID, user_id=ADMIN_ID, new_role=UserRole.requester
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "You cannot change your own role."
        assert admin.role == UserRole.admin  # unchanged
        db.commit.assert_not_called()

    def test_unknown_user_raises_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            update_user_role(db=db, admin_id=ADMIN_ID, user_id=999,
                             new_role=UserRole.approver)

        assert exc_info.value.status_code == 404


class TestSetUserActive:

    def test_deactivate_user(self):
        db = MagicMock()
        user = make_mock_user(is_active=True)
        db.query.return_value.filter.return_value.first.return_value = user
        added = collect_added(db)

        result = set_user_active(db=db, admin_id=ADMIN_ID, user_id=5, is_active=False)

        assert result.is_active is False
        audit = get_audit(added)
        assert audit.action == "USER_DEACTIVATED"
        assert audit.old_status == "active"
        assert audit.new_status == "inactive"
        db.commit.assert_called_once()

    def test_activate_user(self):
        db = MagicMock()
        user = make_mock_user(is_active=False)
        db.query.return_value.filter.return_value.first.return_value = user
        added = collect_added(db)

        result = set_user_active(db=db, admin_id=ADMIN_ID, user_id=5, is_active=True)

        assert result.is_active is True
        audit = get_audit(added)
        assert audit.action == "USER_ACTIVATED"
        assert audit.old_status == "inactive"
        assert audit.new_status == "active"

    def test_admin_cannot_deactivate_themselves(self):
        """Guardrail: deactivating yourself locks you out on your next request."""
        db = MagicMock()
        admin = make_mock_user(id=ADMIN_ID, role=UserRole.admin)
        db.query.return_value.filter.return_value.first.return_value = admin

        with pytest.raises(HTTPException) as exc_info:
            set_user_active(db=db, admin_id=ADMIN_ID, user_id=ADMIN_ID, is_active=False)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "You cannot deactivate your own account."
        assert admin.is_active is True  # unchanged
        db.commit.assert_not_called()

    def test_admin_can_reactivate_themselves(self):
        """The guardrail must only block deactivation, not activation."""
        db = MagicMock()
        admin = make_mock_user(id=ADMIN_ID, role=UserRole.admin, is_active=False)
        db.query.return_value.filter.return_value.first.return_value = admin
        collect_added(db)

        result = set_user_active(db=db, admin_id=ADMIN_ID, user_id=ADMIN_ID, is_active=True)

        assert result.is_active is True

    def test_unknown_user_raises_404(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            set_user_active(db=db, admin_id=ADMIN_ID, user_id=999, is_active=False)

        assert exc_info.value.status_code == 404
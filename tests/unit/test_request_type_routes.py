# tests/unit/test_request_type_routes.py
# US-017 (IT35-74 / IT35-307 / IT35-308) — route-level tests for the request
# type endpoints. The role guard and the payload validation live in the
# route/schema layer, so these go through TestClient. The service is patched:
# no database is touched.

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.user import User, UserRole


def make_user(role: UserRole, user_id: int = 1) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.role = role
    return user


def make_type(id=1, slug="hardware_devices", name="Hardware & Devices",
              prefix="HD", is_active=True) -> dict:
    return {
        "id": id,
        "slug": slug,
        "name": name,
        "description": "Laptop, monitor, peripherals etc.",
        "prefix": prefix,
        "is_active": is_active,
        "created_at": datetime(2026, 6, 1, 9, 0, 0),
    }


AUTH = {"Authorization": "Bearer faketoken"}


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def client_as(role: UserRole) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: make_user(role)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


class TestPublicList:
    """GET /request-types — decision J: open to every authenticated user."""

    @pytest.mark.parametrize("role", [UserRole.requester, UserRole.approver, UserRole.admin])
    def test_every_authenticated_role_may_read_the_list(self, role):
        client = client_as(role)
        with patch(
            "app.api.routes.request_types.list_request_types",
            return_value={"items": [make_type()], "total": 1, "empty_message": None},
        ) as mock_list:
            response = client.get("/api/request-types", headers=AUTH)

        assert response.status_code == 200
        # Active only — that is what keeps deactivated types out of the form.
        assert mock_list.call_args.kwargs["active_only"] is True

    def test_response_carries_the_slug_the_form_must_submit(self):
        client = client_as(UserRole.requester)
        with patch(
            "app.api.routes.request_types.list_request_types",
            return_value={"items": [make_type()], "total": 1, "empty_message": None},
        ):
            response = client.get("/api/request-types", headers=AUTH)

        assert response.json()["items"][0]["slug"] == "hardware_devices"


class TestAdminList:
    """GET /admin/request-types — AC9/AC10: admin only."""

    def test_admin_gets_all_types_including_inactive(self):
        client = client_as(UserRole.admin)
        rows = [make_type(), make_type(id=8, slug="training_courses",
                                       name="Training & Courses", prefix="TC",
                                       is_active=False)]
        with patch(
            "app.api.routes.request_types.list_request_types",
            return_value={"items": rows, "total": 2, "empty_message": None},
        ) as mock_list:
            response = client.get("/api/admin/request-types", headers=AUTH)

        assert response.status_code == 200
        assert mock_list.call_args.kwargs["active_only"] is False
        assert response.json()["total"] == 2

    @pytest.mark.parametrize("role", [UserRole.requester, UserRole.approver])
    def test_non_admin_gets_403(self, role):
        client = client_as(role)
        response = client.get("/api/admin/request-types", headers=AUTH)

        assert response.status_code == 403
        assert response.json()["detail"] == "Only admins can manage request types."


class TestAdminCreate:
    """POST /admin/request-types."""

    def test_admin_can_create(self):
        client = client_as(UserRole.admin)
        created = make_type(id=8, slug="training_courses", name="Training & Courses",
                            prefix="TC")
        created["message"] = "Request type created successfully."

        with patch("app.api.routes.request_types.create_request_type", return_value=created):
            response = client.post(
                "/api/admin/request-types",
                json={"name": "Training & Courses", "description": "x", "prefix": "TC"},
                headers=AUTH,
            )

        assert response.status_code == 201
        assert response.json()["slug"] == "training_courses"
        assert response.json()["message"] == "Request type created successfully."

    @pytest.mark.parametrize("role", [UserRole.requester, UserRole.approver])
    def test_non_admin_cannot_create(self, role):
        client = client_as(role)
        response = client.post(
            "/api/admin/request-types",
            json={"name": "Training & Courses", "prefix": "TC"},
            headers=AUTH,
        )

        assert response.status_code == 403

    @pytest.mark.parametrize("bad_payload", [
        {"prefix": "TC"},                                   # AC2 — name missing
        {"name": "   ", "prefix": "TC"},                    # AC2 — whitespace only
        {"name": "Training", "prefix": "T"},                # too short
        {"name": "Training", "prefix": "TOOMANYLETTERS"},   # too long
        {"name": "Training", "prefix": "tc"},               # not uppercase
        {"name": "Training", "prefix": "T C"},              # not letters only
        {"name": "Training"},                               # prefix missing (decision K)
    ])
    def test_invalid_payload_is_rejected_with_422(self, bad_payload):
        client = client_as(UserRole.admin)
        with patch("app.api.routes.request_types.create_request_type") as mock_create:
            response = client.post("/api/admin/request-types", json=bad_payload, headers=AUTH)

        assert response.status_code == 422
        # Rejected before the service ran — nothing can be half-created.
        mock_create.assert_not_called()


class TestAdminUpdate:
    """PATCH /admin/request-types/{id} — IT35-308."""

    def test_admin_can_update(self):
        client = client_as(UserRole.admin)
        updated = make_type(id=8, slug="training_courses", name="Training & Certification",
                             prefix="TC")
        updated["message"] = "Request type updated successfully."

        with patch(
            "app.api.routes.request_types.update_request_type", return_value=updated
        ) as mock_update:
            response = client.patch(
                "/api/admin/request-types/8",
                json={"name": "Training & Certification"},
                headers=AUTH,
            )

        assert response.status_code == 200
        assert response.json()["name"] == "Training & Certification"
        assert response.json()["message"] == "Request type updated successfully."
        assert mock_update.call_args.kwargs["request_type_id"] == 8
        assert mock_update.call_args.kwargs["name"] == "Training & Certification"

    def test_admin_can_update_description_only(self):
        client = client_as(UserRole.admin)
        updated = make_type(id=8)
        updated["description"] = "New description"
        updated["message"] = "Request type updated successfully."

        with patch("app.api.routes.request_types.update_request_type", return_value=updated):
            response = client.patch(
                "/api/admin/request-types/8",
                json={"description": "New description"},
                headers=AUTH,
            )

        assert response.status_code == 200
        assert response.json()["description"] == "New description"

    @pytest.mark.parametrize("role", [UserRole.requester, UserRole.approver])
    def test_non_admin_cannot_update(self, role):
        client = client_as(role)
        response = client.patch(
            "/api/admin/request-types/8",
            json={"name": "Training & Certification"},
            headers=AUTH,
        )

        assert response.status_code == 403
        assert response.json()["detail"] == "Only admins can manage request types."

    def test_empty_payload_is_rejected_with_422(self):
        """Neither name nor description provided — schema's model_validator
        must reject this before the service ever runs."""
        client = client_as(UserRole.admin)
        with patch("app.api.routes.request_types.update_request_type") as mock_update:
            response = client.patch("/api/admin/request-types/8", json={}, headers=AUTH)

        assert response.status_code == 422
        mock_update.assert_not_called()

    def test_whitespace_only_name_is_rejected_with_422(self):
        client = client_as(UserRole.admin)
        with patch("app.api.routes.request_types.update_request_type") as mock_update:
            response = client.patch(
                "/api/admin/request-types/8", json={"name": "   "}, headers=AUTH
            )

        assert response.status_code == 422
        mock_update.assert_not_called()

    def test_prefix_and_slug_cannot_be_changed_via_this_endpoint(self):
        """Decision K: prefix/slug are immutable. Sending them should simply
        be ignored — UpdateRequestTypeRequest has no such fields."""
        client = client_as(UserRole.admin)
        updated = make_type(id=8, prefix="TC")   # prefix unchanged in the response
        updated["message"] = "Request type updated successfully."

        with patch(
            "app.api.routes.request_types.update_request_type", return_value=updated
        ) as mock_update:
            response = client.patch(
                "/api/admin/request-types/8",
                json={"name": "New Name", "prefix": "XX", "slug": "xx_slug"},
                headers=AUTH,
            )

        assert response.status_code == 200
        # The service was never even told about prefix/slug.
        assert "prefix" not in mock_update.call_args.kwargs
        assert "slug" not in mock_update.call_args.kwargs
        assert response.json()["prefix"] == "TC"

    def test_duplicate_name_returns_409_with_exact_message(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.request_types.update_request_type",
            side_effect=HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This request type name already exists. Please enter a unique name.",
            ),
        ):
            response = client.patch(
                "/api/admin/request-types/8",
                json={"name": "Human Resources"},
                headers=AUTH,
            )

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "This request type name already exists. Please enter a unique name."
        )

    def test_not_found_returns_404(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.request_types.update_request_type",
            side_effect=HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Request type not found."
            ),
        ):
            response = client.patch(
                "/api/admin/request-types/999",
                json={"name": "New Name"},
                headers=AUTH,
            )

        assert response.status_code == 404
        assert response.json()["detail"] == "Request type not found."

    def test_db_failure_returns_500(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.request_types.update_request_type",
            side_effect=RuntimeError("Failed to update request type"),
        ):
            response = client.patch(
                "/api/admin/request-types/8",
                json={"name": "New Name"},
                headers=AUTH,
            )

        assert response.status_code == 500


class TestAdminDeactivate:
    """PATCH /admin/request-types/{id}/deactivate — IT35-308."""

    def test_admin_can_deactivate(self):
        client = client_as(UserRole.admin)
        deactivated = make_type(id=8, is_active=False)
        deactivated["message"] = "Request type deactivated successfully."

        with patch(
            "app.api.routes.request_types.set_request_type_active",
            return_value=deactivated,
        ) as mock_set:
            response = client.patch("/api/admin/request-types/8/deactivate", headers=AUTH)

        assert response.status_code == 200
        assert response.json()["is_active"] is False
        assert response.json()["message"] == "Request type deactivated successfully."
        assert mock_set.call_args.kwargs["is_active"] is False
        assert mock_set.call_args.kwargs["request_type_id"] == 8

    @pytest.mark.parametrize("role", [UserRole.requester, UserRole.approver])
    def test_non_admin_cannot_deactivate(self, role):
        client = client_as(role)
        response = client.patch("/api/admin/request-types/8/deactivate", headers=AUTH)

        assert response.status_code == 403
        assert response.json()["detail"] == "Only admins can manage request types."

    def test_not_found_returns_404(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.request_types.set_request_type_active",
            side_effect=HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Request type not found."
            ),
        ):
            response = client.patch("/api/admin/request-types/999/deactivate", headers=AUTH)

        assert response.status_code == 404

    def test_db_failure_returns_500(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.request_types.set_request_type_active",
            side_effect=RuntimeError("Failed to change request type active status"),
        ):
            response = client.patch("/api/admin/request-types/8/deactivate", headers=AUTH)

        assert response.status_code == 500


class TestAdminActivate:
    """PATCH /admin/request-types/{id}/activate — IT35-308."""

    def test_admin_can_activate(self):
        client = client_as(UserRole.admin)
        activated = make_type(id=8, is_active=True)
        activated["message"] = "Request type activated successfully."

        with patch(
            "app.api.routes.request_types.set_request_type_active",
            return_value=activated,
        ) as mock_set:
            response = client.patch("/api/admin/request-types/8/activate", headers=AUTH)

        assert response.status_code == 200
        assert response.json()["is_active"] is True
        assert response.json()["message"] == "Request type activated successfully."
        assert mock_set.call_args.kwargs["is_active"] is True

    @pytest.mark.parametrize("role", [UserRole.requester, UserRole.approver])
    def test_non_admin_cannot_activate(self, role):
        client = client_as(role)
        response = client.patch("/api/admin/request-types/8/activate", headers=AUTH)

        assert response.status_code == 403

    def test_not_found_returns_404(self):
        client = client_as(UserRole.admin)
        with patch(
            "app.api.routes.request_types.set_request_type_active",
            side_effect=HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Request type not found."
            ),
        ):
            response = client.patch("/api/admin/request-types/999/activate", headers=AUTH)

        assert response.status_code == 404
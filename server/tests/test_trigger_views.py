"""Integration tests for trigger views using TriggerDispatcher."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space
from workflows.models import Workflow, WorkflowNode


@pytest.fixture
def user(db):
    """Create test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def project(db):
    """Create test project."""
    return Space.objects.create(
        name="Test Space",
    )


@pytest.fixture
def workflow(db, project, user):
    """Create active workflow with manual trigger node."""
    # 确保 user 是 project 的成员
    SpaceMembership.objects.get_or_create(
        user=user, space=project, defaults={"role": SpaceRole.MEMBER}
    )
    wf = Workflow.objects.create(
        name="Test Workflow",
        space=project,
        is_active=True,
        trigger_type="manual",
        created_by=user,
    )
    # Create a manual trigger node
    WorkflowNode.objects.create(
        workflow=wf,
        node_type="manual_trigger",
        name="Start",
        config={},
    )
    return wf


@pytest.fixture
def inactive_workflow(db, project, user):
    """Create inactive workflow."""
    # 确保 user 是 project 的成员
    SpaceMembership.objects.get_or_create(
        user=user, space=project, defaults={"role": SpaceRole.MEMBER}
    )
    return Workflow.objects.create(
        name="Inactive Workflow",
        space=project,
        is_active=False,
        trigger_type="manual",
        created_by=user,
    )


@pytest.fixture
def api_client():
    """Return DRF APIClient."""
    return APIClient()


@pytest.fixture
def authenticated_api_client(api_client, user):
    """Return APIClient with JWT authentication."""
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return api_client


class TestWorkflowExecuteView:
    """Tests for WorkflowViewSet.execute (manual trigger)."""

    @pytest.mark.django_db
    def test_execute_inactive_workflow(self, authenticated_api_client, inactive_workflow):
        """Triggering inactive workflow should fail."""
        response = authenticated_api_client.post(
            f"/api/workflows/{inactive_workflow.id}/execute/",
            data={},
            format="json",
        )

        # Workflow is_active check returns 400
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_execute_unauthenticated(self, api_client, workflow):
        """Unauthenticated request should fail."""
        response = api_client.post(
            f"/api/workflows/{workflow.id}/execute/",
            data={},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.django_db
    def test_execute_nonexistent_workflow(self, authenticated_api_client):
        """Executing nonexistent workflow returns 404."""
        import uuid

        fake_id = uuid.uuid4()
        response = authenticated_api_client.post(
            f"/api/workflows/{fake_id}/execute/",
            data={},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestWebhookTriggerView:
    """Tests for WebhookTriggerView."""

    @pytest.mark.django_db
    def test_webhook_no_matching_workflow(self, api_client):
        """Webhook with no matching workflow returns 200 with status."""
        response = api_client.post(
            "/api/webhook/nonexistent-path/",
            data={"event": "test"},
            format="json",
        )

        # No matching workflow config - returns 200 with status
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "no_workflows"


class TestFeishuWebhookView:
    """Tests for FeishuWebhookView."""

    @pytest.mark.django_db
    def test_url_verification_challenge(self, api_client):
        """URL verification should return challenge."""
        response = api_client.post(
            "/api/feishu/webhook/",
            data={
                "type": "url_verification",
                "challenge": "test_challenge_string",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["challenge"] == "test_challenge_string"

    @pytest.mark.django_db
    def test_missing_header_payload(self, api_client):
        """Request without header/payload should be ignored."""
        response = api_client.post(
            "/api/feishu/webhook/",
            data={"some": "data"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "ignored"

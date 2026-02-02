"""Integration tests for trigger views using TriggerDispatcher."""
import pytest
from rest_framework import status
from accounts.models import User
from projects.models import Project
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
 return Project.objects.create(
 name="Test Project",
 key="TEST",
 )
@pytest.fixture
def workflow(db, project, user):
 """Create active workflow with manual trigger node."""
 wf = Workflow.objects.create(
 name="Test Workflow",
 project=project,
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
 return Workflow.objects.create(
 name="Inactive Workflow",
 project=project,
 is_active=False,
 trigger_type="manual",
 created_by=user,
 )
@pytest.fixture
def authenticated_client(client, user):
 """Return client with authenticated user."""
 client.force_login(user)
 return client
class TestWorkflowExecuteView:
 """Tests for WorkflowViewSet.execute (manual trigger)."""
 @pytest.mark.django_db
 def test_execute_inactive_workflow(self, authenticated_client, inactive_workflow):
 """Triggering inactive workflow should fail."""
 response = authenticated_client.post(
 f"/api/workflows/{inactive_workflow.id}/execute/",
 data={},
 content_type="application/json",
 )
 # Workflow is_active check returns 400
 assert response.status_code == status.HTTP_400_BAD_REQUEST
 @pytest.mark.django_db
 def test_execute_unauthenticated(self, client, workflow):
 """Unauthenticated request should fail."""
 response = client.post(
 f"/api/workflows/{workflow.id}/execute/",
 data={},
 content_type="application/json",
 )
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
class TestWebhookTriggerView:
 """Tests for WebhookTriggerView."""
 @pytest.mark.django_db
 def test_webhook_no_matching_workflow(self, client):
 """Webhook with no matching workflow returns 200 with status."""
 response = client.post(
 "/api/webhooks/trigger/nonexistent-path/",
 data={"event": "test"},
 content_type="application/json",
 )
 # No matching workflow config - returns 200 with status
 assert response.status_code == status.HTTP_200_OK
 data = response.json
 assert data["status"] == "no_workflows"
class TestFeishuWebhookView:
 """Tests for FeishuWebhookView."""
 @pytest.mark.django_db
 def test_url_verification_challenge(self, client):
 """URL verification should return challenge."""
 response = client.post(
 "/api/feishu/webhook/",
 data={
 "type": "url_verification",
 "challenge": "test_challenge_string",
 },
 content_type="application/json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.json["challenge"] == "test_challenge_string"
 @pytest.mark.django_db
 def test_missing_header_payload(self, client):
 """Request without header/payload should be ignored."""
 response = client.post(
 "/api/feishu/webhook/",
 data={"some": "data"},
 content_type="application/json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.json["status"] == "ignored"

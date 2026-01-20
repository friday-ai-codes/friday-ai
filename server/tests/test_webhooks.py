"""Tests for webhook endpoints."""
import json
import pytest
from rest_framework import status
@pytest.mark.django_db
class TestFeishuWebhook:
 """Test Feishu webhook endpoint."""
 def test_url_verification_challenge(self, api_client):
 """Test URL verification challenge response."""
 response = api_client.post(
 "/api/webhook/feishu",
 {
 "type": "url_verification",
 "challenge": "test-challenge-token",
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["challenge"] == "test-challenge-token"
 def test_webhook_missing_header_payload(self, api_client):
 """Test webhook with missing header or payload."""
 response = api_client.post(
 "/api/webhook/feishu",
 {"some": "data"},
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ignored"
 def test_webhook_missing_project_key(self, api_client):
 """Test webhook with missing project_key."""
 response = api_client.post(
 "/api/webhook/feishu",
 {
 "header": {"event_type": "WorkitemCreateEvent"},
 "payload": {},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ignored"
 # May contain different reason messages
 assert "reason" in response.data
 def test_webhook_project_not_configured(self, api_client):
 """Test webhook for unconfigured project."""
 response = api_client.post(
 "/api/webhook/feishu",
 {
 "header": {"event_type": "WorkitemCreateEvent"},
 "payload": {"project_key": "unknown-project"},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "ignored"
 assert "未配置" in response.data["reason"]
 def test_webhook_token_verification_failed(self, api_client, project):
 """Test webhook with wrong token."""
 response = api_client.post(
 "/api/webhook/feishu",
 {
 "header": {
 "event_type": "WorkitemCreateEvent",
 "token": "wrong-token",
 },
 "payload": {"project_key": project.feishu_project_key},
 },
 format="json",
 )
 assert response.status_code == status.HTTP_401_UNAUTHORIZED
 def test_webhook_success(self, api_client, project):
 """Test successful webhook processing."""
 response = api_client.post(
 "/api/webhook/feishu",
 {
 "header": {
 "event_type": "WorkitemCreateEvent",
 "token": project.feishu_webhook_token,
 "uuid": "test-event-uuid-001",
 },
 "payload": {
 "project_key": project.feishu_project_key,
 "id": 12345,
 "name": "Test Work Item",
 },
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "accepted"
 assert response.data["event_type"] == "WorkitemCreateEvent"
 def test_webhook_duplicate_event(self, api_client, project):
 """Test duplicate event is ignored."""
 webhook_data = {
 "header": {
 "event_type": "WorkitemCreateEvent",
 "token": project.feishu_webhook_token,
 "uuid": "duplicate-event-uuid",
 },
 "payload": {
 "project_key": project.feishu_project_key,
 "id": 12345,
 },
 }
 # First request
 response1 = api_client.post("/api/webhook/feishu", webhook_data, format="json")
 assert response1.status_code == status.HTTP_200_OK
 assert response1.data["status"] == "accepted"
 # Duplicate request
 response2 = api_client.post("/api/webhook/feishu", webhook_data, format="json")
 assert response2.status_code == status.HTTP_200_OK
 assert response2.data["status"] == "duplicate"
@pytest.mark.django_db
class TestGitHubWebhook:
 """Test GitHub webhook endpoint."""
 def test_github_webhook_pr_merged(self, api_client):
 """Test GitHub PR merged webhook."""
 response = api_client.post(
 "/api/webhook/github",
 {
 "action": "closed",
 "pull_request": {
 "merged": True,
 "head": {"ref": "feature/test-branch"},
 "html_url": "https://github.com/test/repo/pull/1",
 },
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["status"] == "accepted"
 def test_github_webhook_pr_closed_not_merged(self, api_client):
 """Test GitHub PR closed but not merged."""
 response = api_client.post(
 "/api/webhook/github",
 {
 "action": "closed",
 "pull_request": {
 "merged": False,
 "head": {"ref": "feature/test-branch"},
 },
 },
 format="json",
 )
 assert response.status_code == status.HTTP_200_OK
 def test_github_webhook_invalid_json(self, api_client):
 """Test GitHub webhook with invalid JSON."""
 response = api_client.post(
 "/api/webhook/github",
 "invalid json",
 content_type="application/json",
 )
 assert response.status_code == status.HTTP_400_BAD_REQUEST

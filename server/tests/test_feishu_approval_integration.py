"""Integration tests for Feishu approval handler integration with webhook view."""
import json
from unittest.mock import AsyncMock, patch
import pytest
from feishu.models import TriggerLog
@pytest.fixture
def webhook_url:
 """Feishu webhook URL."""
 return "/api/feishu/webhook"
def create_comment_payload(project, comment: str, work_item_id: str = "12345"):
 """Create a WorkitemCommentEvent webhook payload."""
 return {
 "header": {
 "uuid": f"test-uuid-{work_item_id}-{hash(comment) % 10000}",
 "event_type": "WorkitemCommentEvent",
 "token": project.feishu_webhook_token,
 },
 "payload": {
 "id": work_item_id,
 "project_key": project.feishu_project_key,
 "comment": comment,
 "work_item_type_key": "story",
 },
 }
@pytest.mark.django_db
class TestFeishuApprovalIntegration:
 """Tests for Feishu approval handler integration with webhook view."""
 def test_comment_with_approval_keyword_calls_handler(self, api_client, project, webhook_url):
 """Test that LGTM keyword triggers handler with approved=True."""
 payload = create_comment_payload(project, "LGTM, looks good to me!")
 with patch("feishu.approval.FeishuApprovalHandler") as MockHandler:
 mock_handler = MockHandler.return_value
 mock_handler.on_approval_comment = AsyncMock(return_value=True)
 response = api_client.post(
 webhook_url,
 data=json.dumps(payload),
 content_type="application/json",
 )
 assert response.status_code == 200
 mock_handler.on_approval_comment.assert_called_once
 call_kwargs = mock_handler.on_approval_comment.call_args.kwargs
 assert call_kwargs["work_item_id"] == "12345"
 assert call_kwargs["approved"] is True
 assert "LGTM" in call_kwargs["comment"]
 assert call_kwargs["approver"] is None
 def test_comment_with_rejection_keyword_calls_handler(self, api_client, project, webhook_url):
 """Test that rejection keyword triggers handler with approved=False."""
 payload = create_comment_payload(project, "驳回, needs more work")
 with patch("feishu.approval.FeishuApprovalHandler") as MockHandler:
 mock_handler = MockHandler.return_value
 mock_handler.on_approval_comment = AsyncMock(return_value=True)
 response = api_client.post(
 webhook_url,
 data=json.dumps(payload),
 content_type="application/json",
 )
 assert response.status_code == 200
 mock_handler.on_approval_comment.assert_called_once
 call_kwargs = mock_handler.on_approval_comment.call_args.kwargs
 assert call_kwargs["work_item_id"] == "12345"
 assert call_kwargs["approved"] is False
 def test_comment_with_both_keywords_prioritizes_rejection(
 self, api_client, project, webhook_url
 ):
 """Test that when both approval and rejection keywords present, rejection takes priority."""
 # Comment contains both "通过" (approval) and "驳回" (rejection)
 payload = create_comment_payload(project, "通过? No, 驳回 this request")
 with patch("feishu.approval.FeishuApprovalHandler") as MockHandler:
 mock_handler = MockHandler.return_value
 mock_handler.on_approval_comment = AsyncMock(return_value=True)
 response = api_client.post(
 webhook_url,
 data=json.dumps(payload),
 content_type="application/json",
 )
 assert response.status_code == 200
 mock_handler.on_approval_comment.assert_called_once
 call_kwargs = mock_handler.on_approval_comment.call_args.kwargs
 assert call_kwargs["approved"] is False # Rejection takes priority
 def test_comment_without_keywords_does_not_call_handler(
 self, api_client, project, webhook_url
 ):
 """Test that neutral comment does not trigger handler."""
 payload = create_comment_payload(project, "Just a regular comment, nothing special")
 with patch("feishu.approval.FeishuApprovalHandler") as MockHandler:
 mock_handler = MockHandler.return_value
 mock_handler.on_approval_comment = AsyncMock(return_value=True)
 response = api_client.post(
 webhook_url,
 data=json.dumps(payload),
 content_type="application/json",
 )
 assert response.status_code == 200
 mock_handler.on_approval_comment.assert_not_called
 def test_handler_error_does_not_crash_webhook(self, api_client, project, webhook_url):
 """Test that handler exception is caught and webhook returns 200."""
 payload = create_comment_payload(project, "LGTM, approved!")
 with patch("feishu.approval.FeishuApprovalHandler") as MockHandler:
 mock_handler = MockHandler.return_value
 mock_handler.on_approval_comment = AsyncMock(
 side_effect=Exception("Database connection failed")
 )
 response = api_client.post(
 webhook_url,
 data=json.dumps(payload),
 content_type="application/json",
 )
 # Webhook should still return 200 even if handler fails
 assert response.status_code == 200
 mock_handler.on_approval_comment.assert_called_once
 # Verify TriggerLog was created
 assert TriggerLog.objects.filter(work_item_id="12345").exists
 def test_approval_with_chinese_keyword(self, api_client, project, webhook_url):
 """Test that Chinese approval keywords work correctly."""
 payload = create_comment_payload(project, "批准, 可以上线了", work_item_id="67890")
 with patch("feishu.approval.FeishuApprovalHandler") as MockHandler:
 mock_handler = MockHandler.return_value
 mock_handler.on_approval_comment = AsyncMock(return_value=True)
 response = api_client.post(
 webhook_url,
 data=json.dumps(payload),
 content_type="application/json",
 )
 assert response.status_code == 200
 mock_handler.on_approval_comment.assert_called_once
 call_kwargs = mock_handler.on_approval_comment.call_args.kwargs
 assert call_kwargs["approved"] is True
 def test_rejection_with_chinese_keyword(self, api_client, project, webhook_url):
 """Test that Chinese rejection keywords work correctly."""
 payload = create_comment_payload(project, "需要修改, 请重新提交", work_item_id="11111")
 with patch("feishu.approval.FeishuApprovalHandler") as MockHandler:
 mock_handler = MockHandler.return_value
 mock_handler.on_approval_comment = AsyncMock(return_value=True)
 response = api_client.post(
 webhook_url,
 data=json.dumps(payload),
 content_type="application/json",
 )
 assert response.status_code == 200
 mock_handler.on_approval_comment.assert_called_once
 call_kwargs = mock_handler.on_approval_comment.call_args.kwargs
 assert call_kwargs["approved"] is False

"""Tests for callback module."""
import pytest
from integrations import CallbackClient
class TestCallbackClient:
 """CallbackClient 测试。"""
 @pytest.mark.asyncio
 async def test_callback_disabled_mode(self, mock_config):
 """测试回调禁用模式（独立运行）。"""
 mock_config.callback_url = ""
 mock_config.callback_token = ""
 client = CallbackClient(mock_config)
 # 应该启用独立模式
 assert client.enabled is False
 # 调用应该成功（仅记录日志）
 result = await client.report_status("started", "Test message")
 assert result is True
 @pytest.mark.asyncio
 async def test_callback_enabled_mode(self, mock_config):
 """测试回调启用模式。"""
 mock_config.callback_url = "http://localhost:8000/api"
 mock_config.callback_token = "test-token"
 client = CallbackClient(mock_config)
 # 应该启用回调模式
 assert client.enabled is True
 assert client.base_url == "http://localhost:8000/api"
 assert "Authorization" in client.headers
 @pytest.mark.asyncio
 async def test_report_started(self, mock_config):
 """测试报告启动状态。"""
 mock_config.callback_url = ""
 client = CallbackClient(mock_config)
 result = await client.report_started
 assert result is True
 @pytest.mark.asyncio
 async def test_report_completed_coding_plan(self, mock_config):
 """测试通过 report_completed 报告 coding_plan 结果（替代已删除的 report_plan_ready）。"""
 mock_config.callback_url = ""
 client = CallbackClient(mock_config)
 result = await client.report_completed(
 output={"text": "## Test Plan\n\n1. Step 1\n2. Step 2", "task_type": "coding_plan"},
 result_type="text",
 )
 assert result is True
 @pytest.mark.asyncio
 async def test_report_execution_complete(self, mock_config):
 """测试报告执行完成。"""
 mock_config.callback_url = ""
 client = CallbackClient(mock_config)
 result = await client.report_execution_complete(
 branch_name="friday/task-001",
 commit_sha="abc12345",
 diff_summary="2 files changed",
 )
 assert result is True
 @pytest.mark.asyncio
 async def test_report_error(self, mock_config):
 """测试报告错误。"""
 mock_config.callback_url = ""
 client = CallbackClient(mock_config)
 result = await client.report_error("Test error", "execution")
 assert result is True
 @pytest.mark.asyncio
 async def test_report_git_ready(self, mock_config):
 """测试报告 Git 就绪。"""
 mock_config.callback_url = ""
 client = CallbackClient(mock_config)
 result = await client.report_git_ready("friday/task-001")
 assert result is True

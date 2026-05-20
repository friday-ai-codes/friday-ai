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
class TestRunExecuteModeReportsCompleted:
 """Phase：_run_execute_mode 末尾发 completed 帧携带 git 元数据。"""
 @pytest.mark.asyncio
 async def test_run_execute_mode_reports_completed_with_git_metadata(self):
 """_run_execute_mode 成功路径应调 report_completed 一次，output 含 6 个字段。"""
 from unittest.mock import AsyncMock, MagicMock
 from core.runner import TaskRunner
 config = MagicMock
 config.task_type = "coding"
 config.task_mode = "execute"
 config.task_id = "exec-001"
 config.task_title = "用户认证"
 config.task_description = "加 JWT 认证"
 config.callback_url = ""
 config.callback_token = ""
 runner = TaskRunner(config)
 runner.git_ops = AsyncMock
 runner.git_ops.commit_changes = AsyncMock(return_value="deadbeef")
 runner.git_ops.push_branch_with_retry = AsyncMock
 runner.git_ops.get_modified_files = AsyncMock(return_value=["auth.py", "models.py"])
 runner.git_ops.get_diff_summary = AsyncMock(return_value="2 files changed, 100 insertions(+)")
 runner.callback = AsyncMock
 runner.claude = MagicMock
 runner.claude.get_session_summary = AsyncMock(return_value="plan summary")
 runner.claude.run_execute_mode = AsyncMock(return_value={"success": True})
 log = MagicMock
 result = await runner._run_execute_mode(log, "friday/exec-test")
 assert result == 0
 # 调用序列断言：progress 帧（execution_complete / push_complete /
 # suggested_commit_message）保留 + 末尾新增 completed 帧
 runner.callback.report_execution_complete.assert_called_once
 runner.callback.report_push_complete.assert_called_once
 runner.callback.report_suggested_commit_message.assert_called_once
 runner.callback.report_completed.assert_called_once
 completed_call = runner.callback.report_completed.call_args
 output = completed_call.kwargs["output"]
 assert output["branch_name"] == "friday/exec-test"
 assert output["commit_sha"] == "deadbeef"
 assert output["suggested_commit_message"] != ""
 assert "modified_files" in output and isinstance(output["modified_files"], list)
 assert output["modified_files"] == ["auth.py", "models.py"]
 assert output["task_type"] == "coding"
 @pytest.mark.asyncio
 async def test_run_execute_mode_no_changes_skips_completed(self):
 """无改动场景（commit_sha 为 falsy）应走 no_changes 分支，不发 completed 帧。"""
 from unittest.mock import AsyncMock, MagicMock
 from core.runner import TaskRunner
 config = MagicMock
 config.task_type = "coding"
 config.task_mode = "execute"
 config.task_id = "nochange-001"
 config.callback_url = ""
 config.callback_token = ""
 runner = TaskRunner(config)
 runner.git_ops = AsyncMock
 runner.git_ops.commit_changes = AsyncMock(return_value="") # falsy => no changes
 runner.callback = AsyncMock
 runner.claude = MagicMock
 runner.claude.get_session_summary = AsyncMock(return_value="plan")
 runner.claude.run_execute_mode = AsyncMock(return_value={"success": True})
 log = MagicMock
 result = await runner._run_execute_mode(log, "friday/no-change")
 assert result == 0
 runner.callback.report_completed.assert_not_called
 runner.callback.report_status.assert_called

"""Phase Plan: 回调协议迁移测试。
覆盖 的 3 个 behavior:
- _run_plan_mode (容器模式) 使用 report_completed 替代 report_plan_ready
- _run_plan_mode (CLI 模式) 使用 report_completed 替代 report_plan_ready
- report_completed payload 包含 task_type="coding_plan"
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from core.config import TaskConfig
from core.runner import TaskRunner
from integrations.callback import CallbackClient
class TestRunnerPlanModeCallback:
 """容器模式 _run_plan_mode 回调迁移测试。"""
 @pytest.mark.asyncio
 async def test_plan_mode_uses_report_completed(self):
 """_run_plan_mode 调用 report_completed 而非 report_plan_ready。"""
 config = TaskConfig(
 task_id="test-plan-migrate",
 task_description="test plan",
 git_repo_url="https://test.com/repo.git",
 task_mode="plan",
 )
 runner = TaskRunner(config)
 runner.claude = MagicMock
 runner.claude.run_plan_mode = AsyncMock(
 return_value={"success": True, "output": "## Plan\n1. Do X"}
 )
 runner.callback = MagicMock(spec=CallbackClient)
 runner.callback.report_completed = AsyncMock(return_value=True)
 log = MagicMock
 result = await runner._run_plan_mode(log, "main")
 assert result == 0
 runner.callback.report_completed.assert_called_once_with(
 output={"text": "## Plan\n1. Do X", "task_type": "coding_plan"},
 result_type="text",
 )
 # 确认 report_plan_ready 未被调用
 assert not hasattr(runner.callback, 'report_plan_ready') or \
 not runner.callback.report_plan_ready.called
 @pytest.mark.asyncio
 async def test_plan_mode_report_completed_payload(self):
 """report_completed payload 的 task_type 为 coding_plan（与 repo_summary 区分）。"""
 config = TaskConfig(
 task_id="test-payload",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 callback_url="http://localhost:8000",
 callback_token="tok-test",
 )
 client = CallbackClient(config)
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_response = MagicMock
 mock_response.raise_for_status = MagicMock
 mock_client.post = AsyncMock(return_value=mock_response)
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_cls.return_value = mock_client
 await client.report_completed(
 output={"text": "plan text", "task_type": "coding_plan"},
 result_type="text",
 )
 call_kwargs = mock_client.post.call_args
 payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
 assert payload["payload"]["output"]["task_type"] == "coding_plan"
class TestCLIPlanModeCallback:
 """CLI 模式 _run_plan_mode 回调迁移测试。"""
 @pytest.mark.asyncio
 async def test_cli_plan_mode_uses_report_completed(self):
 """CLI _run_plan_mode 调用 callback.report_completed 而非 report_plan_ready。"""
 from cli.commands import _run_plan_mode
 mock_claude = MagicMock
 mock_claude.run_plan_mode = AsyncMock(
 return_value={"success": True, "output": "## CLI Plan"}
 )
 mock_callback = MagicMock(spec=CallbackClient)
 mock_callback.report_completed = AsyncMock(return_value=True)
 mock_log = MagicMock
 result = await _run_plan_mode(mock_claude, mock_callback, mock_log)
 assert result == 0
 mock_callback.report_completed.assert_called_once_with(
 output={"text": "## CLI Plan", "task_type": "coding_plan"},
 result_type="text",
 )

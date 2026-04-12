"""Phase Plan: 容器侧 repo_summary 模式测试。
覆盖 4 个 behavior:
- Test 1: _check_explore_guard 在 task_mode="repo_summary" 时抛出 ExploreModeForbiddenError
- Test 2: git-wrapper.sh 在 FRIDAY_TASK_MODE=repo_summary 时将 mode 别名为 explore
- Test 3: CallbackClient.report_completed 构建正确 payload
- Test 4: CallbackClient.report_failed 构建正确 payload
"""
import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from core.config import TaskConfig
from core.exceptions import ExploreModeForbiddenError
from git_ops.operations import GitOperations
from integrations.callback import CallbackClient
class TestExploreGuardRepoSummary:
 """Test 1: _check_explore_guard 在 task_mode='repo_summary' 时拦截写操作。"""
 def test_check_explore_guard_blocks_repo_summary_mode(self):
 """repo_summary 模式下 _check_explore_guard 抛出 ExploreModeForbiddenError。"""
 config = TaskConfig(
 task_id="test-rs-001",
 task_description="test repo summary",
 git_repo_url="https://test.com/repo.git",
 task_mode="repo_summary",
 )
 ops = GitOperations(config)
 with pytest.raises(ExploreModeForbiddenError):
 ops._check_explore_guard("commit")
 @pytest.mark.asyncio
 async def test_commit_changes_blocked_in_repo_summary(self):
 """repo_summary 模式下调用 commit_changes 抛出 ExploreModeForbiddenError。"""
 config = TaskConfig(
 task_id="test-rs-002",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 task_mode="repo_summary",
 )
 ops = GitOperations(config)
 with pytest.raises(ExploreModeForbiddenError) as exc_info:
 await ops.commit_changes("should be blocked")
 assert exc_info.value.operation == "commit_changes"
 @pytest.mark.asyncio
 async def test_push_branch_blocked_in_repo_summary(self):
 """repo_summary 模式下调用 push_branch 抛出 ExploreModeForbiddenError。"""
 config = TaskConfig(
 task_id="test-rs-003",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 task_mode="repo_summary",
 )
 ops = GitOperations(config)
 with pytest.raises(ExploreModeForbiddenError) as exc_info:
 await ops.push_branch("main")
 assert exc_info.value.operation == "push_branch"
 @pytest.mark.asyncio
 async def test_setup_task_branch_blocked_in_repo_summary(self):
 """repo_summary 模式下调用 setup_task_branch 抛出 ExploreModeForbiddenError。"""
 config = TaskConfig(
 task_id="test-rs-004",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 task_mode="repo_summary",
 )
 ops = GitOperations(config)
 with pytest.raises(ExploreModeForbiddenError) as exc_info:
 await ops.setup_task_branch(None, "test-task")
 assert exc_info.value.operation == "setup_task_branch"
class TestGitWrapperRepoSummary:
 """Test 2: git-wrapper.sh 在 FRIDAY_TASK_MODE=repo_summary 时别名为 explore。"""
 def test_git_wrapper_aliases_repo_summary_to_explore(self):
 """git-wrapper.sh 在 FRIDAY_TASK_MODE=repo_summary 时将 mode 设置为 explore。"""
 # 用 bash 脚本片段测试：读取 git-wrapper.sh 前几行的别名逻辑
 script_path = "/workspace/Desktop/friday-ai/.claude/worktrees/agent-a1174274/task/git_ops/git-wrapper.sh"
 result = subprocess.run(
 [
 "bash",
 "-c",
 f'FRIDAY_TASK_MODE=repo_summary; source <(head -20 "{script_path}" | grep -v "^exec" | grep -v "^REAL_GIT"); echo "$FRIDAY_TASK_MODE"',
 ],
 capture_output=True,
 text=True,
 timeout=5,
 )
 assert result.stdout.strip == "explore", (
 f"Expected FRIDAY_TASK_MODE to be 'explore' after sourcing, got: '{result.stdout.strip}'"
 )
class TestCallbackReportCompleted:
 """Test 3: CallbackClient.report_completed 构建正确的 payload。"""
 @pytest.mark.asyncio
 async def test_report_completed_payload_format(self):
 """report_completed 发送 {type: 'completed', session_id, token, payload: {result_type, output}}。"""
 config = TaskConfig(
 task_id="test-session-123",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 callback_url="http://localhost:8000",
 callback_token="tok-secret-456",
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
 result = await client.report_completed(
 output={"text": "hello world", "task_type": "repo_summary"}
 )
 assert result is True
 call_kwargs = mock_client.post.call_args
 payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
 assert payload["type"] == "completed"
 assert payload["session_id"] == "test-session-123"
 assert payload["token"] == "tok-secret-456"
 assert payload["payload"]["result_type"] == "text"
 assert payload["payload"]["output"]["text"] == "hello world"
 @pytest.mark.asyncio
 async def test_report_completed_url_path(self):
 """report_completed POST 到 /api/containers/callback/ 路径。"""
 config = TaskConfig(
 task_id="test-url",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 callback_url="http://localhost:8000",
 callback_token="tok",
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
 await client.report_completed(output={"text": "test"})
 call_args = mock_client.post.call_args
 url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
 assert url == "http://localhost:8000/api/containers/callback/"
 @pytest.mark.asyncio
 async def test_report_completed_standalone_mode(self):
 """report_completed 在 standalone 模式下（无 callback_url）返回 True 不发送 HTTP。"""
 config = TaskConfig(
 task_id="test-standalone",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 callback_url="",
 callback_token="",
 )
 client = CallbackClient(config)
 with patch("httpx.AsyncClient") as mock_client_cls:
 result = await client.report_completed(output={"text": "test"})
 assert result is True
 mock_client_cls.assert_not_called
class TestCallbackReportFailed:
 """Test 4: CallbackClient.report_failed 构建正确的 payload。"""
 @pytest.mark.asyncio
 async def test_report_failed_payload_format(self):
 """report_failed 发送 {type: 'failed', session_id, token, payload: {error}}。"""
 config = TaskConfig(
 task_id="test-fail-session",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 callback_url="http://localhost:8000",
 callback_token="tok-fail-789",
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
 result = await client.report_failed(error="something went wrong")
 assert result is True
 call_kwargs = mock_client.post.call_args
 payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
 assert payload["type"] == "failed"
 assert payload["session_id"] == "test-fail-session"
 assert payload["token"] == "tok-fail-789"
 assert payload["payload"]["error"] == "something went wrong"
 @pytest.mark.asyncio
 async def test_report_failed_url_path(self):
 """report_failed POST 到 /api/containers/callback/ 路径。"""
 config = TaskConfig(
 task_id="test-fail-url",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 callback_url="http://localhost:8000",
 callback_token="tok",
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
 await client.report_failed(error="test error")
 call_args = mock_client.post.call_args
 url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
 assert url == "http://localhost:8000/api/containers/callback/"
 @pytest.mark.asyncio
 async def test_report_failed_http_error_returns_false(self):
 """report_failed 在 HTTP 错误时返回 False。"""
 import httpx
 config = TaskConfig(
 task_id="test-fail-err",
 task_description="test",
 git_repo_url="https://test.com/repo.git",
 callback_url="http://localhost:8000",
 callback_token="tok",
 )
 client = CallbackClient(config)
 with patch("httpx.AsyncClient") as mock_client_cls:
 mock_client = AsyncMock
 mock_client.post = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
 mock_client.__aenter__ = AsyncMock(return_value=mock_client)
 mock_client.__aexit__ = AsyncMock(return_value=None)
 mock_client_cls.return_value = mock_client
 result = await client.report_failed(error="test")
 assert result is False

"""Phase 测试: TaskConfig 字段 + TaskRunner Phase/2 + callback 扩展。
TDD RED 阶段：测试 TaskConfig 新增字段、TaskRunner coding_commit 路由、
_run_commit_mode、_generate_suggested_commit_message、callback 扩展。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from core.config import TaskConfig
from integrations import CallbackClient
class TestTaskConfigNewFields:
 """TaskConfig 新增 task_type 和 commit_message 字段测试。"""
 def test_task_type_default_coding(self, temp_session_dir):
 """task_type 默认值应为 'coding'。"""
 config = TaskConfig(
 task_id="test-001",
 task_description="Test",
 git_repo_url="https://example.com/repo.git",
 session_dir=temp_session_dir,
 )
 assert config.task_type == "coding"
 def test_task_type_coding_commit(self, temp_session_dir):
 """task_type 可设为 'coding_commit'。"""
 config = TaskConfig(
 task_id="test-001",
 task_description="Test",
 git_repo_url="https://example.com/repo.git",
 task_type="coding_commit",
 session_dir=temp_session_dir,
 )
 assert config.task_type == "coding_commit"
 def test_commit_message_default_empty(self, temp_session_dir):
 """commit_message 默认值应为空字符串。"""
 config = TaskConfig(
 task_id="test-001",
 task_description="Test",
 git_repo_url="https://example.com/repo.git",
 session_dir=temp_session_dir,
 )
 assert config.commit_message == ""
 def test_commit_message_from_param(self, temp_session_dir):
 """commit_message 可从参数传入。"""
 config = TaskConfig(
 task_id="test-001",
 task_description="Test",
 git_repo_url="https://example.com/repo.git",
 commit_message="feat: implement feature X",
 session_dir=temp_session_dir,
 )
 assert config.commit_message == "feat: implement feature X"
 def test_commit_message_from_env(self, temp_session_dir, monkeypatch):
 """commit_message 可从 FRIDAY_TASK_COMMIT_MESSAGE 环境变量读取。"""
 monkeypatch.setenv("FRIDAY_TASK_COMMIT_MESSAGE", "fix: resolve bug #123")
 monkeypatch.setenv("FRIDAY_TASK_TASK_ID", "env-test")
 monkeypatch.setenv("FRIDAY_TASK_TASK_DESCRIPTION", "env test desc")
 monkeypatch.setenv("FRIDAY_TASK_GIT_REPO_URL", "https://example.com/repo.git")
 monkeypatch.setenv("FRIDAY_TASK_SESSION_DIR", temp_session_dir)
 config = TaskConfig
 assert config.commit_message == "fix: resolve bug #123"
 def test_task_type_from_env(self, temp_session_dir, monkeypatch):
 """task_type 可从 FRIDAY_TASK_TASK_TYPE 环境变量读取。"""
 monkeypatch.setenv("FRIDAY_TASK_TASK_TYPE", "coding_commit")
 monkeypatch.setenv("FRIDAY_TASK_TASK_ID", "env-test")
 monkeypatch.setenv("FRIDAY_TASK_TASK_DESCRIPTION", "env test desc")
 monkeypatch.setenv("FRIDAY_TASK_GIT_REPO_URL", "https://example.com/repo.git")
 monkeypatch.setenv("FRIDAY_TASK_SESSION_DIR", temp_session_dir)
 config = TaskConfig
 assert config.task_type == "coding_commit"
class TestCallbackSuggestedCommitMessage:
 """CallbackClient.report_suggested_commit_message 测试。"""
 @pytest.mark.asyncio
 async def test_report_suggested_commit_message_exists(self, mock_config):
 """report_suggested_commit_message 方法应存在。"""
 mock_config.callback_url = ""
 client = CallbackClient(mock_config)
 assert hasattr(client, "report_suggested_commit_message")
 @pytest.mark.asyncio
 async def test_report_suggested_commit_message_standalone(self, mock_config):
 """standalone 模式下 report_suggested_commit_message 应成功。"""
 mock_config.callback_url = ""
 client = CallbackClient(mock_config)
 result = await client.report_suggested_commit_message("feat: add login feature")
 assert result is True
 @pytest.mark.asyncio
 async def test_report_suggested_commit_message_calls_report_status(self, mock_config):
 """report_suggested_commit_message 应通过 report_status 上报。"""
 mock_config.callback_url = ""
 client = CallbackClient(mock_config)
 # 监控 report_status 调用
 original_report_status = client.report_status
 call_args_list =
 async def capture_report_status(*args, **kwargs):
 call_args_list.append((args, kwargs))
 return await original_report_status(*args, **kwargs)
 client.report_status = capture_report_status
 await client.report_suggested_commit_message("feat: test message")
 # 应调用 report_status
 assert len(call_args_list) == 1
 _, kwargs = call_args_list[0]
 assert kwargs.get("status") == "progress"
 details = kwargs.get("details", {})
 assert "suggested_commit_message" in details
 assert details["suggested_commit_message"] == "feat: test message"
class TestTaskRunnerRouting:
 """TaskRunner._run_execute_mode 路由测试。"""
 @pytest.mark.asyncio
 async def test_coding_commit_routes_to_commit_mode(self):
 """task_type='coding_commit' 应路由到 _run_commit_mode。"""
 from core.runner import TaskRunner
 config = MagicMock
 config.task_type = "coding_commit"
 config.task_mode = "execute"
 config.commit_message = "feat: test"
 config.task_id = "test-001"
 config.callback_url = ""
 config.callback_token = ""
 config.git_timeout = 300
 runner = TaskRunner(config)
 runner.git_ops = MagicMock
 runner.callback = AsyncMock
 runner.claude = MagicMock
 # Mock _run_commit_mode 来验证路由
 runner._run_commit_mode = AsyncMock(return_value=0)
 log = MagicMock
 result = await runner._run_execute_mode(log, "friday/test-branch")
 runner._run_commit_mode.assert_called_once_with(log, "friday/test-branch")
 assert result == 0
 @pytest.mark.asyncio
 async def test_coding_default_runs_full_execute(self):
 """task_type='coding'（默认）应执行完整 execute 流程。"""
 from core.runner import TaskRunner
 config = MagicMock
 config.task_type = "coding"
 config.task_mode = "execute"
 config.task_id = "test-001"
 config.task_title = "Test Task"
 config.task_description = "Test desc"
 config.callback_url = ""
 config.callback_token = ""
 runner = TaskRunner(config)
 runner.git_ops = AsyncMock
 runner.git_ops.commit_changes = AsyncMock(return_value="abc123def")
 runner.git_ops.push_branch_with_retry = AsyncMock
 runner.git_ops.get_modified_files = AsyncMock(return_value=["file.py"])
 runner.git_ops.get_diff_summary = AsyncMock(return_value="1 file changed")
 runner.callback = AsyncMock
 runner.claude = MagicMock
 runner.claude.get_session_summary = AsyncMock(return_value="plan summary")
 runner.claude.run_execute_mode = AsyncMock(return_value={"success": True})
 log = MagicMock
 result = await runner._run_execute_mode(log, "friday/test-branch")
 assert result == 0
 # 确保调用了 report_suggested_commit_message（Phase 回传）
 runner.callback.report_suggested_commit_message.assert_called_once
class TestRunCommitMode:
 """TaskRunner._run_commit_mode 测试。"""
 @pytest.mark.asyncio
 async def test_commit_mode_missing_message_returns_error(self):
 """commit_message 为空时应报错返回 1。"""
 from core.runner import TaskRunner
 config = MagicMock
 config.task_type = "coding_commit"
 config.commit_message = ""
 config.task_id = "test-001"
 config.callback_url = ""
 config.callback_token = ""
 runner = TaskRunner(config)
 runner.git_ops = MagicMock
 runner.callback = AsyncMock
 log = MagicMock
 result = await runner._run_commit_mode(log, "friday/test-branch")
 assert result == 1
 runner.callback.report_error.assert_called_once
 @pytest.mark.asyncio
 async def test_commit_mode_amend_and_push(self):
 """_run_commit_mode 应执行 git commit --amend + push --force-with-lease。"""
 from core.runner import TaskRunner
 config = MagicMock
 config.task_type = "coding_commit"
 config.commit_message = "feat: user confirmed message"
 config.task_id = "test-001"
 config.callback_url = ""
 config.callback_token = ""
 config.git_timeout = 300
 runner = TaskRunner(config)
 runner.git_ops = AsyncMock
 runner.git_ops.get_modified_files = AsyncMock(return_value=["file.py"])
 runner.git_ops.get_diff_summary = AsyncMock(return_value="1 file changed")
 runner.callback = AsyncMock
 # Mock subprocess for git commands
 mock_process = AsyncMock
 mock_process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
 mock_process.returncode = 0
 with patch("asyncio.create_subprocess_exec", return_value=mock_process):
 log = MagicMock
 result = await runner._run_commit_mode(log, "friday/test-branch")
 assert result == 0
 runner.callback.report_push_complete.assert_called_once
 runner.callback.report_execution_complete.assert_called_once
class TestGenerateSuggestedCommitMessage:
 """_generate_suggested_commit_message 测试。"""
 def test_generate_with_title_and_description(self):
 """使用 title 和 description 生成 suggested commit message。"""
 from core.runner import TaskRunner
 config = MagicMock
 runner = TaskRunner(config)
 result = runner._generate_suggested_commit_message(
 diff_summary="2 files changed, 50 insertions(+)",
 task_title="Add user login",
 task_description="Implement JWT auth for user login",
 )
 assert "Add user login" in result
 assert "feat:" in result
 def test_generate_without_title(self):
 """没有 title 时使用默认前缀。"""
 from core.runner import TaskRunner
 config = MagicMock
 runner = TaskRunner(config)
 result = runner._generate_suggested_commit_message(
 diff_summary="1 file changed",
 task_title="",
 task_description="",
 )
 assert "feat:" in result
 assert "implement changes" in result
 def test_generate_truncates_long_diff(self):
 """超长 diff summary 应被截断。"""
 from core.runner import TaskRunner
 config = MagicMock
 runner = TaskRunner(config)
 long_diff = "a" * 1000
 result = runner._generate_suggested_commit_message(
 diff_summary=long_diff,
 task_title="Test",
 task_description="Desc",
 )
 # diff 部分应被截断到 500 字符以内
 assert len(result) < 1000

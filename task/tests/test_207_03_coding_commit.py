"""implementation 测试: TaskConfig 字段 + TaskRunner Phase/2 + callback 扩展。

TDD RED 阶段：测试 TaskConfig 新增字段、TaskRunner coding_commit 路由、
_run_commit_mode、_generate_suggested_commit_message、callback 扩展。
"""

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
        config = TaskConfig()
        assert config.commit_message == "fix: resolve bug #123"

    def test_task_type_from_env(self, temp_session_dir, monkeypatch):
        """task_type 可从 FRIDAY_TASK_TASK_TYPE 环境变量读取。"""
        monkeypatch.setenv("FRIDAY_TASK_TASK_TYPE", "coding_commit")
        monkeypatch.setenv("FRIDAY_TASK_TASK_ID", "env-test")
        monkeypatch.setenv("FRIDAY_TASK_TASK_DESCRIPTION", "env test desc")
        monkeypatch.setenv("FRIDAY_TASK_GIT_REPO_URL", "https://example.com/repo.git")
        monkeypatch.setenv("FRIDAY_TASK_SESSION_DIR", temp_session_dir)
        config = TaskConfig()
        assert config.task_type == "coding_commit"

    def test_legacy_coding_task_mode_normalized_to_execute(
        self, temp_session_dir, monkeypatch
    ):
        """旧 Go Runner 把 task_type 注入到 task_mode 时，容器仍应进入 execute 流程。"""
        monkeypatch.setenv("FRIDAY_TASK_TASK_MODE", "coding")
        monkeypatch.setenv("FRIDAY_TASK_TASK_ID", "legacy-coding")
        monkeypatch.setenv("FRIDAY_TASK_TASK_DESCRIPTION", "legacy coding desc")
        monkeypatch.setenv("FRIDAY_TASK_GIT_REPO_URL", "https://example.com/repo.git")
        monkeypatch.setenv("FRIDAY_TASK_SESSION_DIR", temp_session_dir)

        config = TaskConfig()

        assert config.task_mode == "execute"
        assert config.task_type == "coding"

    def test_legacy_coding_commit_task_mode_normalized_to_execute(
        self, temp_session_dir, monkeypatch
    ):
        """旧 Go Runner 传 task_mode=coding_commit 时应执行 commit 阶段。"""
        monkeypatch.setenv("FRIDAY_TASK_TASK_MODE", "coding_commit")
        monkeypatch.setenv("FRIDAY_TASK_TASK_ID", "legacy-commit")
        monkeypatch.setenv("FRIDAY_TASK_TASK_DESCRIPTION", "legacy commit desc")
        monkeypatch.setenv("FRIDAY_TASK_GIT_REPO_URL", "https://example.com/repo.git")
        monkeypatch.setenv("FRIDAY_TASK_SESSION_DIR", temp_session_dir)

        config = TaskConfig()

        assert config.task_mode == "execute"
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
        call_args_list = []

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

        config = MagicMock()
        config.task_type = "coding_commit"
        config.task_mode = "execute"
        config.commit_message = "feat: test"
        config.task_id = "test-001"
        config.callback_url = ""
        config.callback_token = ""
        config.git_timeout = 300

        runner = TaskRunner(config)
        runner.git_ops = MagicMock()
        runner.callback = AsyncMock()
        runner.claude = MagicMock()

        # Mock _run_commit_mode 来验证路由
        runner._run_commit_mode = AsyncMock(return_value=0)

        log = MagicMock()
        result = await runner._run_execute_mode(log, "friday/test-branch")

        runner._run_commit_mode.assert_called_once_with(log, "friday/test-branch")
        assert result == 0

    @pytest.mark.asyncio
    async def test_coding_default_runs_full_execute(self):
        """task_type='coding'（默认）应执行完整 execute 流程。"""
        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding"
        config.task_mode = "execute"
        config.task_id = "test-001"
        config.task_title = "Test Task"
        config.task_description = "Test desc"
        config.callback_url = ""
        config.callback_token = ""

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.commit_changes = AsyncMock(return_value="abc123def")
        runner.git_ops.push_branch_with_retry = AsyncMock()
        runner.git_ops.get_modified_files = AsyncMock(return_value=["file.py"])
        runner.git_ops.get_diff_summary = AsyncMock(return_value="1 file changed")
        runner.callback = AsyncMock()
        runner.claude = MagicMock()
        runner.claude.get_session_summary = AsyncMock(return_value="plan summary")
        runner.claude.run_execute_mode = AsyncMock(return_value={"success": True})
        runner._generate_suggested_commit_message = AsyncMock(return_value="fix: final message")

        log = MagicMock()
        result = await runner._run_execute_mode(log, "friday/test-branch")

        assert result == 0
        runner.git_ops.commit_changes.assert_awaited_once_with("fix: final message")
        # 确保调用了 report_suggested_commit_message（Phase 回传）
        runner.callback.report_suggested_commit_message.assert_called_once()
        # implementation contract: 末尾发 completed 帧携带 git 元数据
        runner.callback.report_completed.assert_called_once()
        completed_call = runner.callback.report_completed.call_args
        output = completed_call.kwargs["output"]
        assert output["branch_name"] == "friday/test-branch"
        assert output["commit_sha"] == "abc123def"
        assert output["suggested_commit_message"] == "fix: final message"
        assert "modified_files" in output and isinstance(output["modified_files"], list)
        assert output["modified_files"] == ["file.py"]
        assert output["task_type"] == "coding"
        assert output["text"] == "1 file changed"  # diff_summary 落到 text
        assert completed_call.kwargs["result_type"] == "text"


class TestRunCommitMode:
    """TaskRunner._run_commit_mode 测试。"""

    @pytest.mark.asyncio
    async def test_commit_mode_missing_message_returns_error(self):
        """commit_message 为空时应报错返回 1。"""
        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding_commit"
        config.commit_message = ""
        config.task_id = "test-001"
        config.callback_url = ""
        config.callback_token = ""

        runner = TaskRunner(config)
        runner.git_ops = MagicMock()
        runner.callback = AsyncMock()

        log = MagicMock()
        result = await runner._run_commit_mode(log, "friday/test-branch")

        assert result == 1
        runner.callback.report_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_mode_amend_and_push(self):
        """_run_commit_mode 应执行 git commit --amend + push --force-with-lease。"""
        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding_commit"
        config.commit_message = "feat: user confirmed message"
        config.task_id = "test-001"
        config.callback_url = ""
        config.callback_token = ""
        config.git_timeout = 300

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.get_modified_files = AsyncMock(return_value=["file.py"])
        runner.git_ops.get_diff_summary = AsyncMock(return_value="1 file changed")
        runner.callback = AsyncMock()

        # Mock subprocess for git commands
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            log = MagicMock()
            result = await runner._run_commit_mode(log, "friday/test-branch")

        assert result == 0
        runner.callback.report_push_complete.assert_called_once()
        runner.callback.report_execution_complete.assert_called_once()
        # implementation contract: Phase 末尾也发 completed 帧（task_type=coding_commit）
        runner.callback.report_completed.assert_called_once()
        completed_call = runner.callback.report_completed.call_args
        output = completed_call.kwargs["output"]
        assert output["task_type"] == "coding_commit"
        assert output["branch_name"] == "friday/test-branch"
        assert output["commit_sha"] == "abc123"  # amended sha (rev-parse 输出)
        assert "modified_files" in output

    @pytest.mark.asyncio
    async def test_commit_mode_sets_git_identity_env(self):
        """commit amend 也应显式传 Git author/committer，不依赖容器 git config。"""
        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding_commit"
        config.commit_message = "fix: amend message"
        config.task_id = "test-identity"
        config.callback_url = ""
        config.callback_token = ""
        config.git_timeout = 300

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.get_modified_files = AsyncMock(return_value=[])
        runner.git_ops.get_diff_summary = AsyncMock(return_value="No changes")
        runner.callback = AsyncMock()

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(return_value=(b"abc123\n", b""))
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as create_proc:
            result = await runner._run_commit_mode(MagicMock(), "friday/test-branch")

        assert result == 0
        commit_call = create_proc.call_args_list[0]
        assert commit_call.args[:3] == ("/usr/bin/git", "commit", "--amend")
        env = commit_call.kwargs["env"]
        assert env["GIT_AUTHOR_NAME"] == "Friday Codes AI Agent"
        assert env["GIT_AUTHOR_EMAIL"] == "ai@friday.codes"
        assert env["GIT_COMMITTER_NAME"] == "Friday Codes AI Agent"
        assert env["GIT_COMMITTER_EMAIL"] == "ai@friday.codes"


class TestGenerateSuggestedCommitMessage:
    """_generate_suggested_commit_message 测试。"""

    @pytest.mark.asyncio
    async def test_generate_uses_claude_message_response(self):
        """优先使用 Claude Messages API 返回的 commit message。"""
        from core.runner import TaskRunner

        config = MagicMock()
        config.claude_api_key = "sk-test"
        config.claude_base_url = "https://anthropic.example"
        config.claude_model = "claude-test"
        config.claude_small_model = ""
        runner = TaskRunner(config)

        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "content": [
                        {"type": "text", "text": "fix: 隐藏空资源位\n\n接口空列表时不展示 Gift 入口。"}
                    ]
                }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post = AsyncMock(return_value=MockResponse())
        mock_client.__aexit__.return_value = None

        with patch("core.runner.httpx.AsyncClient", return_value=mock_client):
            result = await runner._generate_suggested_commit_message(
                diff_summary="Gift.vue | 37 +++++++++++++++++++++++--------------",
                task_title="学习首页搜索右侧资源位空列表隐藏方案",
                modified_files=["apps/tabStudy/src/v3/plugins/Gift/Gift.vue"],
            )

        assert result == "fix: 隐藏空资源位\n\n接口空列表时不展示 Gift 入口。"
        post = mock_client.__aenter__.return_value.post
        assert post.await_args is not None
        assert post.await_args.args[0] == "https://anthropic.example/v1/messages"
        payload = post.await_args.kwargs["json"]
        assert payload["model"] == "claude-test"
        assert "学习首页搜索右侧资源位空列表隐藏方案" in payload["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_generate_fallback_does_not_include_task_prompt(self):
        """AI 调用失败时 fallback 不得把完整任务 prompt 拼进 commit message。"""
        from core.runner import TaskRunner

        config = MagicMock()
        config.claude_api_key = "sk-test"
        config.claude_base_url = ""
        config.claude_model = ""
        config.claude_small_model = ""
        config.task_description = "你正在对项目「示例平台」执行编码任务。\n\n技术方案：很长..."
        runner = TaskRunner(config)

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post = AsyncMock(side_effect=RuntimeError("network down"))
        mock_client.__aexit__.return_value = None

        with patch("core.runner.httpx.AsyncClient", return_value=mock_client):
            result = await runner._generate_suggested_commit_message(
                diff_summary="Gift.vue | 37 +++++++++",
                task_title="学习首页搜索右侧资源位空列表隐藏方案",
                modified_files=["apps/tabStudy/src/v3/plugins/Gift/Gift.vue"],
            )

        assert "feat:" in result
        assert "学习首页搜索右侧资源位空列表隐藏方案" in result
        assert "Gift.vue | 37 +++++++++" in result
        assert "你正在对项目" not in result
        assert "技术方案" not in result

    @pytest.mark.asyncio
    async def test_generate_truncates_long_diff(self):
        """超长 diff summary 应被截断。"""
        from core.runner import TaskRunner

        config = MagicMock()
        config.claude_api_key = ""
        config.task_description = "prompt text that must not be included"
        runner = TaskRunner(config)

        long_diff = "a" * 1000
        result = await runner._generate_suggested_commit_message(
            diff_summary=long_diff,
            task_title="Test",
            modified_files=[],
        )

        # fallback diff 部分应被截断到 300 字符以内
        assert len(result) < 400
        assert "prompt text" not in result

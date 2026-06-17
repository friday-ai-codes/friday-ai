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
    async def test_report_completed_lifts_git_metadata_to_payload(self, mock_config, monkeypatch):
        """completed 帧必须把真实 branch/commit 放到服务端 serializer 读取的位置。"""
        sent_payloads = []

        class DummyResponse:
            def raise_for_status(self):
                return None

        class DummyClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def post(self, _url, json, headers, timeout):
                sent_payloads.append(json)
                return DummyResponse()

        monkeypatch.setattr("integrations.callback.httpx.AsyncClient", DummyClient)
        mock_config.callback_url = "http://localhost:8000/api"
        mock_config.callback_token = "test-token"
        client = CallbackClient(mock_config)

        result = await client.report_completed(
            output={
                "text": "done",
                "branch_name": "feat/actual-branch",
                "commit_sha": "abc123",
                "modified_files": ["a.py"],
            },
            result_type="text",
        )

        assert result is True
        payload = sent_payloads[0]["payload"]
        assert payload["branch_name"] == "feat/actual-branch"
        assert payload["commit_sha"] == "abc123"
        assert payload["modified_files"] == ["a.py"]

    @pytest.mark.asyncio
    async def test_report_started(self, mock_config):
        """测试报告启动状态。"""
        mock_config.callback_url = ""
        client = CallbackClient(mock_config)

        result = await client.report_started()
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
    """implementation contract：_run_execute_mode 末尾发 completed 帧携带 git 元数据。"""

    @pytest.mark.asyncio
    async def test_legacy_coding_mode_sets_up_and_pushes_task_branch(self):
        """旧协议 task_mode=coding 也必须先创建任务分支，禁止推送默认分支。"""
        from unittest.mock import AsyncMock, MagicMock

        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding"
        config.task_mode = "coding"
        config.task_id = "legacy-001"
        config.task_title = "修复资源位"
        config.task_description = "修复 Gift 资源位展示"
        config.git_branch = "master"
        config.branch_strategy = "feature/demo-task-branch"
        config.git_new_branch = None
        config.callback_url = ""
        config.callback_token = ""

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.setup_task_branch = AsyncMock(return_value="feature/demo-task-branch")
        runner.git_ops.get_workspace_path = MagicMock(return_value="/tmp/workspace")
        runner.git_ops.cleanup = MagicMock()
        runner.git_ops.restore_task_branch = AsyncMock(return_value=True)
        runner.git_ops.ensure_current_branch = AsyncMock(return_value=True)
        runner.git_ops.commit_changes = AsyncMock(return_value="deadbeef")
        runner.git_ops.push_branch_with_retry = AsyncMock()
        runner.git_ops.get_modified_files = AsyncMock(return_value=["apps/Gift.vue"])
        runner.git_ops.get_diff_summary = AsyncMock(return_value="1 file changed")
        runner.callback = AsyncMock()

        fake_claude = MagicMock()
        fake_claude.get_session_summary = AsyncMock(return_value="plan summary")
        fake_claude.run_execute_mode = AsyncMock(return_value={"success": True})

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.runner.ClaudeRunner", lambda *_args, **_kwargs: fake_claude)
            result = await runner.run()

        assert result == 0
        runner.git_ops.setup_task_branch.assert_awaited_once_with(
            branch_strategy="feature/demo-task-branch",
            task_id="legacy-001",
        )
        runner.git_ops.push_branch_with_retry.assert_awaited_once_with("feature/demo-task-branch")

    @pytest.mark.asyncio
    async def test_run_refuses_protected_work_branch_before_claude(self):
        """Runner 准备出的工作分支若是保护分支，应在 Claude 执行前失败。"""
        from unittest.mock import AsyncMock, MagicMock

        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding"
        config.task_mode = "execute"
        config.task_id = "bad-branch-001"
        config.git_branch = "master"
        config.branch_strategy = "master"
        config.git_new_branch = None
        config.callback_url = ""
        config.callback_token = ""

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.setup_task_branch = AsyncMock(return_value="master")
        runner.git_ops.get_workspace_path = MagicMock(return_value="/tmp/workspace")
        runner.git_ops.cleanup = MagicMock()
        runner.callback = AsyncMock()

        result = await runner.run()

        assert result == 1
        runner.callback.report_error.assert_awaited_once()
        runner.git_ops.commit_changes.assert_not_called()
        runner.git_ops.push_branch_with_retry.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_execute_mode_reports_completed_with_git_metadata(self):
        """_run_execute_mode 成功路径应调 report_completed 一次，output 含 6 个字段。"""
        from unittest.mock import AsyncMock, MagicMock

        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding"
        config.task_mode = "execute"
        config.task_id = "exec-001"
        config.task_title = "用户认证"
        config.task_description = "加 JWT 认证"
        config.callback_url = ""
        config.callback_token = ""

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.commit_changes = AsyncMock(return_value="deadbeef")
        runner.git_ops.push_branch_with_retry = AsyncMock()
        runner.git_ops.get_modified_files = AsyncMock(return_value=["auth.py", "models.py"])
        runner.git_ops.get_diff_summary = AsyncMock(
            return_value="2 files changed, 100 insertions(+)"
        )
        runner.callback = AsyncMock()
        runner.claude = MagicMock()
        runner.claude.get_session_summary = AsyncMock(return_value="plan summary")
        runner.claude.run_execute_mode = AsyncMock(return_value={"success": True})

        log = MagicMock()
        result = await runner._run_execute_mode(log, "friday/exec-test")
        assert result == 0

        # 调用序列断言：progress 帧（execution_complete / push_complete /
        # suggested_commit_message）保留 + 末尾新增 completed 帧
        runner.callback.report_execution_complete.assert_called_once()
        runner.callback.report_push_complete.assert_called_once()
        runner.callback.report_suggested_commit_message.assert_called_once()
        runner.callback.report_completed.assert_called_once()

        completed_call = runner.callback.report_completed.call_args
        output = completed_call.kwargs["output"]
        assert output["branch_name"] == "friday/exec-test"
        assert output["commit_sha"] == "deadbeef"
        assert output["suggested_commit_message"] != ""
        assert "modified_files" in output and isinstance(output["modified_files"], list)
        assert output["modified_files"] == ["auth.py", "models.py"]
        assert output["task_type"] == "coding"

    def test_execute_prompt_forbids_agent_git_branch_commit_and_pr(self):
        """Claude 只改工作区文件，分支/commit/push/MR 由 Runner 编排统一处理。"""
        from unittest.mock import MagicMock

        from core.executor import ClaudeRunner

        config = MagicMock()
        config.task_description = "修复资源位展示"
        runner = ClaudeRunner(config, "/tmp/workspace")

        prompt = runner._build_execute_prompt("已批准方案")

        assert "Do NOT create or switch branches" in prompt
        assert "Do NOT run git commit" in prompt
        assert "Do NOT push" in prompt
        assert "Do NOT create pull requests" in prompt

    @pytest.mark.asyncio
    async def test_run_execute_mode_no_changes_skips_completed(self):
        """无改动场景（commit_sha 为 falsy）应走 no_changes 分支，不发 completed 帧。"""
        from unittest.mock import AsyncMock, MagicMock

        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding"
        config.task_mode = "execute"
        config.task_id = "nochange-001"
        config.callback_url = ""
        config.callback_token = ""

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.commit_changes = AsyncMock(return_value="")  # falsy => no changes
        runner.callback = AsyncMock()
        runner.claude = MagicMock()
        runner.claude.get_session_summary = AsyncMock(return_value="plan")
        runner.claude.run_execute_mode = AsyncMock(return_value={"success": True})

        log = MagicMock()
        result = await runner._run_execute_mode(log, "friday/no-change")
        assert result == 0
        runner.callback.report_completed.assert_not_called()
        runner.callback.report_status.assert_called()

    @pytest.mark.asyncio
    async def test_run_execute_mode_fails_when_agent_switches_branch(self):
        """如果 Claude 擅自切分支，Runner 应阻断后续 commit/push。"""
        from unittest.mock import AsyncMock, MagicMock

        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding"
        config.task_mode = "execute"
        config.task_id = "branch-drift-001"
        config.task_title = "分支漂移"
        config.task_description = "测试分支漂移"
        config.callback_url = ""
        config.callback_token = ""

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.restore_task_branch = AsyncMock(return_value=False)
        runner.git_ops.ensure_current_branch = AsyncMock(return_value=False)
        runner.git_ops.commit_changes = AsyncMock(return_value="deadbeef")
        runner.callback = AsyncMock()
        runner.claude = MagicMock()
        runner.claude.get_session_summary = AsyncMock(return_value="plan summary")
        runner.claude.run_execute_mode = AsyncMock(return_value={"success": True})

        result = await runner._run_execute_mode(MagicMock(), "feature/expected-task-branch")

        assert result == 1
        runner.git_ops.commit_changes.assert_not_called()
        runner.callback.report_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_execute_mode_restores_task_branch_before_commit(self):
        """Runner 必须在 commit 前强制 reset 到准备好的任务分支。"""
        from unittest.mock import AsyncMock, MagicMock

        from core.runner import TaskRunner

        config = MagicMock()
        config.task_type = "coding"
        config.task_mode = "execute"
        config.task_id = "reset-001"
        config.task_title = "强制 reset"
        config.task_description = "确保 commit 前回到任务分支"
        config.callback_url = ""
        config.callback_token = ""

        runner = TaskRunner(config)
        runner.git_ops = AsyncMock()
        runner.git_ops.restore_task_branch = AsyncMock(return_value=True)
        runner.git_ops.ensure_current_branch = AsyncMock(return_value=True)
        runner.git_ops.commit_changes = AsyncMock(return_value="deadbeef")
        runner.git_ops.push_branch_with_retry = AsyncMock()
        runner.git_ops.get_modified_files = AsyncMock(return_value=["a.py"])
        runner.git_ops.get_diff_summary = AsyncMock(return_value="1 file")
        runner.callback = AsyncMock()
        runner.claude = MagicMock()
        runner.claude.get_session_summary = AsyncMock(return_value="plan")
        runner.claude.run_execute_mode = AsyncMock(return_value={"success": True})

        result = await runner._run_execute_mode(MagicMock(), "feature/expected-task-branch")

        assert result == 0
        runner.git_ops.restore_task_branch.assert_awaited_once_with("feature/expected-task-branch")
        runner.git_ops.commit_changes.assert_awaited()


class TestClaudeExecuteModeKeepsBash:
    """编码模式仍要允许 Claude 调 Bash 跑测试/lint；git 写操作交给 shell wrapper 拦截。"""

    @pytest.mark.asyncio
    async def test_execute_mode_does_not_disable_bash(self, monkeypatch):
        """禁 Bash 太粗暴；只在 git-wrapper 层拦截写操作，Bash 本身保留。"""
        from pathlib import Path
        from unittest.mock import MagicMock

        from core import executor as executor_module

        captured: dict[str, object] = {}

        class _FakeOptions:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        async def _empty_query(prompt, options):  # pragma: no cover - dummy
            if False:
                yield None
            return

        monkeypatch.setattr(executor_module, "ClaudeAgentOptions", _FakeOptions)
        monkeypatch.setattr(executor_module, "query", _empty_query)

        config = MagicMock()
        config.claude_api_key = "k"
        config.claude_base_url = ""
        config.claude_small_model = ""
        config.claude_model = ""
        config.claude_max_turns = 10
        config.task_id = "exec-tool"
        config.task_mode = "execute"
        config.session_dir = "/tmp"
        # 防 MagicMock 真值属性误触 openspec 追加（Phase 51-03 D-51-5）。
        config.follow_openspec = False

        runner = executor_module.ClaudeRunner(config, Path("/tmp"))
        await runner.run_execute_mode(plan="any")

        assert captured.get("permission_mode") == "bypassPermissions"
        disallowed = captured.get("disallowed_tools") or []
        assert "Bash" not in disallowed, (
            "禁 Bash 会导致 Claude 跑不了 npm test / lint；改用 git-wrapper 拦截 git 写操作"
        )

    def test_system_prompt_explains_runner_handles_git(self):
        """system prompt 提醒 Claude 把 git 交给 Runner，但不必声称 Bash 被禁。"""
        from pathlib import Path
        from unittest.mock import MagicMock

        from core.executor import ClaudeRunner

        # 显式设 follow_openspec=False：MagicMock 默认属性是真值 Mock，会误触 openspec
        # 追加破坏零回归断言（Phase 51-03 D-51-5 / T-51-MOCK）。
        config = MagicMock()
        config.follow_openspec = False
        runner = ClaudeRunner(config, Path("/tmp"))
        prompt = runner._get_system_prompt()

        assert "Runner" in prompt
        assert "git commit" in prompt or "git push" in prompt or "git 命令" in prompt
        # 不应再宣称 Bash 被禁
        assert "Bash" not in prompt or "已被显式禁用" not in prompt

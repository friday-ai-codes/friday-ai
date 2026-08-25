"""容器侧 repo_summary 模式测试。

覆盖 4 个 behavior:
- Test 1: _check_explore_guard 在 task_mode="repo_summary" 时抛出 ExploreModeForbiddenError
- Test 2: git-wrapper.sh 在 FRIDAY_TASK_MODE=repo_summary 时将 mode 别名为 explore
- Test 3: CallbackClient.report_completed() 构建正确 payload
- Test 4: CallbackClient.report_failed() 构建正确 payload
"""

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from core.config import TaskConfig
from core.exceptions import ExploreModeForbiddenError
from core.executor import ClaudeRunner
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
        """repo_summary 模式下调用 commit_changes() 抛出 ExploreModeForbiddenError。"""
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
        """repo_summary 模式下调用 push_branch() 抛出 ExploreModeForbiddenError。"""
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
        """repo_summary 模式下调用 setup_task_branch() 抛出 ExploreModeForbiddenError。"""
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


class TestRepoSummaryStructuredSubmit:
    """repo_summary 经共享 Agent→Friday MCP 工厂提交结构化结果（唯一渠道）。

    plan 模式会让模型等待"用户批准计划"，无人值守容器里会以
    "Please approve the plan ..." 文本收尾，拿不到结果；改为 bypassPermissions +
    只读白名单 + MCP 提交工具，收口统一走 apply_capture_to_result。
    """

    def _make_runner(self, tmp_path: Path) -> ClaudeRunner:
        config = TaskConfig(
            task_id="test-rs-tool",
            task_description="分析仓库并生成描述",
            git_repo_url="https://test.com/repo.git",
            task_mode="repo_summary",
            session_dir=str(tmp_path / "sessions"),
        )
        return ClaudeRunner(config, tmp_path)

    @pytest.mark.asyncio
    async def test_repo_summary_mounts_shared_submit_mcp(self, tmp_path):
        """repo_summary 用 bypassPermissions + 只读白名单 + 共享 friday-submit 工具。"""
        runner = self._make_runner(tmp_path)
        runner._execute_claude = AsyncMock(
            return_value={"success": False, "error": "empty"}
        )

        await runner.run_repo_summary_mode()

        kwargs = runner._execute_claude.call_args.kwargs
        assert kwargs["permission_mode"] == "bypassPermissions"
        for tool in ("Write", "Edit", "MultiEdit"):
            assert tool in kwargs["disallowed_tools"]

        submit_tool = "mcp__friday-submit__submit_repo_summary"
        assert submit_tool in kwargs["extra_allowed_tools"]
        assert "Write" not in kwargs["extra_allowed_tools"]
        assert "friday-submit" in kwargs["extra_mcp_servers"]
        # prompt 末尾追加了工厂提交契约
        assert submit_tool in kwargs["prompt"]

    @pytest.mark.asyncio
    async def test_captured_result_wins_even_on_empty_text(self, tmp_path, monkeypatch):
        """模型只调工具、SDK 空文本报错时，工厂捕获的结构化结果覆盖误判为成功。"""
        import core.executor as executor_mod
        from core.agent_submit_mcp import build_submit_mcp as real_build

        runner = self._make_runner(tmp_path)

        built = real_build("repo_summary")

        def fake_build(scenario):
            return built

        monkeypatch.setattr(executor_mod, "build_submit_mcp", fake_build)

        async def fake_execute(**kwargs):
            # 模拟 SDK 运行期间模型经 MCP 工具提交（工厂 handler 写入 capture）
            built.capture.value = {"overview": "测试项目", "tech_stack": ["Vue"]}
            return {"success": False, "error": "Claude SDK returned empty response"}

        runner._execute_claude = AsyncMock(side_effect=fake_execute)
        result = await runner.run_repo_summary_mode()

        assert result["success"] is True
        assert "error" not in result
        assert result["mcp_result"]["overview"] == "测试项目"
        assert result["submit_scenario"] == "repo_summary"

    @pytest.mark.asyncio
    async def test_not_called_marks_failure(self, tmp_path):
        """未经 MCP 提交（capture 为空）→ 明确失败，稳定 reason，不拿文本兜底。"""
        runner = self._make_runner(tmp_path)
        runner._execute_claude = AsyncMock(
            return_value={"success": True, "output": '{"overview": "纯文本"}'}
        )

        result = await runner.run_repo_summary_mode()

        assert result["success"] is False
        assert result["error_reason"] == "mcp_tool_not_called"
        assert "mcp_result" not in result

    def test_repo_summary_schema_includes_optional_charter(self):
        """repo_summary schema 含可选 charter（D-01）。"""
        from core.agent_submit_mcp import get_scenario

        schema = get_scenario("repo_summary").input_schema
        props = schema["properties"]
        assert "charter" in props
        assert "charter" not in schema["required"]
        assert "意图面" in props["charter"]["description"]


class TestGitWrapperRepoSummary:
    """Test 2: git-wrapper.sh 在 FRIDAY_TASK_MODE=repo_summary 时别名为 explore。"""

    def test_git_wrapper_aliases_repo_summary_to_explore(self):
        """git-wrapper.sh 在 FRIDAY_TASK_MODE=repo_summary 时将 mode 设置为 explore。"""
        # 提取 wrapper 中的 alias case 块（``case "$FRIDAY_TASK_MODE" in`` ~ ``esac``）
        script_path = Path(__file__).resolve().parents[1] / "git_ops" / "git-wrapper.sh"
        lines = script_path.read_text().splitlines()
        start = next(i for i, ln in enumerate(lines) if 'case "$FRIDAY_TASK_MODE"' in ln)
        end = next(i for i, ln in enumerate(lines) if i > start and ln.strip() == "esac")
        alias_snippet = "\n".join(lines[start : end + 1])
        result = subprocess.run(
            [
                "bash",
                "-c",
                f'FRIDAY_TASK_MODE=repo_summary; {alias_snippet}; echo "$FRIDAY_TASK_MODE"',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.stdout.strip() == "explore", (
            f"Expected FRIDAY_TASK_MODE to be 'explore' after sourcing, got: '{result.stdout.strip()}'"
        )


class TestGitTokenAuth:
    """Token 认证 URL 构造与服务端索引路径保持一致。"""

    @pytest.mark.asyncio
    async def test_gitlab_token_is_url_encoded_in_password_position(self):
        config = TaskConfig(
            task_id="test-rs-token",
            task_description="test",
            git_repo_url="git@gitlab.example.com:frontend/example-practice.git",
            git_auth_type="token",
            git_access_token="glpat-a/b+c@d:e",
        )
        ops = GitOperations(config)

        await ops._setup_token_auth()

        assert config.git_repo_url == (
            "https://oauth2:glpat-a%2Fb%2Bc%40d%3Ae"
            "@gitlab.example.com/frontend/example-practice.git"
        )


class TestCallbackReportCompleted:
    """Test 3: CallbackClient.report_completed() 构建正确的 payload。"""

    def test_callback_endpoint_uses_runner_callback_path_as_is(self):
        config = TaskConfig(
            task_id="test-session-123",
            task_description="test",
            git_repo_url="https://test.com/repo.git",
            callback_url="http://host.docker.internal:8976/callback",
            callback_token="tok-secret-456",
        )
        client = CallbackClient(config)

        assert client._callback_endpoint() == "http://host.docker.internal:8976/callback"

    def test_callback_endpoint_appends_server_api_path_for_base_url(self):
        config = TaskConfig(
            task_id="test-session-123",
            task_description="test",
            git_repo_url="https://test.com/repo.git",
            callback_url="http://localhost:10241",
            callback_token="tok-secret-456",
        )
        client = CallbackClient(config)

        assert client._callback_endpoint() == "http://localhost:10241/api/containers/callback/"

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
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
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
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
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
            mock_client_cls.assert_not_called()


class TestCallbackReportFailed:
    """Test 4: CallbackClient.report_failed() 构建正确的 payload。"""

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
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
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
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
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
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.HTTPError("connection failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await client.report_failed(error="test")
            assert result is False


class TestRepoSummaryClaudeRetry:
    """repo_summary 调 Claude SDK 时的瞬时错误重试。"""

    @pytest.mark.asyncio
    async def test_execute_claude_retries_transient_server_error(self, tmp_path):
        """Claude SDK stream 中途 server_error 时重试并返回后续成功输出。"""
        config = TaskConfig(
            task_id="test-rs-retry",
            task_description="test",
            git_repo_url="https://test.com/repo.git",
            task_mode="repo_summary",
            claude_api_key="test-key",
            session_dir=str(tmp_path / "sessions"),
        )
        runner = ClaudeRunner(config, tmp_path)
        attempts = 0

        async def failing_stream():
            raise Exception("The server had an error while processing your request")
            yield

        async def successful_stream():
            yield AssistantMessage(
                content=[TextBlock(text='{"overview": "ok"}')],
                model="claude-test",
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="session-ok",
                total_cost_usd=0.01,
                usage={"input_tokens": 10, "output_tokens": 5},
                result='{"overview": "ok"}',
            )

        def fake_query(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return failing_stream()
            return successful_stream()

        with patch("core.executor.query", side_effect=fake_query):
            result = await runner._execute_claude(
                prompt="生成仓库描述 JSON",
                permission_mode="plan",
                max_turns=2,
            )

        assert attempts == 2
        assert result["success"] is True
        assert result["output"] == '{"overview": "ok"}'

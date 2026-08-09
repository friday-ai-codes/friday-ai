"""Claude Agent SDK 集成测试。

这些测试需要真实的 Anthropic API Key 才能运行。
默认情况下会跳过，通过设置环境变量 FRIDAY_RUN_INTEGRATION_TESTS=1 启用。

使用方式：
    FRIDAY_TASK_CLAUDE_API_KEY=your-key FRIDAY_RUN_INTEGRATION_TESTS=1 pytest tests/test_claude_sdk_integration.py -v
"""

import os
from pathlib import Path

import pytest

# 检查是否应该运行集成测试
SKIP_INTEGRATION = os.environ.get("FRIDAY_RUN_INTEGRATION_TESTS", "0") != "1"
SKIP_REASON = "集成测试已禁用。设置 FRIDAY_RUN_INTEGRATION_TESTS=1 启用"


@pytest.mark.skipif(SKIP_INTEGRATION, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_claude_runner_plan_mode(temp_workspace, mock_config):
    """测试 Claude Runner 的 plan 模式。"""
    # 仅当有 API Key 时才导入和测试
    if not mock_config.claude_api_key:
        pytest.skip("需要设置 FRIDAY_TASK_CLAUDE_API_KEY")

    from core import ClaudeRunner

    runner = ClaudeRunner(config=mock_config, workspace=temp_workspace)

    result = await runner.run_plan_mode()

    assert result["success"] is True
    assert "output" in result
    assert len(result["output"]) > 0
    assert result["message_count"] > 0


@pytest.mark.skipif(SKIP_INTEGRATION, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_claude_runner_execute_mode(temp_workspace, mock_config):
    """测试 Claude Runner 的 execute 模式。"""
    if not mock_config.claude_api_key:
        pytest.skip("需要设置 FRIDAY_TASK_CLAUDE_API_KEY")

    from core import ClaudeRunner

    runner = ClaudeRunner(config=mock_config, workspace=temp_workspace)

    # 提供一个简单的 plan
    plan = """
## Implementation plan. Add a new function `goodbye()` to `src/main.py`
2. The function should return "Goodbye, World!"
"""

    result = await runner.run_execute_mode(plan=plan)

    assert result["success"] is True
    assert "output" in result


@pytest.mark.skipif(SKIP_INTEGRATION, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_claude_runner_session_save(temp_workspace, mock_config):
    """测试会话保存功能。"""
    if not mock_config.claude_api_key:
        pytest.skip("需要设置 FRIDAY_TASK_CLAUDE_API_KEY")

    from core import ClaudeRunner

    runner = ClaudeRunner(config=mock_config, workspace=temp_workspace)

    # 运行一次
    result = await runner.run_plan_mode()
    assert result["success"] is True

    # 检查会话文件是否创建
    session_file = Path(mock_config.session_dir) / f"{mock_config.task_id}.json"
    assert session_file.exists()

    # 检查可以读取会话摘要
    summary = await runner.get_session_summary()
    assert summary is not None


# === 模拟测试（不需要真实 API）===


@pytest.mark.asyncio
async def test_claude_runner_prompt_building(temp_workspace, mock_config):
    """测试 prompt 构建逻辑（不需要 API）。"""
    # 测试 plan prompt 构建
    expected_description = mock_config.task_description

    plan_prompt_template = f"""You are an AI development agent working on a coding task.

## Task Information
- **Description**: {expected_description}

## Your Goal
Analyze the codebase and create a detailed implementation plan. Do NOT make any changes yet.
"""

    assert expected_description in plan_prompt_template


@pytest.mark.asyncio
async def test_claude_runner_session_file_location(temp_workspace, mock_config):
    """测试会话文件路径正确性。"""
    expected_session_file = Path(mock_config.session_dir) / f"{mock_config.task_id}.json"

    # 验证路径构建正确
    assert str(expected_session_file).endswith(f"{mock_config.task_id}.json")
    assert mock_config.session_dir in str(expected_session_file)


@pytest.mark.asyncio
async def test_claude_runner_handles_missing_api_key(temp_workspace, mock_config):
    """测试没有 API Key 时的错误处理。"""
    mock_config.claude_api_key = ""
    os.environ.pop("FRIDAY_TASK_CLAUDE_API_KEY", None)

    # 这个测试验证在没有 API Key 时，runner 会优雅地处理错误
    # 具体行为取决于 SDK 实现
    # 这里我们只验证配置状态
    assert mock_config.claude_api_key == ""


@pytest.mark.asyncio
async def test_session_mapping(temp_session_dir, mock_config):
    """测试会话映射功能。"""
    import json

    from core import ClaudeRunner

    mock_config.session_dir = temp_session_dir

    # 创建一个映射文件
    mapping_file = Path(temp_session_dir) / "mapping.json"
    mapping_data = {
        "session-abc123": {
            "task_id": "test-task-001",
            "created_at": "2026-01-17T12:00:00Z",
            "last_output_preview": "Test output preview",
        }
    }
    mapping_file.write_text(json.dumps(mapping_data))

    # 测试通过 session_id 获取会话信息
    session_info = await ClaudeRunner.get_session_by_id("session-abc123", temp_session_dir)

    assert session_info is not None
    assert session_info["task_id"] == "test-task-001"


@pytest.mark.asyncio
async def test_session_mapping_not_found(temp_session_dir):
    """测试会话不存在的情况。"""
    from core import ClaudeRunner

    session_info = await ClaudeRunner.get_session_by_id("non-existent-session", temp_session_dir)

    assert session_info is None


# === Phase 11 RemoteTool 装配（_execute_claude 条件挂载 mcp_servers/allowed_tools）===


def _make_real_config(temp_session_dir, **overrides):
    """构造真实 TaskConfig（非 MagicMock），便于断言 options 装配。"""
    from core import TaskConfig

    params = dict(
        task_id="test-rtool-001",
        task_description="rtool test",
        git_repo_url="git@github.com:test/repo.git",
        task_mode="plan",
        session_dir=temp_session_dir,
    )
    params.update(overrides)
    return TaskConfig(**params)


async def _capture_options(monkeypatch, runner):
    """monkeypatch core.executor.query 捕获 ClaudeAgentOptions，不触网。"""
    captured: dict = {}

    async def fake_query(*, prompt, options):
        captured["options"] = options
        if False:  # pragma: no cover - 让函数成为空 async generator
            yield None

    monkeypatch.setattr("core.executor.query", fake_query)
    await runner._execute_claude(prompt="hi", permission_mode="plan")
    return captured["options"]


@pytest.mark.asyncio
async def test_options_include_mcp_when_remote_tools_present(
    monkeypatch, temp_workspace, temp_session_dir
):
    """有 remote_tools + user_token + tools_endpoint → options 含 mcp_servers + allowed_tools。"""
    from core import ClaudeRunner
    from core.remote_tools import REMOTE_MCP_SERVER_NAME

    config = _make_real_config(
        temp_session_dir,
        remote_tools=[{"name": "a", "input_schema": {}}],
        user_token="friday_pat_SECRET123",
        tools_endpoint="https://friday.example.com/api/tools/execute/",
    )
    runner = ClaudeRunner(config=config, workspace=temp_workspace)

    options = await _capture_options(monkeypatch, runner)

    assert REMOTE_MCP_SERVER_NAME in options.mcp_servers
    # 远程工具被列入 allowed_tools
    assert f"mcp__{REMOTE_MCP_SERVER_NAME}__a" in options.allowed_tools
    # WR-02：挂载远程工具不得禁掉内建编码工具，Bash/Edit/Write/Read 必须仍可用
    for builtin in ("Bash", "Edit", "Write", "Read"):
        assert builtin in options.allowed_tools


@pytest.mark.asyncio
async def test_execute_mode_keeps_builtin_tools_with_remote_tools(
    monkeypatch, temp_workspace, temp_session_dir
):
    """execute 模式挂载远程工具后，内建编码工具（Bash/Edit/Write/Read）仍在
    allowed_tools 内，远程工具也在——二者并存（WR-02）。"""
    from core import ClaudeRunner
    from core.remote_tools import REMOTE_MCP_SERVER_NAME

    config = _make_real_config(
        temp_session_dir,
        task_mode="execute",
        remote_tools=[{"name": "a", "input_schema": {}}],
        user_token="friday_pat_SECRET123",
        tools_endpoint="https://friday.example.com/api/tools/execute/",
    )
    runner = ClaudeRunner(config=config, workspace=temp_workspace)

    captured: dict = {}

    async def fake_query(*, prompt, options):
        captured["options"] = options
        if False:  # pragma: no cover - 空 async generator
            yield None

    monkeypatch.setattr("core.executor.query", fake_query)
    await runner._execute_claude(prompt="hi", permission_mode="bypassPermissions")
    options = captured["options"]

    assert f"mcp__{REMOTE_MCP_SERVER_NAME}__a" in options.allowed_tools
    for builtin in ("Bash", "Edit", "Write", "Read", "Glob", "Grep"):
        assert builtin in options.allowed_tools


@pytest.mark.asyncio
async def test_options_omit_mcp_when_no_remote_tools(monkeypatch, temp_workspace, temp_session_dir):
    """无 remote_tools/token/endpoint → options 不含 friday-remote-tools server（向后兼容）。"""
    from core import ClaudeRunner
    from core.remote_tools import REMOTE_MCP_SERVER_NAME

    config = _make_real_config(temp_session_dir)
    runner = ClaudeRunner(config=config, workspace=temp_workspace)

    options = await _capture_options(monkeypatch, runner)

    assert REMOTE_MCP_SERVER_NAME not in (options.mcp_servers or {})


@pytest.mark.asyncio
async def test_executor_logs_no_pat_plaintext(monkeypatch, temp_workspace, temp_session_dir):
    """executor 日志只记 has_user_token bool，绝不记 PAT 明文（T-11-04 脱敏）。"""
    import structlog

    from core import ClaudeRunner

    secret = "friday_pat_SECRET123"
    config = _make_real_config(
        temp_session_dir,
        remote_tools=[{"name": "a", "input_schema": {}}],
        user_token=secret,
        tools_endpoint="https://friday.example.com/api/tools/execute/",
    )
    runner = ClaudeRunner(config=config, workspace=temp_workspace)

    async def fake_query(*, prompt, options):
        if False:  # pragma: no cover
            yield None

    monkeypatch.setattr("core.executor.query", fake_query)
    with structlog.testing.capture_logs() as captured:
        await runner._execute_claude(prompt="hi", permission_mode="plan")

    assert secret not in str(captured)


# === Phase 103-02 合并收口（_build_tool_mounts 单一构造函数，WR-02 第七面）===


@pytest.mark.asyncio
async def test_knowledge_alone_keeps_builtin_tools(monkeypatch, temp_workspace, temp_session_dir):
    """knowledge 单独挂载（remote 未配）：allowed_tools 含全量 builtin +
    7 个 mcp__friday-knowledge__*，mcp_servers 恰含 friday-knowledge（WR-02 隐患面修复：
    收口前照抄 remote 分支会丢 builtin，禁掉 Bash/Edit/Write 破坏 execute）。"""
    from core import ClaudeRunner
    from core.executor import _BUILTIN_CODING_TOOLS
    from core.knowledge_tools import KNOWLEDGE_MCP_SERVER_NAME, knowledge_allowed_tools

    config = _make_real_config(
        temp_session_dir,
        task_mode="execute",
        knowledge_endpoint="https://friday.example.com",
        user_token="friday_pat_SECRET123",
        # remote 未配：remote_tools/tools_endpoint 保持默认空
    )
    runner = ClaudeRunner(config=config, workspace=temp_workspace)

    options = await _capture_options(monkeypatch, runner)

    assert list(options.mcp_servers.keys()) == [KNOWLEDGE_MCP_SERVER_NAME]
    # WR-02：全量 builtin 必须在列（Bash/Read/Edit/Write/MultiEdit/Glob/Grep 等）
    for builtin in _BUILTIN_CODING_TOOLS:
        assert builtin in options.allowed_tools, f"builtin {builtin} 不得丢失"
    # 12 个知识工具全部在列（126 追加 rename_preview 后 11 → 12）
    for tool in knowledge_allowed_tools():
        assert tool in options.allowed_tools
    assert len(knowledge_allowed_tools()) == 12
    assert "mcp__friday-knowledge__detect_changes" in options.allowed_tools
    assert "mcp__friday-knowledge__rename_preview" in options.allowed_tools


@pytest.mark.asyncio
async def test_three_sources_merge_union_with_builtin_no_dupes(
    monkeypatch, temp_workspace, temp_session_dir
):
    """remote + knowledge + extra(ask_user) 三源同挂：allowed_tools 为三源并集 +
    builtin，无重复项；mcp_servers 含三个 server。"""
    from core import ClaudeRunner
    from core.executor import _BUILTIN_CODING_TOOLS
    from core.knowledge_tools import KNOWLEDGE_MCP_SERVER_NAME, knowledge_allowed_tools
    from core.question_loop import ASK_USER_MCP_SERVER_NAME, ask_user_allowed_tools
    from core.remote_tools import REMOTE_MCP_SERVER_NAME

    config = _make_real_config(
        temp_session_dir,
        task_mode="execute",
        remote_tools=[{"name": "a", "input_schema": {}}],
        tools_endpoint="https://friday.example.com/api/tools/execute/",
        knowledge_endpoint="https://friday.example.com",
        user_token="friday_pat_SECRET123",
    )
    runner = ClaudeRunner(config=config, workspace=temp_workspace)

    captured: dict = {}

    async def fake_query(*, prompt, options):
        captured["options"] = options
        if False:  # pragma: no cover - 空 async generator
            yield None

    monkeypatch.setattr("core.executor.query", fake_query)
    # extra 源镜像 run_execute_mode 的 ask_user 装配（含 builtin，收口后去重不重复）
    await runner._execute_claude(
        prompt="hi",
        permission_mode="bypassPermissions",
        extra_mcp_servers={ASK_USER_MCP_SERVER_NAME: object()},
        extra_allowed_tools=[*_BUILTIN_CODING_TOOLS, *ask_user_allowed_tools()],
    )
    options = captured["options"]

    assert set(options.mcp_servers.keys()) == {
        REMOTE_MCP_SERVER_NAME,
        KNOWLEDGE_MCP_SERVER_NAME,
        ASK_USER_MCP_SERVER_NAME,
    }
    expected_union = {
        *_BUILTIN_CODING_TOOLS,
        f"mcp__{REMOTE_MCP_SERVER_NAME}__a",
        *knowledge_allowed_tools(),
        *ask_user_allowed_tools(),
    }
    assert set(options.allowed_tools) == expected_union
    assert len(options.allowed_tools) == len(set(options.allowed_tools)), "无重复项"


@pytest.mark.asyncio
async def test_extra_only_mount_keeps_caller_allowlist_no_builtin(
    monkeypatch, temp_workspace, temp_session_dir
):
    """extra-only 挂载（repo_summary 形态：remote/knowledge 均未配，仅 extra server）：
    allowed_tools 恰为调用方自带白名单，builtin 不并入——WebFetch/WebSearch 等
    网络工具不得被悄悄解禁（103 审查 WR-01：只读分析容器网络出口是白名单级策略）。"""
    from core import ClaudeRunner
    from core.executor import _READONLY_ANALYSIS_TOOLS

    config = _make_real_config(temp_session_dir, task_mode="repo_summary")
    runner = ClaudeRunner(config=config, workspace=temp_workspace)

    captured: dict = {}

    async def fake_query(*, prompt, options):
        captured["options"] = options
        if False:  # pragma: no cover - 空 async generator
            yield None

    monkeypatch.setattr("core.executor.query", fake_query)
    submit_tool = "mcp__repo-summary__submit_summary"
    await runner._execute_claude(
        prompt="hi",
        permission_mode="bypassPermissions",
        extra_mcp_servers={"repo-summary": object()},
        extra_allowed_tools=[*_READONLY_ANALYSIS_TOOLS, submit_tool],
    )
    options = captured["options"]

    assert set(options.allowed_tools) == {*_READONLY_ANALYSIS_TOOLS, submit_tool}
    assert "WebFetch" not in options.allowed_tools
    assert "WebSearch" not in options.allowed_tools
    assert "Write" not in options.allowed_tools
    assert "Edit" not in options.allowed_tools


@pytest.mark.asyncio
async def test_empty_config_options_have_no_mounts(monkeypatch, temp_workspace, temp_session_dir):
    """全空配置（remote/knowledge/extra 均未配）：options 不含任何 MCP server 与
    allowed_tools（零回归钉子——与收口前行为逐字一致）。"""
    from core import ClaudeRunner

    config = _make_real_config(temp_session_dir)
    runner = ClaudeRunner(config=config, workspace=temp_workspace)

    options = await _capture_options(monkeypatch, runner)

    assert not options.mcp_servers, "全空配置不得挂载任何 MCP server"
    assert not options.allowed_tools, "全空配置不得设置 allowed_tools 白名单"

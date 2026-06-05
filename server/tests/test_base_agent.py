"""initial implementation Wave（task）：AIAgentBaseNode 单元测试。

覆盖范围（implementation plan Task 3 <behavior> 11 场景）：

- Test 1 test_resolve_custom_api_returns_node_source_with_extra
  分歧 A：use_custom_api=True 返回临时 ResolvedProviderConfig
  (source="node", extra.custom_api=True, extra.source_detail="node_custom_api")。
- Test 2 test_resolve_custom_api_without_model_raises
  use_custom_api=True 但 config_model 为空 → ValueError("使用自定义 API 时必须指定模型")。
- Test 3 test_resolve_via_aresolve_or_error_returns_resolved
  aresolve_or_error 返回 ResolvedProviderConfig → _resolve 二元组直接转发。
- Test 4 test_resolve_missing_credential_raises_valueerror
  aresolve_or_error 返回 ProviderMissingError → _resolve 转 ValueError
  （"未配置 ... Provider 凭证：..."）。
- Test 5 test_resolve_empty_config_model_falls_back_to_claude_config
  config_model="" 时走 aget_claude_config(project).model fallback。
- Test 6 test_resolve_no_model_anywhere_raises
  config_model="" + claude_config.model="" → ValueError("未配置默认模型...")。
- Test 7 test_execute_maps_missing_credential_to_error_code
  ValueError("未配置 ... 凭证") → NodeResult(failed, output.error_code=
  "provider_credential_missing")。
- Test 8 test_execute_maps_context_window_exceeded_to_error_code
  ContextWindowExceededError → output.error_code="context_window_exceeded"。
- Test 9 test_execute_maps_cancelled_error_to_error_code
  asyncio.CancelledError → output.error_code="execution_cancelled"。
- Test 10 test_execute_tools_empty_when_hook_returns_none
  分歧 B：get_enabled_tools 返回 None → build_langchain_tools 收到 []（而非
  全量注册表）。
- Test 11 test_execute_logs_custom_api_flag
  Pitfall #8：use_custom_api=True 场景 structlog 输出含 custom_api=True，
  且不含 api_base_url / api_key 明文（威胁缓解 security mitigation-01）。

Fixture 策略（contract / Pattern 9）：
- checkpoint-03 已抽取 conftest.py 公共 fixture
  （fake_chat_model_factory / mock_aresolve_ok / mock_aresolve_missing /
  make_minimal_context），本文件统一引用，**禁止**重复定义。
- checkpoint 静态扫描检查这些 fixture 不在本文件被重新定义
  （`grep -c "^def fake_chat_model_factory|^def mock_aresolve_ok|..." == 0`）。
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from agents.langchain_runner import ContextWindowExceededError
from services.provider_config import (
    ProviderMissingError,
    ProviderType,
    ResolvedProviderConfig,
)
from workflows.nodes.ai.base_agent import AIAgentBaseNode
from workflows.nodes.base import ExecutionContext, NodeResult


# ============================================================================
# 最小 AIAgentBaseNode 子类：无工具 + 固定 prompt + iterations=2
# ============================================================================


class _TestAgentNode(AIAgentBaseNode):
    """测试用最小 AIAgentBaseNode 子类（无工具；走通 execute 主干 5 个 hook）。"""

    node_type: ClassVar[str] = "test_agent"

    def get_system_prompt(self, context: ExecutionContext) -> str:
        return "你是测试 agent"

    def get_user_prompt(self, context: ExecutionContext) -> str:
        return "请回答"

    def get_enabled_tools(self, context: ExecutionContext) -> list[str] | None:
        return []

    def get_max_iterations(self, context: ExecutionContext) -> int:
        return 2


# ============================================================================
# Test 1-6：_resolve_api_key_and_model 二元组签名覆盖
# ============================================================================


@pytest.mark.asyncio
async def test_resolve_custom_api_returns_node_source_with_extra() -> None:
    """Test 1：分歧 A 守护 —— use_custom_api=True 构造临时 ResolvedProviderConfig。

    断言：
    - source=="node"（四态之一；严禁 D：不得新增第 5 种枚举值）
    - extra.custom_api is True
    - extra.source_detail == "node_custom_api"
    - credential_id is None
    - provider_type == ProviderType.OPENAI_CHAT
    - 返回 model == config_model
    """
    node = _TestAgentNode()
    resolved, model = await node._resolve_api_key_and_model(
        project=None,
        config_model="gpt-4o",
        use_custom_api=True,
        api_base_url="https://api.example.com/v1",
        api_key="sk-custom-test",
        provider_type="",
    )
    assert resolved.source == "node"
    assert resolved.extra.get("custom_api") is True
    assert resolved.extra.get("source_detail") == "node_custom_api"
    assert resolved.credential_id is None
    assert resolved.provider_type == ProviderType.OPENAI_CHAT
    assert resolved.api_key == "sk-custom-test"
    assert resolved.base_url == "https://api.example.com/v1"
    assert model == "gpt-4o"


@pytest.mark.asyncio
async def test_resolve_custom_api_without_model_raises() -> None:
    """Test 2：use_custom_api=True 但 config_model 为空 → ValueError。"""
    node = _TestAgentNode()
    with pytest.raises(ValueError, match="使用自定义 API 时必须指定模型"):
        await node._resolve_api_key_and_model(
            project=None,
            config_model="",
            use_custom_api=True,
            api_base_url="https://api.example.com/v1",
            api_key="sk-custom-test",
        )


@pytest.mark.asyncio
async def test_resolve_via_aresolve_or_error_returns_resolved(
    monkeypatch: pytest.MonkeyPatch,
    mock_aresolve_ok: Any,
) -> None:
    """Test 3：aresolve_or_error 返回 ResolvedProviderConfig → 二元组直转发。"""
    mock_aresolve_ok(source="system", provider_type="anthropic", api_key="sk-sys")
    node = _TestAgentNode()
    resolved, model = await node._resolve_api_key_and_model(
        project=None,
        config_model="claude-sonnet-4-20250514",
        use_custom_api=False,
        provider_type="anthropic",
    )
    assert resolved.source == "system"
    assert resolved.api_key == "sk-sys"
    assert resolved.provider_type == ProviderType.ANTHROPIC
    assert model == "claude-sonnet-4-20250514"


@pytest.mark.asyncio
async def test_resolve_missing_credential_raises_valueerror(
    monkeypatch: pytest.MonkeyPatch,
    mock_aresolve_missing: Any,
) -> None:
    """Test 4：aresolve_or_error 返回 ProviderMissingError → ValueError 转发。

    message 包含 missing_provider + recommended_action 两字段，供 execute 层
    按 "未配置 ... 凭证" 模式分派到 provider_credential_missing error_code。
    """
    mock_aresolve_missing(
        missing_provider="openai_chat",
        recommended_action="请在系统设置中配置 OpenAI 凭证",
    )
    node = _TestAgentNode()
    with pytest.raises(ValueError) as ei:
        await node._resolve_api_key_and_model(
            project=None,
            config_model="gpt-4o",
            use_custom_api=False,
            provider_type="openai_chat",
        )
    msg = str(ei.value)
    assert "未配置" in msg
    assert "凭证" in msg
    assert "openai_chat" in msg
    assert "请在系统设置中配置" in msg


# initial implementation plan（contract/contract）：aget_claude_config 整体删除，Test 5 / Test 6
# fallback 测试随 claude_config.py 整文件删除一并移除。
# 新 fallback 路径：resolved.extra.default_model（来自 ProviderCredential.default_model）。
# 等价测试由 test_provider_config.py / test_provider_config_v2.py 覆盖。


# ============================================================================
# Test 7-9：execute 错误码分支 5 种映射（contract）
# ============================================================================


@pytest.mark.asyncio
async def test_execute_maps_missing_credential_to_error_code(
    monkeypatch: pytest.MonkeyPatch,
    mock_aresolve_missing: Any,
    make_minimal_context: Any,
) -> None:
    """Test 7：ProviderMissingError → ValueError("未配置 ... 凭证...") →
    NodeResult(failed, output.error_code="provider_credential_missing")。
    """
    mock_aresolve_missing(
        missing_provider="openai_chat",
        recommended_action="请配置凭证",
    )
    ctx = make_minimal_context(node_config={"model": "gpt-4o"})
    result = await _TestAgentNode().execute(ctx)
    assert result.status == "failed"
    assert result.output is not None
    assert result.output.get("error_code") == "provider_credential_missing"


@pytest.mark.asyncio
async def test_execute_maps_context_window_exceeded_to_error_code(
    monkeypatch: pytest.MonkeyPatch,
    mock_aresolve_ok: Any,
    fake_chat_model_factory: Any,
    make_minimal_context: Any,
) -> None:
    """Test 8：ContextWindowExceededError → error_code="context_window_exceeded"。"""
    mock_aresolve_ok(source="system", provider_type="anthropic")
    fake_chat_model_factory(responses=["done"])

    # 让 runner.stream 直接抛 ContextWindowExceededError
    async def _raise_cwe(self: Any, messages: Any) -> Any:
        raise ContextWindowExceededError("budget 100 < tokens 200")
        yield  # pragma: no cover（标记为 async generator）

    monkeypatch.setattr(
        "agents.langchain_runner.LangChainAgentRunner.stream",
        _raise_cwe,
    )

    ctx = make_minimal_context(node_config={"model": "claude-sonnet-4-20250514"})
    result = await _TestAgentNode().execute(ctx)
    assert result.status == "failed"
    assert result.output is not None
    assert result.output.get("error_code") == "context_window_exceeded"
    assert "budget" in str(result.output.get("detail", ""))


@pytest.mark.asyncio
async def test_execute_maps_cancelled_error_to_error_code(
    monkeypatch: pytest.MonkeyPatch,
    mock_aresolve_ok: Any,
    fake_chat_model_factory: Any,
    make_minimal_context: Any,
) -> None:
    """Test 9：asyncio.CancelledError → error_code="execution_cancelled"。"""
    mock_aresolve_ok(source="system", provider_type="anthropic")
    fake_chat_model_factory(responses=["done"])

    async def _raise_cancelled(self: Any, messages: Any) -> Any:
        raise asyncio.CancelledError()
        yield  # pragma: no cover

    monkeypatch.setattr(
        "agents.langchain_runner.LangChainAgentRunner.stream",
        _raise_cancelled,
    )

    ctx = make_minimal_context(node_config={"model": "claude-sonnet-4-20250514"})
    result = await _TestAgentNode().execute(ctx)
    assert result.status == "failed"
    assert result.output is not None
    assert result.output.get("error_code") == "execution_cancelled"


# ============================================================================
# Test 10：分歧 B 守护（None → []，非全量注册表）
# ============================================================================


@pytest.mark.asyncio
async def test_execute_tools_empty_when_hook_returns_none(
    monkeypatch: pytest.MonkeyPatch,
    mock_aresolve_ok: Any,
    fake_chat_model_factory: Any,
    make_minimal_context: Any,
) -> None:
    """Test 10：get_enabled_tools 返回 None → build_langchain_tools 收到 []
    （非 _tool_registry 全量）。覆盖 contract（CONTEXT）→ 分歧 B 锁定。
    """
    mock_aresolve_ok(source="system", provider_type="anthropic")
    fake_chat_model_factory(responses=["done"])

    captured_tool_names: list[list[str]] = []

    def _capturing_build_tools(
        tool_names: list[str], *, injected_values: dict[str, Any] | None = None
    ) -> list[Any]:
        captured_tool_names.append(list(tool_names))
        return []

    monkeypatch.setattr(
        "workflows.nodes.ai.base_agent.build_langchain_tools",
        _capturing_build_tools,
    )

    class _NoneToolsNode(_TestAgentNode):
        def get_enabled_tools(self, context: ExecutionContext) -> list[str] | None:
            return None  # 关键：触发分歧 B 分支

    ctx = make_minimal_context(node_config={"model": "claude-sonnet-4-20250514"})
    result: NodeResult = await _NoneToolsNode().execute(ctx)

    # execute 正常跑完（FakeChatModel 单 turn done → status=="completed"）
    assert result.status == "completed"
    # build_langchain_tools 被调且首参是 []（而非 _tool_registry 全量列表）
    assert captured_tool_names, "build_langchain_tools 应被调用"
    assert captured_tool_names[0] == [], (
        f"None 映射应为空 list（分歧 B 锁定），实际 {captured_tool_names[0]}"
    )


# ============================================================================
# Test 11：Pitfall #8 守护（custom_api 日志字段不泄漏 api_key / api_base_url）
# ============================================================================


@pytest.mark.asyncio
async def test_execute_logs_custom_api_flag(
    monkeypatch: pytest.MonkeyPatch,
    fake_chat_model_factory: Any,
    make_minimal_context: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 11 / Pitfall #8 / security mitigation-01 守护：use_custom_api=True 场景 structlog
    写 agent_node_start event 必须含 custom_api=True 字段，且不得泄漏
    api_key / api_base_url 原值。

    说明：项目 structlog JSON → stdout（project instructions 规定），不经 stdlib logging
    桥接，用 capsys 而非 caplog。
    """
    # use_custom_api 路径不走 aresolve_or_error（分支 1 早返），故不需 mock_aresolve。
    fake_chat_model_factory(responses=["done"])

    ctx = make_minimal_context(
        node_config={
            "model": "gpt-4o",
            "use_custom_api": True,
            "api_base_url": "https://custom-api.internal/v1",
            "api_key": "sk-secret-custom-api-key-work item-LEAK",
        }
    )
    result = await _TestAgentNode().execute(ctx)
    assert result.status == "completed"

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # agent_node_start event 必须含 custom_api=True
    assert "agent_node_start" in combined
    assert "custom_api" in combined, "logger.info 必须包含 custom_api 字段"
    # 明文 api_key / api_base_url 不得出现在日志（Information Disclosure 守护）
    assert "sk-secret-custom-api-key-work item-LEAK" not in combined, (
        "api_key 明文不得出现在 structlog 输出（security mitigation-01）"
    )
    assert "custom-api.internal" not in combined, (
        "api_base_url 不得出现在 structlog 输出（Pitfall #8 守护）"
    )

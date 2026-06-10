"""Context window 预算策略测试。

覆盖 context contract 全部子项：
- contract `_CONTEXT_SAFETY_BUFFER = 800` 硬编码、禁暴露节点配置
- contract 预算公式 ``max_input - max_output - 800``
- contract strict_error 抛 ContextWindowExceededError（错误消息含 5 关键字段）
- contract auto_trim 策略 + trim_messages(strategy='last', include_system=True)
    + BUDGET_WARNING event data 六字段锁（warning_type / trimmed_count /
    budget / original_tokens / model / session_id）
- contract auto_trim 不改变 messages 时不发 BUDGET_WARNING

所有 test 用 FakeChatModel seam（tests/helpers/fake_chat_model.py）不碰网口。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from agents.core.events import BUDGET_WARNING, MESSAGE_COMPLETE
from agents.langchain_runner import (
    _CONTEXT_SAFETY_BUFFER,
    ContextWindowExceededError,
    LangChainAgentRunner,
    LangChainRunnerConfig,
)
from services.model_capabilities import ModelCapabilitiesEntry
from services.provider_config import ProviderType, ResolvedProviderConfig
from tests.helpers.fake_chat_model import FakeChatModel


# ============================================================================
# Fixtures
# ============================================================================


def _make_caps(
    *,
    max_input_tokens: int,
    max_output_tokens: int = 50,
) -> ModelCapabilitiesEntry:
    """构造测试用 capabilities（最小必填字段）。"""
    return ModelCapabilitiesEntry(
        provider="anthropic",
        model="tiny-test",
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        input_cost_per_token=Decimal("0.000003"),
        output_cost_per_token=Decimal("0.000015"),
        supports_function_calling=True,
    )


@pytest.fixture
def resolved_stub() -> ResolvedProviderConfig:
    return ResolvedProviderConfig(
        provider_type=ProviderType.ANTHROPIC,
        api_key="sk-fake",
        base_url="https://api.anthropic.com",
        source="system",
    )


def _make_config(
    resolved: ResolvedProviderConfig,
    *,
    caps: ModelCapabilitiesEntry,
    context_strategy: str = "strict_error",
    max_output_tokens: int | None = None,
) -> LangChainRunnerConfig:
    return LangChainRunnerConfig(
        resolved=resolved,
        model="tiny-test",
        session_id="sess-ctx-budget",
        capabilities=caps,
        context_strategy=context_strategy,  # type: ignore[arg-type]
        max_output_tokens=max_output_tokens,
        max_turns=3,
    )


@pytest.fixture
def long_messages() -> list:
    """生成远超 tiny caps budget 的 messages（数百 token 重复）。"""
    return [
        SystemMessage(content="SYSTEM 指令 " * 200),
        HumanMessage(content="用户输入 " * 200),
    ]


@pytest.fixture
def short_messages() -> list:
    return [HumanMessage(content="hi")]


def _patch_build_chat_model(
    monkeypatch: pytest.MonkeyPatch, fake: FakeChatModel
) -> None:
    monkeypatch.setattr(
        "agents.langchain_runner.build_chat_model",
        lambda *a, **kw: fake,
    )


# ============================================================================
# contract：safety_buffer 硬编码常量
# ============================================================================


def test_safety_buffer_is_800() -> None:
    """contract：_CONTEXT_SAFETY_BUFFER 硬编码 800，禁暴露节点配置。"""
    assert _CONTEXT_SAFETY_BUFFER == 800


def test_context_safety_buffer_not_configurable() -> None:
    """contract：LangChainRunnerConfig 无 context_safety_buffer 字段（禁暴露配置）。"""
    # 检查 dataclass 字段名不含 context_safety_buffer
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(LangChainRunnerConfig)}
    assert "context_safety_buffer" not in field_names


# ============================================================================
# contract：strict_error 策略
# ============================================================================


@pytest.mark.asyncio
async def test_strict_error_raises(
    monkeypatch: pytest.MonkeyPatch,
    resolved_stub: ResolvedProviderConfig,
    long_messages: list,
) -> None:
    """contract：strict_error 策略 + 超预算 → ContextWindowExceededError。"""
    caps = _make_caps(max_input_tokens=100, max_output_tokens=50)
    config = _make_config(
        resolved_stub, caps=caps, context_strategy="strict_error"
    )
    fake = FakeChatModel(responses=["x"])
    _patch_build_chat_model(monkeypatch, fake)

    runner = LangChainAgentRunner(config)
    with pytest.raises(ContextWindowExceededError, match="context too long"):
        async for _ in runner.stream(long_messages):
            pass


@pytest.mark.asyncio
async def test_strict_error_message_format(
    monkeypatch: pytest.MonkeyPatch,
    resolved_stub: ResolvedProviderConfig,
    long_messages: list,
) -> None:
    """contract：ContextWindowExceededError 消息必须含 5 关键字段。"""
    caps = _make_caps(max_input_tokens=100, max_output_tokens=50)
    config = _make_config(
        resolved_stub, caps=caps, context_strategy="strict_error"
    )
    fake = FakeChatModel(responses=["x"])
    _patch_build_chat_model(monkeypatch, fake)

    runner = LangChainAgentRunner(config)
    try:
        async for _ in runner.stream(long_messages):
            pass
        pytest.fail("应抛 ContextWindowExceededError")
    except ContextWindowExceededError as exc:
        msg = str(exc)
        # 5 关键字段均在错误消息中出现（便于前端 implementation contract 降级引导）
        assert "tokens" in msg
        assert "budget" in msg
        assert "max_input=" in msg
        assert "max_output=" in msg
        assert "buffer=" in msg


# ============================================================================
# contract：auto_trim 策略
# ============================================================================


@pytest.mark.asyncio
async def test_auto_trim_yields_warning(
    monkeypatch: pytest.MonkeyPatch,
    resolved_stub: ResolvedProviderConfig,
    long_messages: list,
) -> None:
    """contract：auto_trim 策略 + 超预算 → 发射 BUDGET_WARNING event。"""
    caps = _make_caps(max_input_tokens=100, max_output_tokens=50)
    config = _make_config(
        resolved_stub, caps=caps, context_strategy="auto_trim"
    )
    fake = FakeChatModel(responses=["done"])
    _patch_build_chat_model(monkeypatch, fake)

    runner = LangChainAgentRunner(config)
    events = [e async for e in runner.stream(long_messages)]

    budget_warnings = [e for e in events if e.type == BUDGET_WARNING]
    assert len(budget_warnings) >= 1, (
        f"auto_trim 策略必须发 BUDGET_WARNING，实际 events: "
        f"{[e.type for e in events]}"
    )


@pytest.mark.asyncio
async def test_auto_trim_warning_fields(
    monkeypatch: pytest.MonkeyPatch,
    resolved_stub: ResolvedProviderConfig,
    long_messages: list,
) -> None:
    """contract：BUDGET_WARNING.data 字段锁（前端 SSE 合约冻结）。

    必含字段：warning_type / trimmed_count / budget / original_tokens
    （+ `_inject_metadata` 注入的 model / session_id）。
    """
    caps = _make_caps(max_input_tokens=100, max_output_tokens=50)
    config = _make_config(
        resolved_stub, caps=caps, context_strategy="auto_trim"
    )
    fake = FakeChatModel(responses=["done"])
    _patch_build_chat_model(monkeypatch, fake)

    runner = LangChainAgentRunner(config)
    events = [e async for e in runner.stream(long_messages)]
    budget = [e for e in events if e.type == BUDGET_WARNING][0]

    assert set(budget.data.keys()) >= {
        "warning_type",
        "trimmed_count",
        "budget",
        "original_tokens",
        "model",
        "session_id",
    }
    assert budget.data["warning_type"] == "context_trimmed"
    assert budget.data["trimmed_count"] >= 1
    assert budget.data["original_tokens"] > budget.data["budget"]
    assert budget.data["model"] == "tiny-test"
    assert budget.data["session_id"] == "sess-ctx-budget"


@pytest.mark.asyncio
async def test_auto_trim_preserves_system_message(
    monkeypatch: pytest.MonkeyPatch,
    resolved_stub: ResolvedProviderConfig,
) -> None:
    """contract：auto_trim 使用 `include_system=True`，SystemMessage 必保留。

    构造多轮对话 + 1 个 SystemMessage，trim 后检查 runner._last_trim_meta
    证明触发修剪；并通过 _check_context_window 直接调用验证返回消息含 SystemMessage。
    """
    # budget = 2000 - 50 - 800 = 1150 tokens（正数，可让 trim_messages 收敛到一个子集）
    caps = _make_caps(max_input_tokens=2000, max_output_tokens=50)
    config = _make_config(
        resolved_stub, caps=caps, context_strategy="auto_trim"
    )
    fake = FakeChatModel(responses=["done"])
    _patch_build_chat_model(monkeypatch, fake)

    runner = LangChainAgentRunner(config)

    # 构造 ~2000+ token：SystemMessage ~60 token + 3 轮历史 ~700 token + 最新 ~700 token
    messages: list = [
        SystemMessage(content="system " * 30),  # ~60 token
        HumanMessage(content="old_1 " * 300),   # ~600 token
        HumanMessage(content="old_2 " * 300),   # ~600 token
        HumanMessage(content="latest_question " * 200),  # ~500 token，最新
    ]
    trimmed, flag = runner._check_context_window(messages)
    assert flag is True, f"超预算必须触发修剪；实际 flag={flag}, trimmed={trimmed}"
    # SystemMessage 保留（include_system=True）
    sys_msgs = [m for m in trimmed if isinstance(m, SystemMessage)]
    assert len(sys_msgs) == 1, f"trim 后 SystemMessage 必须保留；实际 {trimmed}"
    # strategy='last' + allow_partial=False：至少保留最新的 HumanMessage
    last_human = [m for m in trimmed if isinstance(m, HumanMessage)]
    assert len(last_human) >= 1, f"strategy='last' 必须保留最新 HumanMessage；实际 {trimmed}"
    # 确认_last_trim_meta 写入
    assert runner._last_trim_meta["trimmed_count"] >= 1
    assert runner._last_trim_meta["budget"] == 1150
    assert runner._last_trim_meta["original_tokens"] > 1150


@pytest.mark.asyncio
async def test_auto_trim_no_effect_when_under_budget(
    monkeypatch: pytest.MonkeyPatch,
    resolved_stub: ResolvedProviderConfig,
    short_messages: list,
) -> None:
    """contract：当 current <= budget 时 auto_trim 不触发，不发 BUDGET_WARNING。"""
    caps = _make_caps(max_input_tokens=100_000, max_output_tokens=4096)
    config = _make_config(
        resolved_stub, caps=caps, context_strategy="auto_trim"
    )
    fake = FakeChatModel(responses=["done"])
    _patch_build_chat_model(monkeypatch, fake)

    runner = LangChainAgentRunner(config)
    events = [e async for e in runner.stream(short_messages)]

    budget_warnings = [e for e in events if e.type == BUDGET_WARNING]
    assert len(budget_warnings) == 0, (
        f"未超预算不得发 BUDGET_WARNING；实际 events: {[e.type for e in events]}"
    )
    # 正常完成
    assert any(e.type == MESSAGE_COMPLETE for e in events)


# ============================================================================
# contract：预算公式边界 + max_output_tokens 覆盖
# ============================================================================


def test_budget_formula_exact(
    resolved_stub: ResolvedProviderConfig,
) -> None:
    """contract：预算公式 budget = max_input - max_output - 800。

    用 _check_context_window 的 strict_error 错误消息解析回 budget 数值核对。
    """
    caps = _make_caps(max_input_tokens=10_000, max_output_tokens=2_000)
    config = _make_config(
        resolved_stub, caps=caps, context_strategy="strict_error"
    )
    # 构造故意超 budget 的 messages（5 万字符约 12.5k token，肯定超 7200 budget）
    huge = [HumanMessage(content="x " * 50_000)]
    runner = LangChainAgentRunner(config)
    with pytest.raises(ContextWindowExceededError) as exc_info:
        runner._check_context_window(huge)

    msg = str(exc_info.value)
    # budget = 10_000 - 2_000 - 800 = 7_200
    assert "budget 7200" in msg
    assert "max_input=10000" in msg
    assert "max_output=2000" in msg
    assert "buffer=800" in msg


def test_max_output_exceeds_budget_strict(
    resolved_stub: ResolvedProviderConfig,
) -> None:
    """contract：config.max_output_tokens 覆盖 caps.max_output_tokens 参与预算计算。

    caps.max_output_tokens=50，但 config.max_output_tokens=80 时 budget 收紧。
    """
    caps = _make_caps(max_input_tokens=1000, max_output_tokens=50)
    # config 显式覆盖 max_output_tokens=80 → budget = 1000 - 80 - 800 = 120
    config = _make_config(
        resolved_stub,
        caps=caps,
        context_strategy="strict_error",
        max_output_tokens=80,
    )
    # ~600 token messages 必然超 budget=120
    runner = LangChainAgentRunner(config)
    msgs = [HumanMessage(content="token " * 600)]
    with pytest.raises(ContextWindowExceededError) as exc_info:
        runner._check_context_window(msgs)
    assert "max_output=80" in str(exc_info.value)
    assert "budget 120" in str(exc_info.value)


@pytest.mark.asyncio
async def test_last_trim_meta_initialized_empty(
    monkeypatch: pytest.MonkeyPatch,
    resolved_stub: ResolvedProviderConfig,
    short_messages: list,
) -> None:
    """contract 集成：__init__ 初始化 _last_trim_meta 为 {}，短消息场景下不变。"""
    caps = _make_caps(max_input_tokens=100_000)
    config = _make_config(
        resolved_stub, caps=caps, context_strategy="auto_trim"
    )
    runner = LangChainAgentRunner(config)
    assert runner._last_trim_meta == {}

    fake = FakeChatModel(responses=["done"])
    _patch_build_chat_model(monkeypatch, fake)
    [e async for e in runner.stream(short_messages)]
    # 未修剪时 _last_trim_meta 仍为 {}
    assert runner._last_trim_meta == {}

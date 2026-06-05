"""implementation 契约：SSE 事件流跨 5 Provider 字段名一致性（20 contract tests）。

参数化维度：
- provider: anthropic / openai_responses / openai_chat / gemini / ollama（5）
- event_type: TEXT_DELTA / TOOL_USE_START / TOOL_USE_RESULT / MESSAGE_COMPLETE（4）
- 5 × 4 = 20 测试用例

外加 2 个跨 Provider 字段一致性 / THINKING 事件 Anthropic 专属性验证。

FakeChatModel 驱动，所有 Provider 共享同一预置响应序列；
断言字段名 keys 跨 Provider 完全一致（context contract data 字段锁定表）。

参考：
- context contract 字段锁
- RESEARCH Example 1 契约测试骨架
- VALIDATION work item
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agents.core.events import (
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    THINKING,
    TOOL_USE_RESULT,
    TOOL_USE_START,
)
from agents.langchain_runner import LangChainAgentRunner, LangChainRunnerConfig
from services.model_capabilities import ModelCapabilitiesEntry
from services.provider_config import ProviderType, ResolvedProviderConfig
from tests.helpers.fake_chat_model import FakeChatModel


# ============================================================================
# 参数化 Provider 列表（5 个）
# ============================================================================


PROVIDER_TYPES = [
    ProviderType.ANTHROPIC,
    ProviderType.OPENAI_RESPONSES,
    ProviderType.OPENAI_CHAT,
    ProviderType.GEMINI,
    ProviderType.OLLAMA,
]


# ============================================================================
# Fixtures
# ============================================================================


@tool
def search(q: str) -> str:
    """查询工具 fake（契约测试 tool_name="search" 统一）。"""
    return f"result: {q}"


def _make_fake() -> FakeChatModel:
    """第一 turn tool_call search(q=x)，第二 turn 文本 'done'。"""
    return FakeChatModel(
        responses=["", "done"],
        tool_calls=[
            [{"name": "search", "args": {"q": "x"}, "id": "t1"}],
            [],
        ],
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
    )


@pytest.fixture
def default_caps() -> ModelCapabilitiesEntry:
    """大 context window，避免契约测试被预算策略干扰。"""
    return ModelCapabilitiesEntry(
        provider="test",
        model="test-model",
        max_input_tokens=100_000,
        max_output_tokens=4096,
        input_cost_per_token=Decimal("0.000003"),
        output_cost_per_token=Decimal("0.000015"),
        supports_function_calling=True,
    )


def _make_config(
    provider: ProviderType,
    caps: ModelCapabilitiesEntry,
) -> LangChainRunnerConfig:
    return LangChainRunnerConfig(
        resolved=ResolvedProviderConfig(
            provider_type=provider,
            api_key="sk-fake",
            base_url="https://example.com",
            source="system",
        ),
        model="test-model",
        session_id="sess-contract",
        capabilities=caps,
        tools=[search],
        max_turns=3,
    )


def _patch_build(monkeypatch: pytest.MonkeyPatch, fake: FakeChatModel) -> None:
    monkeypatch.setattr(
        "agents.langchain_runner.build_chat_model",
        lambda *a, **kw: fake,
    )


# ============================================================================
# 20 契约测试：4 事件 × 5 Provider
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDER_TYPES)
async def test_text_delta_fields_cross_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: ProviderType,
    default_caps: ModelCapabilitiesEntry,
) -> None:
    """work item / contract：TEXT_DELTA.data 字段跨 5 Provider 一致。

    必含 keys：text / model / session_id
    """
    _patch_build(monkeypatch, _make_fake())
    runner = LangChainAgentRunner(_make_config(provider, default_caps))
    events = [e async for e in runner.stream("go")]
    text_events = [e for e in events if e.type == TEXT_DELTA]
    assert len(text_events) >= 1, f"{provider} 未产出 TEXT_DELTA"
    for e in text_events:
        assert set(e.data.keys()) >= {"text", "model", "session_id"}, (
            f"{provider} TEXT_DELTA 缺字段：{e.data.keys()}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDER_TYPES)
async def test_tool_use_start_fields_cross_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: ProviderType,
    default_caps: ModelCapabilitiesEntry,
) -> None:
    """work item / contract：TOOL_USE_START.data 字段跨 5 Provider 一致。

    必含 keys：tool_call_id / tool_name / tool_input / model / session_id
    tool_call_id 非空（Gemini id 缺失时 runner 用 uuid 补）。
    """
    _patch_build(monkeypatch, _make_fake())
    runner = LangChainAgentRunner(_make_config(provider, default_caps))
    events = [e async for e in runner.stream("go")]
    tool_starts = [e for e in events if e.type == TOOL_USE_START]
    assert len(tool_starts) == 1, f"{provider} 应产出 1 个 TOOL_USE_START"
    data = tool_starts[0].data
    assert set(data.keys()) >= {
        "tool_call_id",
        "tool_name",
        "tool_input",
        "model",
        "session_id",
    }, f"{provider} TOOL_USE_START 缺字段：{data.keys()}"
    assert data["tool_name"] == "search"
    assert data["tool_input"] == {"q": "x"}
    assert data["tool_call_id"], "tool_call_id 不得为空"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDER_TYPES)
async def test_tool_use_result_fields_cross_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: ProviderType,
    default_caps: ModelCapabilitiesEntry,
) -> None:
    """work item / contract：TOOL_USE_RESULT.data 字段跨 5 Provider 一致。

    必含 keys：tool_call_id / tool_name / success / model / session_id
    成功时额外含 `result`，失败时额外含 `error`。
    """
    _patch_build(monkeypatch, _make_fake())
    runner = LangChainAgentRunner(_make_config(provider, default_caps))
    events = [e async for e in runner.stream("go")]
    tool_results = [e for e in events if e.type == TOOL_USE_RESULT]
    assert len(tool_results) == 1, f"{provider} 应产出 1 个 TOOL_USE_RESULT"
    data = tool_results[0].data
    assert set(data.keys()) >= {
        "tool_call_id",
        "tool_name",
        "success",
        "model",
        "session_id",
    }, f"{provider} TOOL_USE_RESULT 缺字段：{data.keys()}"
    assert data["success"] is True
    assert "result" in data


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROVIDER_TYPES)
async def test_message_complete_fields_cross_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: ProviderType,
    default_caps: ModelCapabilitiesEntry,
) -> None:
    """work item / contract：MESSAGE_COMPLETE.data 字段跨 5 Provider 一致。

    必含 keys：final_answer / status / usage / model / session_id
    """
    _patch_build(monkeypatch, _make_fake())
    runner = LangChainAgentRunner(_make_config(provider, default_caps))
    events = [e async for e in runner.stream("go")]
    msg_complete = [e for e in events if e.type == MESSAGE_COMPLETE]
    assert len(msg_complete) == 1, (
        f"{provider} 应产出 1 个 MESSAGE_COMPLETE"
    )
    data = msg_complete[0].data
    assert set(data.keys()) >= {
        "final_answer",
        "status",
        "usage",
        "model",
        "session_id",
    }, f"{provider} MESSAGE_COMPLETE 缺字段：{data.keys()}"
    assert data["status"] == "completed"


# ============================================================================
# 额外契约测试：THINKING 专属性 + 字段名跨 Provider 集合相等（铁证）
# ============================================================================


class _ThinkingFake(FakeChatModel):
    """构造含 reasoning content block 的 AIMessage 用于 THINKING 测试。"""

    def __init__(self) -> None:
        # 基类拿一个占位，然后覆盖 messages 迭代器
        super().__init__(responses=["placeholder"])
        msg = AIMessage(
            content=[
                {"type": "reasoning", "reasoning": "让我先思考一下"},
                {"type": "text", "text": "done"},
            ],
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        )
        # 直接替换基类字段（pydantic 允许赋值）
        self.messages = iter([msg])


@pytest.mark.asyncio
async def test_thinking_event_emitted_when_reasoning_block_present(
    monkeypatch: pytest.MonkeyPatch,
    default_caps: ModelCapabilitiesEntry,
) -> None:
    """work item：AIMessage content_blocks 含 reasoning block 时发 THINKING event。

    该事件由 `_adapt_chunk` 分派（content block type=reasoning/thinking），
    非 Provider 专属逻辑；Anthropic extended thinking 与 OpenAI o 系列
    output_token_details.reasoning 均会走此路径。
    """
    _patch_build(monkeypatch, _ThinkingFake())
    runner = LangChainAgentRunner(
        _make_config(ProviderType.ANTHROPIC, default_caps)
    )
    events = [e async for e in runner.stream("go")]
    thinking_events = [e for e in events if e.type == THINKING]
    assert len(thinking_events) >= 1, (
        f"reasoning block 必须触发 THINKING event；实际 events: "
        f"{[e.type for e in events]}"
    )
    assert thinking_events[0].data.get("thinking") == "让我先思考一下"
    # 字段锁
    assert set(thinking_events[0].data.keys()) >= {
        "thinking",
        "model",
        "session_id",
    }


@pytest.mark.asyncio
async def test_fields_names_identical_across_5_providers(
    monkeypatch: pytest.MonkeyPatch,
    default_caps: ModelCapabilitiesEntry,
) -> None:
    """work item 铁律：同一事件类型，5 Provider 发出的 data keys 集合**完全**相等。

    这是前端 SSE 合约不变性最硬的断言；任何 Provider 下字段漂移 CI 立即 fail。
    """
    results: dict[ProviderType, dict[str, set[str]]] = {}
    for provider in PROVIDER_TYPES:
        # 每次重新构造 fake（GenericFakeChatModel.messages 是一次性迭代器）
        fake = _make_fake()
        _patch_build(monkeypatch, fake)
        runner = LangChainAgentRunner(_make_config(provider, default_caps))
        events = [e async for e in runner.stream("go")]
        # 对每个事件类型收集 union keys（多条同类事件时取合集）
        per_event: dict[str, set[str]] = {
            TEXT_DELTA: set(),
            TOOL_USE_START: set(),
            TOOL_USE_RESULT: set(),
            MESSAGE_COMPLETE: set(),
        }
        for e in events:
            if e.type in per_event:
                per_event[e.type] |= set(e.data.keys())
        results[provider] = per_event

    # 以 Anthropic 为基准，逐 Provider 比对（set equality）
    reference = results[ProviderType.ANTHROPIC]
    for provider, got in results.items():
        for event_type, keys in got.items():
            assert keys == reference[event_type], (
                f"{provider} 的 {event_type} data keys {keys} 与 Anthropic 基准 "
                f"{reference[event_type]} 不一致 —— 前端 SSE 合约被破坏"
            )

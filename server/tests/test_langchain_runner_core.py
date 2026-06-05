"""initial implementation plan Task 2：LangChainAgentRunner 核心 ReAct + interrupt + tool flow 测试。

覆盖 Requirement 映射（project docs）：
- work item：stream / result / interrupt 三件套接口 + CancelledError 传播
- work item：朴素 ReAct（不嵌 LangGraph 子图执行器；静态断言在 test_langchain_runner_no_stategraph.py）
- work item：AIMessage.tool_calls 三元组直接消费 + Gemini id 缺失补 uuid
- work item：TEXT_DELTA / THINKING / MESSAGE_COMPLETE data 字段契约

测试 FakeChatModel 策略（本 plan 本 task 的临时方案）：
implementation plan 会抽离到 tests/helpers/fake_chat_model.py；本 plan 先 inline 最小化 FakeChatModel。
基类选 BaseChatModel 直接 override `_agenerate` + `_astream`，避开 GenericFakeChatModel
不支持 tool_calls 的 limitation（只处理 content + additional_kwargs，不处理 AIMessage.tool_calls）。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from langchain_core.callbacks.manager import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from agents.core.events import (
    ERROR,
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    THINKING,
    TOOL_USE_RESULT,
    TOOL_USE_START,
)
from agents.langchain_runner import LangChainAgentRunner, LangChainRunnerConfig
from services.model_capabilities import ModelCapabilitiesEntry
from services.provider_config import ProviderType, ResolvedProviderConfig


# ============================================================================
# FakeChatModel（inline）——本 plan 本 task 临时实现，implementation plan 抽离
# ============================================================================


class _InlineFakeChatModel(BaseChatModel):
    """最小 FakeChatModel：按预置 AIMessage 序列回放，每轮 astream 单 chunk。

    关键行为：
    - `_agenerate` 每次消费一条 AIMessage
    - `_astream` yield 一个包含 content + tool_calls + usage_metadata 的
      AIMessageChunk（ReAct loop 下 `aimsg = None + chunk` 即含 tool_calls）
    - `bind_tools` 返回 self（fake 不真调 tool binding；runner 从预置 tool_calls 回放）

    参考：RESEARCH Pattern 3 work item（implementation plan 会迁入 tests/helpers/fake_chat_model.py）。
    """

    responses: Sequence[AIMessage]
    _cursor: dict[str, int]

    def __init__(self, **data: Any) -> None:
        # pydantic v2 兼容：把私有字段放 data
        super().__init__(**data)
        object.__setattr__(self, "_cursor", {"i": 0})

    @classmethod
    def make(
        cls,
        *,
        responses: Sequence[str] = (),
        tool_calls: Sequence[Sequence[dict[str, Any]]] | None = None,
        usage_metadata: dict[str, Any] | None = None,
        content_blocks_per_response: Sequence[Sequence[dict[str, Any]]] | None = None,
    ) -> "_InlineFakeChatModel":
        tcs = list(tool_calls) if tool_calls else [[]] * len(responses)
        if tcs and len(tcs) != len(responses):
            raise ValueError("responses / tool_calls 长度必须一致")
        cbs = list(content_blocks_per_response) if content_blocks_per_response else [None] * len(responses)
        msgs: list[AIMessage] = []
        for idx, text in enumerate(responses):
            kwargs: dict[str, Any] = {
                "content": text if cbs[idx] is None else list(cbs[idx] or []),
                "tool_calls": list(tcs[idx]),
                "usage_metadata": dict(
                    usage_metadata
                    or {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
                ),
            }
            msgs.append(AIMessage(**kwargs))
        return cls(responses=msgs)

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        idx = self._cursor["i"]
        if idx >= len(self.responses):
            raise StopIteration("no more fake responses")
        self._cursor["i"] = idx + 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])

    async def _astream(  # type: ignore[override]
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        idx = self._cursor["i"]
        if idx >= len(self.responses):
            return
        msg = self.responses[idx]
        self._cursor["i"] = idx + 1
        # 单 chunk 回放：含 content + tool_calls + usage_metadata，保证 runner 累加后
        # `aimsg.tool_calls` 与预置一致
        chunk = ChatGenerationChunk(
            message=AIMessageChunk(
                content=msg.content,
                tool_call_chunks=[
                    {
                        "name": tc.get("name"),
                        "args": __import__("json").dumps(tc.get("args", {})),
                        "id": tc.get("id") or "",
                        "index": i,
                    }
                    for i, tc in enumerate(msg.tool_calls)
                ] if msg.tool_calls else [],
                usage_metadata=msg.usage_metadata,
            )
        )
        yield chunk

    def bind_tools(  # type: ignore[override]
        self,
        tools: Sequence[dict[str, Any] | type | Any | BaseTool],
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        """Stub：返回 self，fake 不真走 binding。"""
        return self


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def resolved_stub() -> ResolvedProviderConfig:
    """最小 ResolvedProviderConfig（runner 测试不在意 api_key 真伪）。"""
    return ResolvedProviderConfig(
        provider_type=ProviderType.ANTHROPIC,
        api_key="sk-fake",
        base_url="https://api.anthropic.com",
        source="system",
    )


@pytest.fixture
def runner_config(resolved_stub: ResolvedProviderConfig) -> LangChainRunnerConfig:
    return LangChainRunnerConfig(
        resolved=resolved_stub,
        model="claude-test",
        session_id="sess-1",
        max_turns=3,
    )


def _patch_model(monkeypatch: pytest.MonkeyPatch, fake: BaseChatModel) -> None:
    """注入 FakeChatModel 到 runner._build_model 调用点（monkeypatch factory）。"""
    monkeypatch.setattr(
        "agents.langchain_runner.build_chat_model",
        lambda *a, **kw: fake,
    )


# ============================================================================
# 测试用例（≥ 15 条）
# ============================================================================


def test_runner_interface(runner_config: LangChainRunnerConfig) -> None:
    """work item：LangChainAgentRunner 含 stream / result / interrupt 三件套 + _last_trim_meta 预留。"""
    runner = LangChainAgentRunner(runner_config)
    assert hasattr(runner, "stream")
    assert hasattr(runner, "result")
    assert hasattr(runner, "interrupt")
    # Wave stub 空 dict；Wave implementation plan auto_trim 分支会写入 {trimmed_count, budget, ...}
    assert runner._last_trim_meta == {}


@pytest.mark.asyncio
async def test_stream_yields_agent_events(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """work item：stream 返回 AsyncGenerator 且至少 yield 一个 MESSAGE_COMPLETE。"""
    fake = _InlineFakeChatModel.make(responses=["hello"])
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("hi")]
    assert any(e.type == MESSAGE_COMPLETE for e in events)
    assert runner.result is not None
    assert runner.result.status == "completed"
    assert runner.result.final_answer == "hello"


@pytest.mark.asyncio
async def test_react_loop_no_langgraph(runner_config: LangChainRunnerConfig) -> None:
    """work item：langchain_runner 模块 __dict__ 不含 StateGraph / Pregel 等子图符号。"""
    import agents.langchain_runner as mod

    assert "StateGraph" not in dir(mod)
    assert "MessageGraph" not in dir(mod)
    assert "Pregel" not in dir(mod)
    assert "create_react_agent" not in dir(mod)


@pytest.mark.asyncio
async def test_max_turns_exhausted(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """work item：max_turns=2 下 tool_calls 无限循环 → result.status='max_iterations'。"""
    # 每轮都带 tool_calls → 总触发下一轮，直到耗尽 max_turns
    tcs = [[{"name": "dummy", "args": {}, "id": "call_1"}]] * 4
    fake = _InlineFakeChatModel.make(responses=["t"] * 4, tool_calls=tcs)
    _patch_model(monkeypatch, fake)

    from langchain_core.tools import tool

    @tool
    def dummy() -> str:  # type: ignore[misc]
        """dummy tool."""
        return "dummy ran"

    runner_config.max_turns = 2
    runner_config.tools = [dummy]
    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    assert runner.result is not None
    assert runner.result.status == "max_iterations"
    # 至少有 2 轮 TOOL_USE_START（每轮各 1 个 tool_call）
    starts = [e for e in events if e.type == TOOL_USE_START]
    assert len(starts) >= 2


@pytest.mark.asyncio
async def test_bind_tools_fake_model(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """work item：tools 非空时走 model.bind_tools(tools) 分支；FakeChatModel.bind_tools 返回 self。"""
    from langchain_core.tools import tool

    @tool
    def search(q: str) -> str:  # type: ignore[misc]
        """search tool."""
        return f"searched {q}"

    fake = _InlineFakeChatModel.make(responses=["ok"])
    _patch_model(monkeypatch, fake)

    runner_config.tools = [search]
    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("hi")]
    # 没有工具调用，但 tools 非空会走 bind_tools 分支 — runner 正常完成
    assert any(e.type == MESSAGE_COMPLETE for e in events)
    assert runner.result is not None
    assert runner.result.status == "completed"


@pytest.mark.asyncio
async def test_gemini_missing_tool_id_filled_with_uuid(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """work item / contract：tool_call id 缺失时 runner 补 uuid.uuid4().hex[:12]（12 hex）。"""
    from langchain_core.tools import tool

    @tool
    def x() -> str:  # type: ignore[misc]
        """x."""
        return "x done"

    # 第一轮带缺 id 的 tool_call，第二轮无 tool_call 终止
    fake = _InlineFakeChatModel.make(
        responses=["t1", "done"],
        tool_calls=[[{"name": "x", "args": {}, "id": ""}], []],
    )
    _patch_model(monkeypatch, fake)

    runner_config.tools = [x]
    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    starts = [e for e in events if e.type == TOOL_USE_START]
    assert len(starts) == 1
    filled = starts[0].data["tool_call_id"]
    assert isinstance(filled, str)
    assert len(filled) == 12
    # 12 hex 字符
    assert all(c in "0123456789abcdef" for c in filled)


@pytest.mark.asyncio
async def test_tool_exception_yields_failed_result(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """contract：工具抛异常 → TOOL_USE_RESULT(success=False) + ToolMessage(status='error') + 下一轮继续。"""
    from langchain_core.tools import tool

    @tool
    def boom() -> str:  # type: ignore[misc]
        """always raises."""
        raise RuntimeError("tool crashed")

    fake = _InlineFakeChatModel.make(
        responses=["try_tool", "recovered"],
        tool_calls=[[{"name": "boom", "args": {}, "id": "c1"}], []],
    )
    _patch_model(monkeypatch, fake)

    runner_config.tools = [boom]
    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    tool_results = [e for e in events if e.type == TOOL_USE_RESULT]
    assert len(tool_results) == 1
    assert tool_results[0].data["success"] is False
    assert "crashed" in tool_results[0].data["error"]

    # 下一轮 LLM 返回无 tool_calls → runner 仍能完成
    assert runner.result is not None
    assert runner.result.status == "completed"


@pytest.mark.asyncio
async def test_interrupt_cancels_stream(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """work item / Pitfall F：interrupt 触发 CancelledError → result.status='interrupted'。"""

    class _SlowFake(_InlineFakeChatModel):
        async def _astream(  # type: ignore[override]
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: AsyncCallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> AsyncIterator[ChatGenerationChunk]:
            await asyncio.sleep(5)  # 阻塞模拟 LLM 长响应
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
                yield chunk

    fake = _SlowFake.make(responses=["delayed"])
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(runner_config)

    async def _drive() -> None:
        async for _ in runner.stream("hi"):
            pass

    task = asyncio.create_task(_drive())
    await asyncio.sleep(0.05)
    await runner.interrupt()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert runner.result is not None
    assert runner.result.status == "interrupted"


@pytest.mark.asyncio
async def test_interrupt_reraises_cancelled_error(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """Pitfall F：interrupt 后 CancelledError 必须 re-raise（外层可 catch）。"""

    class _SlowFake(_InlineFakeChatModel):
        async def _astream(  # type: ignore[override]
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: AsyncCallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> AsyncIterator[ChatGenerationChunk]:
            await asyncio.sleep(5)
            async for chunk in super()._astream(messages, stop, run_manager, **kwargs):
                yield chunk

    fake = _SlowFake.make(responses=["delayed"])
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(runner_config)

    cancelled_raised = False

    async def _drive() -> None:
        nonlocal cancelled_raised
        try:
            async for _ in runner.stream("hi"):
                pass
        except asyncio.CancelledError:
            cancelled_raised = True
            raise

    task = asyncio.create_task(_drive())
    await asyncio.sleep(0.05)
    await runner.interrupt()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cancelled_raised is True


@pytest.mark.asyncio
async def test_tool_calls_normalized_via_aimessage(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """work item：TOOL_USE_START.data 三元组字段与预置 AIMessage.tool_calls 对齐。"""
    from langchain_core.tools import tool

    @tool
    def search(q: str) -> str:  # type: ignore[misc]
        """search tool."""
        return f"got {q}"

    fake = _InlineFakeChatModel.make(
        responses=["t", "ok"],
        tool_calls=[
            [{"name": "search", "args": {"q": "llm"}, "id": "call_abc"}],
            [],
        ],
    )
    _patch_model(monkeypatch, fake)

    runner_config.tools = [search]
    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    starts = [e for e in events if e.type == TOOL_USE_START]
    assert len(starts) == 1
    data = starts[0].data
    assert data["tool_name"] == "search"
    assert data["tool_call_id"] == "call_abc"
    assert data["tool_input"] == {"q": "llm"}


@pytest.mark.asyncio
async def test_ollama_no_tool_support_raises(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """Q2 RESOLVED：capabilities.supports_function_calling=False + tools 非空 → ValueError。"""
    from decimal import Decimal

    from langchain_core.tools import tool

    @tool
    def t() -> str:  # type: ignore[misc]
        """t."""
        return "t"

    no_fc_caps = ModelCapabilitiesEntry(
        provider="ollama",
        model="llama2",
        max_input_tokens=4096,
        max_output_tokens=2048,
        input_cost_per_token=Decimal("0"),
        output_cost_per_token=Decimal("0"),
        supports_function_calling=False,
    )
    fake = _InlineFakeChatModel.make(responses=["x"])
    _patch_model(monkeypatch, fake)

    runner_config.tools = [t]
    runner_config.capabilities = no_fc_caps
    runner = LangChainAgentRunner(runner_config)

    with pytest.raises(ValueError, match="does not support function calling"):
        async for _ in runner.stream("hi"):
            pass


@pytest.mark.asyncio
async def test_text_delta_fields_complete(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """work item 预证：TEXT_DELTA.data 至少含 {text, model, session_id} 三字段（contract）。"""
    fake = _InlineFakeChatModel.make(responses=["hi there"])
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    deltas = [e for e in events if e.type == TEXT_DELTA]
    assert len(deltas) >= 1
    for d in deltas:
        assert "text" in d.data
        assert d.data.get("model") == "claude-test"
        assert d.data.get("session_id") == "sess-1"


@pytest.mark.asyncio
async def test_thinking_event_emitted_for_reasoning_block(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """contract：content_blocks 含 {type:'reasoning', reasoning:...} → THINKING event。"""
    fake = _InlineFakeChatModel.make(
        responses=[""],
        content_blocks_per_response=[
            [
                {"type": "reasoning", "reasoning": "让我想想……"},
                {"type": "text", "text": "答案是 42"},
            ]
        ],
    )
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    thinkings = [e for e in events if e.type == THINKING]
    assert len(thinkings) >= 1
    assert thinkings[0].data.get("thinking") == "让我想想……"
    assert thinkings[0].data.get("model") == "claude-test"
    assert thinkings[0].data.get("session_id") == "sess-1"


@pytest.mark.asyncio
async def test_message_complete_contains_usage(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """contract：MESSAGE_COMPLETE.data.usage 至少含 input + output 两字段映射。"""
    fake = _InlineFakeChatModel.make(
        responses=["ok"],
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        },
    )
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    completes = [e for e in events if e.type == MESSAGE_COMPLETE]
    assert len(completes) == 1
    usage = completes[0].data.get("usage", {})
    assert usage.get("input") == 100
    assert usage.get("output") == 50


@pytest.mark.asyncio
async def test_error_event_on_llm_exception(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """contract：LLM astream 抛异常 → yield ERROR event + result.status='error'（不重试）。"""

    class _BoomFake(_InlineFakeChatModel):
        async def _astream(  # type: ignore[override]
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: AsyncCallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> AsyncIterator[ChatGenerationChunk]:
            raise RuntimeError("provider meltdown")
            yield  # pragma: no cover —— make async generator valid

    fake = _BoomFake.make(responses=["x"])
    _patch_model(monkeypatch, fake)

    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    errors = [e for e in events if e.type == ERROR]
    assert len(errors) == 1
    assert "meltdown" in errors[0].data["message"]
    assert runner.result is not None
    assert runner.result.status == "error"
    assert runner.result.error is not None
    assert "meltdown" in runner.result.error


@pytest.mark.asyncio
async def test_normalize_prompt_accepts_string_and_list(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """contract：prompt 为 str 或 list[BaseMessage] 都能正常运行。"""
    fake = _InlineFakeChatModel.make(responses=["ok"])
    _patch_model(monkeypatch, fake)

    # str 输入
    runner1 = LangChainAgentRunner(runner_config)
    events1 = [e async for e in runner1.stream("hello")]
    assert any(e.type == MESSAGE_COMPLETE for e in events1)

    # list 输入（需要换一个 fake，因为 cursor 已耗尽）
    fake2 = _InlineFakeChatModel.make(responses=["ok"])
    _patch_model(monkeypatch, fake2)
    runner2 = LangChainAgentRunner(runner_config)
    events2 = [
        e async for e in runner2.stream([HumanMessage(content="hello")])
    ]
    assert any(e.type == MESSAGE_COMPLETE for e in events2)


@pytest.mark.asyncio
async def test_tool_use_result_fields_on_success(
    monkeypatch: pytest.MonkeyPatch, runner_config: LangChainRunnerConfig
) -> None:
    """contract：TOOL_USE_RESULT(success=True) 含 {tool_call_id, tool_name, result, model, session_id}。"""
    from langchain_core.tools import tool

    @tool
    def echo(msg: str) -> str:  # type: ignore[misc]
        """echo."""
        return f"echo:{msg}"

    fake = _InlineFakeChatModel.make(
        responses=["t1", "done"],
        tool_calls=[[{"name": "echo", "args": {"msg": "hi"}, "id": "cid-1"}], []],
    )
    _patch_model(monkeypatch, fake)

    runner_config.tools = [echo]
    runner = LangChainAgentRunner(runner_config)
    events = [e async for e in runner.stream("go")]

    results = [e for e in events if e.type == TOOL_USE_RESULT]
    assert len(results) == 1
    d = results[0].data
    assert d["tool_call_id"] == "cid-1"
    assert d["tool_name"] == "echo"
    assert d["success"] is True
    assert d["result"] == "echo:hi"
    assert d["model"] == "claude-test"
    assert d["session_id"] == "sess-1"

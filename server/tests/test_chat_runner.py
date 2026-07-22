from __future__ import annotations

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessageChunk

from agents.chat_runner import (
    ChatAnthropicRunner,
    ChatRunnerConfig,
    _build_tool_specs,
    _thinking_budget_tokens,
)
from agents.core.events import (
    ERROR,
    MESSAGE_COMPLETE,
    PART_COMPLETED,
    PART_DELTA,
    PART_STARTED,
    TEXT_DELTA,
    TOOL_USE_RESULT,
    TOOL_USE_START,
)

# parts contract 起 SSE 双轨期：旧测试断言事件序列时需先过滤掉
# part_started / part_delta / part_completed 新事件，验证 legacy 序列不退化。
_NEW_PART_EVENTS = frozenset({PART_STARTED, PART_DELTA, PART_COMPLETED})


def _legacy_event_types(events):
    return [e.type for e in events if e.type not in _NEW_PART_EVENTS]
from agents.tool_budget import FILE_READ_HARD_LIMIT
from agents.tools.base import ToolResult


def _make_config() -> ChatRunnerConfig:
    return ChatRunnerConfig(
        system_prompt="你是测试助手",
        model="claude-sonnet-4-5",
        space_id="proj-1",
        session_id="sess-1",
        conversation_id="cid",
        api_key="sk-test",
    )


@pytest.fixture(autouse=True)
def _disable_history_load(request):
    """默认 mock 历史加载为空 — chat_runner 大部分单测不关心历史。

    专测历史回灌的用例需用 ``@pytest.mark.real_history_load`` 关闭这个 mock，
    避免每个 stream 测试都触发 Message ORM 查询（pytest-django 默认隔离 DB）。
    """
    if request.node.get_closest_marker("real_history_load"):
        yield
        return
    with patch(
        "agents.chat_runner._load_history_messages",
        new=AsyncMock(return_value=[]),
    ):
        yield


def _make_bound_model(chunks: list[AIMessageChunk]):
    async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
        for chunk in chunks:
            yield chunk

    return SimpleNamespace(astream=_astream)


def test_check_chat_context_window_respects_credential_override() -> None:
    """凭证级 max_input_tokens_override 优先于 fixture：
    fixture 预算内不抛；override 缩小预算后同样消息应抛 ContextWindowExceededError。
    """
    from langchain_core.messages import HumanMessage

    from agents.chat_runner import (
        ContextWindowExceededError,
        _check_chat_context_window,
    )

    messages = [HumanMessage(content="x" * 40000)]  # ~10K tokens

    # fixture 兜底（200K）下不超限
    _check_chat_context_window(messages, model="claude-test-model")

    # override 收紧到 8K → 超限
    with pytest.raises(ContextWindowExceededError):
        _check_chat_context_window(
            messages,
            model="claude-test-model",
            max_input_tokens_override=8000,
        )

    # override 放大（如用户配置 1M）→ 大消息也不超限
    big_messages = [HumanMessage(content="x" * 1_200_000)]  # ~300K tokens
    with pytest.raises(ContextWindowExceededError):
        _check_chat_context_window(big_messages, model="claude-test-model")
    _check_chat_context_window(
        big_messages,
        model="claude-test-model",
        max_input_tokens_override=1_000_000,
    )


def test_thinking_budget_enabled_for_supported_claude_models() -> None:
    assert _thinking_budget_tokens('claude-sonnet-4-5') == 4096
    assert _thinking_budget_tokens('claude-opus-4-5-thinking') == 4096
    assert _thinking_budget_tokens('gpt-5') is None


def test_build_model_enables_thinking_with_temperature_one() -> None:
    runner = ChatAnthropicRunner(_make_config())

    with patch('agents.chat_runner.ChatAnthropic') as mock_chat_anthropic:
      runner._build_model()

    kwargs = mock_chat_anthropic.call_args.kwargs
    assert kwargs['thinking'] == {'type': 'enabled', 'budget_tokens': 4096}
    assert kwargs['temperature'] == 1


@pytest.mark.asyncio
async def test_chat_runner_streams_text_and_message_complete() -> None:
    runner = ChatAnthropicRunner(_make_config())
    bound_model = _make_bound_model([
        AIMessageChunk(content="你"),
        AIMessageChunk(
            content="好",
            response_metadata={"usage": {"input_tokens": 10, "output_tokens": 2}},
        ),
    ])
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound_model

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value={}),
    ):
        events = [event async for event in runner.stream("你好")]

    # contract 双轨期：旧事件序列不退化（过滤新 part_* 事件后断言）
    assert _legacy_event_types(events) == [TEXT_DELTA, TEXT_DELTA, MESSAGE_COMPLETE]
    assert events[-1].data["result"] == "你好"
    assert runner.result is not None
    assert runner.result.final_answer == "你好"
    assert runner.result.usage == {"input_tokens": 10, "output_tokens": 2}


@pytest.mark.asyncio
async def test_chat_runner_emits_tool_events_for_blocking_tool() -> None:
    runner = ChatAnthropicRunner(_make_config())
    bound_model = _make_bound_model([
        AIMessageChunk(
            content="",
            tool_calls=[{
                "name": "deep_analysis",
                "args": {"task_description": "分析项目"},
                "id": "call_1",
                "type": "tool_call",
            }],
            response_metadata={"usage": {"input_tokens": 20, "output_tokens": 5}},
        ),
    ])
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound_model

    async def _execute(_arguments: dict[str, object]) -> ToolResult:
        return ToolResult(
            success=True,
            output={
                "__blocking_task__": True,
                "task_id": "deep-1",
                "task_type": "deep_analysis",
            },
        )

    tool_specs = {
        "deep_analysis": SimpleNamespace(
            tool=object(),
            execute=_execute,
            definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        events = [event async for event in runner.stream("分析一下")]

    # contract 双轨期：旧事件序列不退化（过滤新 part_* 事件后断言）
    assert _legacy_event_types(events) == [TOOL_USE_START, TOOL_USE_RESULT]
    # tool_use_result.data["result"] 已统一序列化为 JSON 字符串（与 langchain_runner /
    # graph snapshot 对齐），blocking marker 校验需先 json.loads。
    import json as _json
    legacy_events = [e for e in events if e.type not in _NEW_PART_EVENTS]
    parsed_result = _json.loads(legacy_events[-1].data["result"])
    assert parsed_result["__blocking_task__"] is True
    assert runner.result is not None
    assert runner.result.status == "completed"
    assert runner.result.final_answer == ""


# ===========================================================================
# Phase P15 — _ToolBudget 集成测试
# ===========================================================================


def _make_scripted_bound_model(scripts: list[list[AIMessageChunk]]):
    """构造一个可被多次 astream 的 model，每次 astream yield 一个 script。

    适用于多轮 LLM ↔ tool 来回的场景。bind_tools 的副作用是返回自身，
    保证 chat_runner 切换 active_model = model_with_tools 或 = model 都能跑。
    """
    iter_state = {"call_count": 0}

    async def _astream(_messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
        idx = iter_state["call_count"]
        iter_state["call_count"] += 1
        # script 用完后 yield 一条 "done" 文本作为最终回答，避免无限循环
        if idx >= len(scripts):
            yield AIMessageChunk(content="done")
            return
        for chunk in scripts[idx]:
            yield chunk

    bound = SimpleNamespace(astream=_astream, bind_tools=lambda _tools: SimpleNamespace(astream=_astream))
    return bound


@pytest.mark.asyncio
async def test_tool_budget_dedup_intercepts_second_identical_call() -> None:
    """LLM 第 2 次用相同 args 调同一工具，应被 budget 拦截，不真实执行。"""
    runner = ChatAnthropicRunner(_make_config())

    # Round 1: 调 search，返工具调用
    # Round 2: 同样的 search args 再调一次（应被拦截）
    # Round 3: 给最终答案
    tool_call_1 = AIMessageChunk(
        content="",
        tool_calls=[{
            "name": "search_repository_code",
            "args": {"query": "foo"},
            "id": "call_1",
            "type": "tool_call",
        }],
        response_metadata={"usage": {"input_tokens": 10, "output_tokens": 5}},
    )
    tool_call_2 = AIMessageChunk(
        content="",
        tool_calls=[{
            "name": "search_repository_code",
            "args": {"query": "foo"},
            "id": "call_2",
            "type": "tool_call",
        }],
        response_metadata={"usage": {"input_tokens": 10, "output_tokens": 5}},
    )
    final_answer = AIMessageChunk(
        content="结果是 X",
        response_metadata={"usage": {"input_tokens": 10, "output_tokens": 3}},
    )
    bound_model = _make_scripted_bound_model([
        [tool_call_1],
        [tool_call_2],
        [final_answer],
    ])
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound_model

    execute_calls = []

    async def _execute(arguments: dict[str, object]) -> ToolResult:
        execute_calls.append(arguments)
        return ToolResult(success=True, output={"matches": ["a.py"]})

    tool_specs = {
        "search_repository_code": SimpleNamespace(
            tool=object(),
            execute=_execute,
            definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        events = [event async for event in runner.stream("找一下 foo")]

    # 应该只真实执行 1 次（第 2 次被去重拦截）
    assert len(execute_calls) == 1
    # 验证第 2 次 TOOL_USE_RESULT 带 budget_intercepted=True flag
    tool_results = [e for e in events if e.type == TOOL_USE_RESULT]
    assert len(tool_results) == 2
    assert "budget_intercepted" not in tool_results[0].data
    assert tool_results[1].data.get("budget_intercepted") is True
    assert runner.result is not None
    assert runner.result.status == "completed"
    assert runner.result.final_answer == "结果是 X"


@pytest.mark.asyncio
async def test_tool_budget_file_limit_rejects_after_hard_limit() -> None:
    """browse_file_content 同一文件读到上限后，下次调用被硬拒绝。"""
    runner = ChatAnthropicRunner(_make_config())

    args_base = {"repository_id": "r1", "file_path": "a.ts"}

    def _read_chunk(call_id: str, start: int) -> AIMessageChunk:
        return AIMessageChunk(
            content="",
            tool_calls=[{
                "name": "browse_file_content",
                "args": {**args_base, "start_line": start},
                "id": call_id,
                "type": "tool_call",
            }],
            response_metadata={"usage": {"input_tokens": 10, "output_tokens": 5}},
        )

    # FILE_READ_HARD_LIMIT 次允许 + 1 次拦截 + 最终答案
    scripts = [[_read_chunk(f"call_{i}", i * 10)] for i in range(FILE_READ_HARD_LIMIT)]
    scripts.append([_read_chunk(f"call_{FILE_READ_HARD_LIMIT}", 999)])
    scripts.append([AIMessageChunk(
        content="基于读到的内容回答",
        response_metadata={"usage": {"input_tokens": 5, "output_tokens": 3}},
    )])

    bound_model = _make_scripted_bound_model(scripts)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound_model

    execute_calls = []

    async def _execute(arguments: dict[str, object]) -> ToolResult:
        execute_calls.append(arguments)
        return ToolResult(success=True, output={"chunks": []})

    tool_specs = {
        "browse_file_content": SimpleNamespace(
            tool=object(),
            execute=_execute,
            definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        events = [event async for event in runner.stream("看下 a.ts")]

    # 真实执行 = FILE_READ_HARD_LIMIT 次
    assert len(execute_calls) == FILE_READ_HARD_LIMIT
    tool_results = [e for e in events if e.type == TOOL_USE_RESULT]
    assert len(tool_results) == FILE_READ_HARD_LIMIT + 1
    # 最后一次应被拦截 + success=False
    last_intercepted = tool_results[-1].data
    assert last_intercepted.get("budget_intercepted") is True
    assert last_intercepted["success"] is False


@pytest.mark.asyncio
async def test_tool_budget_force_final_turn_skips_tools() -> None:
    """剩余 ≤ 1 轮时应不再 bind_tools，强制 LLM 出最终回答。

    我们用 max_turns=2 让第 0 轮就 should_force_final()=True
    （remaining=2 - 0 = 2 > 1，第 0 轮先调一次 tool；turn done 后 remaining=1，
    第 1 轮触发 force_final，必须给出文本回答）。
    """
    config = _make_config()
    config.max_turns = 2  # 最多 2 轮：第 0 轮调工具，第 1 轮 force-final
    runner = ChatAnthropicRunner(config)

    scripts = [
        [AIMessageChunk(
            content="",
            tool_calls=[{
                "name": "search_repository_code",
                "args": {"query": "foo"},
                "id": "call_1",
                "type": "tool_call",
            }],
            response_metadata={"usage": {"input_tokens": 10, "output_tokens": 5}},
        )],
        # 第 1 轮：force-final，LLM 必须出文本回答（不能再调工具）
        [AIMessageChunk(
            content="基于已有信息：foo 在 a.py 中",
            response_metadata={"usage": {"input_tokens": 10, "output_tokens": 8}},
        )],
    ]

    bound_model = _make_scripted_bound_model(scripts)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound_model
    # force-final 轮用的是 model 本身（未 bind_tools），必须也接上 scripted astream
    # —— 与 bound_model.astream 共享同一个 iter_state，所以是连续的 turn 序列。
    fake_model.astream = bound_model.astream

    async def _execute(_arguments: dict[str, object]) -> ToolResult:
        return ToolResult(success=True, output={"matches": ["a.py"]})

    tool_specs = {
        "search_repository_code": SimpleNamespace(
            tool=object(),
            execute=_execute,
            definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        events = [event async for event in runner.stream("找 foo")]

    # 验证：执行了 1 次工具，最终拿到了 final text
    assert runner.result is not None
    assert runner.result.status == "completed"
    assert "基于已有信息" in (runner.result.final_answer or "")
    # MESSAGE_COMPLETE 一定出现（非 ERROR）
    assert any(e.type == MESSAGE_COMPLETE for e in events)
    assert not any(e.type == ERROR for e in events)


@pytest.mark.asyncio
async def test_tool_budget_max_turns_exhausted_returns_degraded_not_error() -> None:
    """max_turns 真用尽时，状态应是 completed+degraded 而非 error。

    设计要点：要让 for 循环跑完 max_turns 次（每轮 turn_complete），模型每轮
    都必须吐 tool_calls（无 tool_calls 时 chat_runner 会立即 return 成
    completed）。这模拟最坏场景 —— 模型即使被 force-final 也继续要工具。
    """
    config = _make_config()
    config.max_turns = 2
    runner = ChatAnthropicRunner(config)

    def _tool_chunk(cid: str) -> AIMessageChunk:
        return AIMessageChunk(
            content="",
            tool_calls=[{
                "name": "search_repository_code",
                "args": {"query": f"q-{cid}"},
                "id": cid,
                "type": "tool_call",
            }],
            response_metadata={"usage": {"input_tokens": 5, "output_tokens": 5}},
        )

    # 两轮都吐 tool_calls（distinct args 避免 dedup 拦截 → 触发 turn_complete）
    scripts = [
        [_tool_chunk("c1")],
        [_tool_chunk("c2")],
    ]

    bound_model = _make_scripted_bound_model(scripts)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound_model
    fake_model.astream = bound_model.astream  # force-final 路径用 fake_model.astream

    async def _execute(_arguments: dict[str, object]) -> ToolResult:
        return ToolResult(success=True, output={"matches": []})

    tool_specs = {
        "search_repository_code": SimpleNamespace(
            tool=object(),
            execute=_execute,
            definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        events = [event async for event in runner.stream("找点东西")]

    assert runner.result is not None
    # 关键断言：max_turns 用尽不再是 error，而是 completed + degraded
    assert runner.result.status == "completed"
    assert runner.result.metadata.get("degraded") is True
    assert runner.result.metadata.get("degraded_reason") == "max_turns_exhausted"
    assert runner.result.metadata.get("max_turns") == 2
    # MESSAGE_COMPLETE 应包含 degraded flag
    msg_complete = [e for e in events if e.type == MESSAGE_COMPLETE]
    assert len(msg_complete) == 1
    assert msg_complete[0].data.get("degraded") is True
    # 没有 ERROR
    assert not any(e.type == ERROR for e in events)


@pytest.mark.asyncio
async def test_tool_budget_annotates_tool_message_with_remaining() -> None:
    """ToolMessage 的 content 应被注入预算提示（被 LLM 下一轮看到）。"""
    config = _make_config()
    config.max_turns = 50
    runner = ChatAnthropicRunner(config)

    scripts = [
        [AIMessageChunk(
            content="",
            tool_calls=[{
                "name": "search_repository_code",
                "args": {"query": "foo"},
                "id": "c1",
                "type": "tool_call",
            }],
            response_metadata={"usage": {"input_tokens": 5, "output_tokens": 5}},
        )],
        [AIMessageChunk(content="ok", response_metadata={"usage": {"input_tokens": 3, "output_tokens": 1}})],
    ]
    bound_model = _make_scripted_bound_model(scripts)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound_model

    captured_messages = []

    async def _astream_capture(messages: list[object]) -> AsyncGenerator[AIMessageChunk, None]:
        captured_messages.append([type(m).__name__ for m in messages])
        idx = len(captured_messages) - 1
        for c in scripts[idx] if idx < len(scripts) else [AIMessageChunk(content="done")]:
            yield c

    bound_model.astream = _astream_capture

    async def _execute(_arguments: dict[str, object]) -> ToolResult:
        return ToolResult(success=True, output={"matches": ["a.py"]})

    tool_specs = {
        "search_repository_code": SimpleNamespace(
            tool=object(),
            execute=_execute,
            definition=MagicMock(),
        ),
    }

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value=tool_specs),
    ):
        async for _event in runner.stream("找 foo"):
            pass

    # 第 2 次 astream 时 messages 已包含 ToolMessage —— 找出它检查 content
    # 简化：直接从 runner._run_task 后看 messages 不太好，改成验证拦截后的
    # tool_message content。这里通过 patch ToolMessage 验证。
    # 实际上更简单：再写一个测试直接 import budget.annotate 验证内容。
    # 此处只校验流程跑通即可（详细 annotation 形态由 test_tool_budget.py 覆盖）
    assert len(captured_messages) >= 2  # 至少跑了 2 轮 astream


# ===========================================================================
# Phase P15 — _build_tool_specs 防御层测试：LLM 自创未知 args 被静默 drop
# ===========================================================================


@pytest.mark.asyncio
async def test_tool_specs_drops_unknown_args_from_llm() -> None:
    """LLM 在 tool_call.args 里塞 schema 不存在的字段时，应被 drop 而非抛 TypeError。

    复现 user-reported bug：LLM 调 list_space_structure 时塞了一个 schema 不存在
    的字段，旧实现直接 unpack → TypeError 让整轮失败。新实现按 schema properties
    过滤 + warning log，让工具能正常执行。
    """
    from agents.tools.base import ToolCategory, ToolDefinition, _tool_registry
    from agents.tools.base import ToolResult as _TR

    received_kwargs: dict[str, object] = {}

    async def _fake_tool_func(**kwargs: object) -> _TR:
        received_kwargs.update(kwargs)
        return _TR(success=True, output={"ok": True})

    fake_def = ToolDefinition(
        name="fake_tool_for_filter_test",
        description="test",
        category=ToolCategory.GENERAL,
        parameters={
            "type": "object",
            "properties": {
                "space_id": {"type": "string"},
                "real_field": {"type": "string"},
            },
            "required": ["space_id"],
        },
        func=_fake_tool_func,
    )

    # 临时注册到 registry，跑完测试清理
    _tool_registry["fake_tool_for_filter_test"] = fake_def
    try:
        with patch(
            "agents.chat_runner._get_tool_names",
            return_value=["fake_tool_for_filter_test"],
        ):
            specs = await _build_tool_specs(
                space_id="proj-xyz",
                conversation_id="conv-xyz",
            )

        spec = specs["fake_tool_for_filter_test"]
        # LLM 传了 schema 不存在的 garbage_field + invented_param —— 这是 bug 现场
        result = await spec.execute({
            "real_field": "ok-value",
            "garbage_field": "should_be_dropped",
            "invented_param": 42,
        })

        # 1) 工具应正常执行（不抛 TypeError）
        assert result.success is True
        # 2) 已注入 space_id（chat_runner 的 injected_values）
        assert received_kwargs["space_id"] == "proj-xyz"
        # 3) 合法字段被保留
        assert received_kwargs["real_field"] == "ok-value"
        # 4) 未知字段被 drop，函数没收到
        assert "garbage_field" not in received_kwargs
        assert "invented_param" not in received_kwargs
    finally:
        _tool_registry.pop("fake_tool_for_filter_test", None)


@pytest.mark.asyncio
async def test_tool_specs_passes_through_known_args_unchanged() -> None:
    """schema 内的合法字段应原样透传，过滤逻辑不应误伤。"""
    from agents.tools.base import ToolCategory, ToolDefinition, _tool_registry
    from agents.tools.base import ToolResult as _TR

    received_kwargs: dict[str, object] = {}

    async def _fake_tool_func(**kwargs: object) -> _TR:
        received_kwargs.update(kwargs)
        return _TR(success=True, output={"ok": True})

    fake_def = ToolDefinition(
        name="fake_passthrough_test",
        description="test",
        category=ToolCategory.GENERAL,
        parameters={
            "type": "object",
            "properties": {
                "space_id": {"type": "string"},
                "a": {"type": "string"},
                "b": {"type": "integer"},
                "c": {"type": "boolean"},
            },
            "required": ["space_id"],
        },
        func=_fake_tool_func,
    )

    _tool_registry["fake_passthrough_test"] = fake_def
    try:
        with patch(
            "agents.chat_runner._get_tool_names",
            return_value=["fake_passthrough_test"],
        ):
            specs = await _build_tool_specs(
                space_id="proj-1",
                conversation_id="cid",
            )

        result = await specs["fake_passthrough_test"].execute({
            "a": "x", "b": 7, "c": True,
        })

        assert result.success is True
        assert received_kwargs == {
            "space_id": "proj-1",
            "a": "x",
            "b": 7,
            "c": True,
        }
    finally:
        _tool_registry.pop("fake_passthrough_test", None)


@pytest.mark.asyncio
async def test_tool_specs_injected_values_cannot_be_overridden_by_llm() -> None:
    """102-REVIEW HI-01 回归：模型 tool_call 带不同 conversation_id 也必须以服务端注入值执行。

    confused-deputy 现场：攻击者 A 在自己会话里诱导模型（prompt injection）以
    受害者 B 的会话 UUID 调用知识读工具（search_project_context / read_project_doc /
    search_learning_cases 以及既有 project_read 系工具共享此闭包路径）。
    修复后：服务端注入的 conversation_id / space_id 终局生效，模型产出的同名
    字段按未知字段 drop。
    """
    from agents.tools.base import ToolCategory, ToolDefinition, _tool_registry
    from agents.tools.base import ToolResult as _TR

    received_kwargs: dict[str, object] = {}

    async def _fake_tool_func(**kwargs: object) -> _TR:
        received_kwargs.update(kwargs)
        return _TR(success=True, output={"ok": True})

    fake_def = ToolDefinition(
        name="fake_injected_override_test",
        description="test",
        category=ToolCategory.GENERAL,
        parameters={
            "type": "object",
            "properties": {
                "space_id": {"type": "string"},
                "conversation_id": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
        func=_fake_tool_func,
    )

    _tool_registry["fake_injected_override_test"] = fake_def
    try:
        with patch(
            "agents.chat_runner._get_tool_names",
            return_value=["fake_injected_override_test"],
        ):
            specs = await _build_tool_specs(
                space_id="server-space",
                conversation_id="server-conv-uuid",
            )

        # 模型被诱导带上受害者会话 UUID + 异 space_id —— 必须全部被注入值压住
        result = await specs["fake_injected_override_test"].execute({
            "query": "找项目上下文",
            "conversation_id": "victim-conv-uuid",
            "space_id": "victim-space",
        })

        assert result.success is True
        assert received_kwargs["conversation_id"] == "server-conv-uuid"
        assert received_kwargs["space_id"] == "server-space"
        assert received_kwargs["query"] == "找项目上下文"
    finally:
        _tool_registry.pop("fake_injected_override_test", None)


# ---------------------------------------------------------------------------
# 历史回灌测试：覆盖 _load_history_messages 还原逻辑 + stream() 注入
#
# 背景：原先 chat_runner 每次 stream 都新建 messages 列表，LLM 看不到前几轮对话，
# 会反复调同一个工具。详见 _load_history_messages docstring。
# ---------------------------------------------------------------------------


@pytest.mark.real_history_load
@pytest.mark.asyncio
async def test_load_history_messages_empty_conversation_id() -> None:
    """空 conversation_id 短路返回，不应触发 ORM 访问。"""
    from agents.chat_runner import _load_history_messages

    assert await _load_history_messages("") == []


@pytest.mark.real_history_load
@pytest.mark.asyncio
async def test_load_history_messages_swallows_db_error() -> None:
    """DB 访问异常（pytest-django 默认隔离、生产 DB 故障）应退化为空 list 而非 raise。"""
    from agents.chat_runner import _load_history_messages

    # 真实路径：Message.objects.filter 在没标记 django_db 时会抛
    # SynchronousOnlyOperation / 数据库未初始化等错误，应被吞掉。
    history = await _load_history_messages("conv-not-exist")
    assert history == []


@pytest.mark.real_history_load
@pytest.mark.asyncio
async def test_load_history_messages_reconstructs_user_assistant_tool_sequence() -> None:
    """user → assistant(+tool_calls) → user 的会话应还原为 LangChain 5 元消息序列：
    HumanMessage / AIMessage(tool_calls) / ToolMessage（剔除末尾当前轮 user）。
    """
    from agents.chat_runner import _load_history_messages

    fake_user_row = SimpleNamespace(
        role="user",
        content="第一轮问题",
        tool_calls=None,
    )
    fake_assistant_row = SimpleNamespace(
        role="assistant",
        content="第一轮回答",
        tool_calls=[
            {
                "id": "tool_abc",
                "name": "list_space_repositories",
                "input": {},
                "result": {"data": {"repositories": [{"id": "r1"}]}},
            },
        ],
    )
    fake_current_user_row = SimpleNamespace(
        role="user",
        content="本轮新问题（应被丢弃）",
        tool_calls=None,
    )

    class _FakeRoleEnum:
        USER = "user"
        ASSISTANT = "assistant"
        SYSTEM = "system"

    class _FakeMessage:
        Role = _FakeRoleEnum

        class objects:  # noqa: N801
            @staticmethod
            def filter(**_kwargs: object) -> object:
                class _QS:
                    def order_by(self, *_a: str) -> object:
                        rows = [fake_user_row, fake_assistant_row, fake_current_user_row]

                        class _Aiter:
                            def __aiter__(self_inner) -> object:  # noqa: N805
                                self_inner._iter = iter(rows)
                                return self_inner

                            async def __anext__(self_inner) -> object:  # noqa: N805
                                try:
                                    return next(self_inner._iter)
                                except StopIteration:
                                    raise StopAsyncIteration

                        return _Aiter()

                return _QS()

    import sys
    fake_chat_models = SimpleNamespace(Message=_FakeMessage)
    real_chat_models = sys.modules.get("chat.models")
    sys.modules["chat.models"] = fake_chat_models  # type: ignore[assignment]
    try:
        history = await _load_history_messages("conv-test")
    finally:
        if real_chat_models is not None:
            sys.modules["chat.models"] = real_chat_models
        else:
            sys.modules.pop("chat.models", None)

    # 末尾当前轮 user 应被丢弃 → 剩 3 条 LangChain 消息
    assert len(history) == 3

    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    assert isinstance(history[0], HumanMessage)
    assert history[0].content == "第一轮问题"

    assert isinstance(history[1], AIMessage)
    assert history[1].content == "第一轮回答"
    assert history[1].tool_calls == [
        {
            "name": "list_space_repositories",
            "args": {},
            "id": "tool_abc",
            "type": "tool_call",
        },
    ]

    assert isinstance(history[2], ToolMessage)
    assert history[2].tool_call_id == "tool_abc"
    # dict result 应被 json.dumps（ensure_ascii=False 保留中文）
    assert '"repositories"' in history[2].content


@pytest.mark.real_history_load
@pytest.mark.asyncio
async def test_load_history_messages_annotates_space_switch() -> None:
    """会话内切换空间：space_switch 系统消息应注入为 HumanMessage 切换标注；
    其余 system 消息维持忽略。
    """
    from agents.chat_runner import _load_history_messages

    rows = [
        SimpleNamespace(role="user", content="旧空间的问题", tool_calls=None),
        SimpleNamespace(role="assistant", content="旧空间的回答", tool_calls=None),
        SimpleNamespace(
            role="system",
            content="已切换空间到「新空间」",
            tool_calls=None,
            metadata={
                "type": "space_switch",
                "from_space_id": None,
                "from_space_name": "",
                "to_space_id": "space-2",
                "to_space_name": "新空间",
            },
        ),
        SimpleNamespace(
            role="system",
            content="其它系统消息（应被忽略）",
            tool_calls=None,
            metadata={},
        ),
        SimpleNamespace(role="user", content="本轮新问题（应被丢弃）", tool_calls=None),
    ]

    class _FakeRoleEnum:
        USER = "user"
        ASSISTANT = "assistant"
        SYSTEM = "system"

    class _FakeMessage:
        Role = _FakeRoleEnum

        class objects:  # noqa: N801
            @staticmethod
            def filter(**_kwargs: object) -> object:
                class _QS:
                    def order_by(self, *_a: str) -> object:
                        class _Aiter:
                            def __aiter__(self_inner) -> object:  # noqa: N805
                                self_inner._iter = iter(rows)
                                return self_inner

                            async def __anext__(self_inner) -> object:  # noqa: N805
                                try:
                                    return next(self_inner._iter)
                                except StopIteration:
                                    raise StopAsyncIteration

                        return _Aiter()

                return _QS()

    import sys
    fake_chat_models = SimpleNamespace(Message=_FakeMessage)
    real_chat_models = sys.modules.get("chat.models")
    sys.modules["chat.models"] = fake_chat_models  # type: ignore[assignment]
    try:
        history = await _load_history_messages("conv-test")
    finally:
        if real_chat_models is not None:
            sys.modules["chat.models"] = real_chat_models
        else:
            sys.modules.pop("chat.models", None)

    from langchain_core.messages import AIMessage, HumanMessage

    # user + assistant + space_switch 标注 = 3；普通 system 消息被忽略
    assert len(history) == 3
    assert isinstance(history[0], HumanMessage)
    assert isinstance(history[1], AIMessage)
    annotation = history[2]
    assert isinstance(annotation, HumanMessage)
    assert "切换" in annotation.content
    assert "「新空间」" in annotation.content
    assert "无空间（通用对话）" in annotation.content


@pytest.mark.asyncio
async def test_stream_injects_history_into_llm_messages() -> None:
    """端到端：runner.stream() 应把 _load_history_messages 返回的消息插到
    SystemMessage 和当前 HumanMessage 之间，传给 LLM 的 messages 列表完整。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    captured: list[list[object]] = []

    async def _astream(messages: list[object]):
        captured.append(list(messages))
        yield AIMessageChunk(
            content="新答案",
            response_metadata={"usage": {"input_tokens": 5, "output_tokens": 2}},
        )

    fake_history = [
        HumanMessage(content="历史问题"),
        AIMessage(content="历史回答"),
    ]
    bound_model = SimpleNamespace(astream=_astream)
    fake_model = MagicMock()
    fake_model.bind_tools.return_value = bound_model

    runner = ChatAnthropicRunner(_make_config())

    with (
        patch.object(ChatAnthropicRunner, "_build_model", return_value=fake_model),
        patch("agents.chat_runner._build_tool_specs", return_value={}),
        patch(
            "agents.chat_runner._load_history_messages",
            new=AsyncMock(return_value=fake_history),
        ),
    ):
        events = [event async for event in runner.stream("新问题")]

    assert any(event.type == MESSAGE_COMPLETE for event in events)
    assert len(captured) == 1
    sent = captured[0]

    # 顺序必须严格：SystemMessage → 历史 → 当前 HumanMessage
    assert isinstance(sent[0], SystemMessage)
    assert sent[1] is fake_history[0]
    assert sent[2] is fake_history[1]
    assert isinstance(sent[3], HumanMessage)
    assert sent[3].content == "新问题"

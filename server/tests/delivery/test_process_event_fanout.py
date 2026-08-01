"""`_emit_event` 内的 SSE fan-out 单测（Phase 110-01，OBS-01）。

本文件锁住四条不变量：

1. **单一出口**：走真实 `transition()` 的转移事件也会被推 —— 7 个 stage handler 与各
   adapter 零改动即自动获得推送（不是靠逐处补推）。
2. **ts 对齐**：推送的 `ts` 与落库行的 `ts` **逐字符相同**，前端去重键依赖此不变量。
3. **出网净化**：自由文本在服务端剥离，但落库行仍是原文（留痕面 ≠ 出网面）。
4. **绝不反噬业务**：writer 不可用的两种形态（`RuntimeError` / `KeyError`）、writer 自身
   抛错、落库失败，四种情形下 `_emit_event` 都不抛、不阻断编排。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
)
from delivery.services import ConvergenceSessionService

pytestmark = pytest.mark.django_db(transaction=True)


class _WriterSpy:
    """记录 writer 收到的 chunk；可配置调用时抛错（用于「writer 抛异常不阻断」）。"""

    def __init__(self, *, raises: BaseException | None = None) -> None:
        self.calls: list[dict] = []
        self._raises = raises

    def __call__(self, chunk: dict) -> None:
        self.calls.append(chunk)
        if self._raises is not None:
            raise self._raises


def _install_writer(monkeypatch: pytest.MonkeyPatch, writer: Any) -> None:
    """顶掉 `langgraph.config.get_stream_writer`，让它返回给定 writer。

    `_fanout_process_event` 用的是**函数内 import**，解析时机在调用点 ⇒ patch 模块属性即可。
    """
    import langgraph.config

    monkeypatch.setattr(langgraph.config, "get_stream_writer", lambda: writer)


def _install_failing_get_stream_writer(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """让 `get_stream_writer()` 本身抛错（区别于 writer 调用时抛错）。"""
    import langgraph.config

    def _raise() -> Any:
        raise exc

    monkeypatch.setattr(langgraph.config, "get_stream_writer", _raise)


async def _make_session(*, with_conversation: bool = True) -> ConvergenceSession:
    return await ConvergenceSessionService().create_session(
        "echo",
        ConvergenceSessionEntrypoint.TOOL_INVOKE,
        conversation_id=uuid.uuid4() if with_conversation else None,
    )


# ============================ 推送成立 ============================


@pytest.mark.asyncio
async def test_fanout_pushes_one_process_event_with_full_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一次 `_emit_event` 恰好产出一条 `process_event`，信封 5 个键齐备。"""
    writer = _WriterSpy()
    _install_writer(monkeypatch, writer)
    session = await _make_session()

    await ConvergenceSessionService()._emit_event("recalled", session, {"hits": 3})

    assert len(writer.calls) == 1
    chunk = writer.calls[0]
    assert chunk["type"] == "process_event"
    assert set(chunk["data"]) == {"event", "session_id", "work_item_id", "ts", "payload"}
    assert chunk["data"]["event"] == "recalled"
    assert chunk["data"]["session_id"] == str(session.id)
    assert chunk["data"]["payload"] == {"hits": 3}


@pytest.mark.asyncio
async def test_pushed_ts_is_identical_to_persisted_ts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 推送的 ts 与落库的 ts 逐字符相同 —— **前端去重键依赖此不变量**。

    `build_envelope()` 自己调 `timezone.now()`，与 `ConvergenceSessionEvent.ts` 的默认值
    分属两次求值；不回填就会让 SSE 那条与快照那条被当成两条不同事件，计数成倍虚高。
    """
    writer = _WriterSpy()
    _install_writer(monkeypatch, writer)
    session = await _make_session()

    await ConvergenceSessionService()._emit_event("recalled", session, {})

    row = await ConvergenceSessionEvent.objects.aget(session_id=session.id, event="recalled")
    assert writer.calls[0]["data"]["ts"] == row.ts.isoformat()


@pytest.mark.asyncio
async def test_outbound_payload_is_sanitized_while_ledger_keeps_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """出网剥离自由文本，落库行仍是原文 —— 留痕面与出网面是两个不同的面。"""
    writer = _WriterSpy()
    _install_writer(monkeypatch, writer)
    session = await _make_session()
    raw = {
        "clarification_id": "c1",
        "question": "你希望改造哪个模块？",
        "summary": "容器产出的自由文本",
    }

    await ConvergenceSessionService()._emit_event("clarification.asked", session, raw)

    pushed = writer.calls[0]["data"]["payload"]
    assert "question" not in pushed
    assert "summary" not in pushed
    assert pushed["clarification_id"] == "c1"

    row = await ConvergenceSessionEvent.objects.aget(
        session_id=session.id, event="clarification.asked"
    )
    assert row.payload == raw


# ============================ 无推送目标：静默跳过 ============================


@pytest.mark.asyncio
async def test_missing_conversation_id_skips_push_but_still_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """workflow / MCP 入口（无 conversation_id）：writer 零调用，落库照常。"""
    writer = _WriterSpy()
    _install_writer(monkeypatch, writer)
    session = await _make_session(with_conversation=False)

    await ConvergenceSessionService()._emit_event("recalled", session, {})

    assert writer.calls == []
    assert await ConvergenceSessionEvent.objects.filter(session_id=session.id).acount() == 1


@pytest.mark.asyncio
async def test_get_stream_writer_runtime_error_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`get_stream_writer()` 抛 `RuntimeError`（压根没有 runnable context）⇒ 不抛、不阻断。"""
    _install_failing_get_stream_writer(
        monkeypatch, RuntimeError("Called get_config outside of a runnable context")
    )
    session = await _make_session()

    await ConvergenceSessionService()._emit_event("recalled", session, {})

    assert await ConvergenceSessionEvent.objects.filter(session_id=session.id).acount() == 1


@pytest.mark.asyncio
async def test_get_stream_writer_key_error_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 `get_stream_writer()` 抛 `KeyError` ⇒ 同样不抛、不阻断。

    「有 runnable context 但不是 langgraph runtime」（如一条普通 LangChain runnable 链）
    走的正是这条：实现 `get_config()[CONF][CONFIG_KEY_RUNTIME]` 在取 runtime 键时抛
    `KeyError`。本用例与上一条**必须都在**——只有 `RuntimeError` 那条时，把外层
    `except Exception` 收紧成 `except RuntimeError` 不会有任何测试变红，而那个改动会让
    这条路径把异常放出去、直接打断编排主流程。
    """
    _install_failing_get_stream_writer(monkeypatch, KeyError("__pregel_runtime"))
    session = await _make_session()

    await ConvergenceSessionService()._emit_event("recalled", session, {})

    assert await ConvergenceSessionEvent.objects.filter(session_id=session.id).acount() == 1


@pytest.mark.asyncio
async def test_writer_raising_does_not_break_emit(monkeypatch: pytest.MonkeyPatch) -> None:
    """writer **被调用时**抛错 ⇒ `_emit_event` 仍正常返回。

    粒度要求：只让 writer 在被调用时抛错（而不是让整个 `_emit_event` 抛错）——无差别抛错
    会让「fan-out 根本没接上」的实现也碰巧通过断言。
    """
    writer = _WriterSpy(raises=ValueError("stream closed"))
    _install_writer(monkeypatch, writer)
    session = await _make_session()

    await ConvergenceSessionService()._emit_event("recalled", session, {})

    assert len(writer.calls) == 1  # 确实推到了 writer（不是压根没接上）
    assert await ConvergenceSessionEvent.objects.filter(session_id=session.id).acount() == 1


@pytest.mark.asyncio
async def test_persist_failure_skips_fanout(monkeypatch: pytest.MonkeyPatch) -> None:
    """落库失败 ⇒ 不推：没有权威 ts 可对齐的事件推出去只会变成孤儿事件。"""
    writer = _WriterSpy()
    _install_writer(monkeypatch, writer)
    session = await _make_session()

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(ConvergenceSessionService, "_persist_event", _boom)

    await ConvergenceSessionService()._emit_event("recalled", session, {})

    assert writer.calls == []


# ============================ 单一出口（零改动即获得推送） ============================


@pytest.mark.asyncio
async def test_real_transition_is_fanned_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """走真实 `transition()` 的转移事件同样被推 —— 证明「stage 零改动即自动获得推送」。

    直接调 `_emit_event` 只能证明 fan-out 函数本身能跑；这条才证明它挂在了唯一出口上。
    """
    writer = _WriterSpy()
    _install_writer(monkeypatch, writer)
    svc = ConvergenceSessionService()
    session = await svc.create_session(
        "echo",
        ConvergenceSessionEntrypoint.TOOL_INVOKE,
        conversation_id=uuid.uuid4(),
    )

    await svc.transition(session, "drafted")

    assert [c["data"]["event"] for c in writer.calls] == ["drafted"]
    assert writer.calls[0]["data"]["session_id"] == str(session.id)

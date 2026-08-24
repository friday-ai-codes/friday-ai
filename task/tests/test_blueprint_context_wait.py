"""短等待原语守护测试（BUS-02，Phase 113-04）。

覆盖：

1. ⭐ **命中即停轮询**：第 2 轮出现目标条目 → `hit is True`、`polls == 2`、`_sleep` 只被调 1 次
   （命中后不再等一轮）。注入 `_now`/`_sleep` 桩，零真实 sleep。
2. ⭐ **超时返正常结果**：恒空 → `hit is False` + `reason == "timeout"`，返回 dict 与**经 MCP
   handler 包装后的返回体都不含 `is_error` 键**（这是本 plan 最核心的可证伪断言：一旦有人把
   超时改成 is_error，agent 会反复重试而不是降级，此处立刻红）。
3. ⭐ **since_seq 递增**：每轮传入的 `since_seq` 等于上一轮返回的 `max_seq`（增量拉取，不重复
   拉全量 —— 轮询是配额敏感路径）。
4. **上界夹紧**：`timeout_minutes=99` 被夹到 5（按轮询次数反推）；`-1` 夹到 0 且立即返回（不无限等）。
5. **向后兼容**：`read_handler is None` → `hit False` + `reason == "tool_unavailable"`，不抛。
6. **瞬时错误不中断等待**：handler 返回带 `is_error` 的体 → 本轮当未命中继续等；但**连续**
   失败达 3 轮 → 提前回 `reason == "tool_error"`（MN-01：持续不可用不得伪装成 `timeout`，
   否则 agent 会把「读不到总线」记成「对方没发布契约」这个错误结论）。
7. `matches_key_pattern` / `literal_prefix` 纯函数。
8. 🔒 **工厂零改动守护**（延续 113-02）：`_make_knowledge_handler` 参数名元组恒等、白名单 10 项、
   `knowledge_allowed_tools()` 10 条、await 工具的 handler **不是**工厂造的那一个。
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from core.blueprint_context_wait import (
    DEFAULT_POLL_INTERVAL_S,
    MAX_TIMEOUT_MINUTES,
    await_blueprint_context,
    literal_prefix,
    matches_key_pattern,
)
from core.knowledge_tools import (
    AWAIT_CONTEXT_TOOL_NAME,
    KNOWLEDGE_TOOL_SCHEMAS,
    _make_knowledge_handler,
    knowledge_allowed_tools,
)

# `asyncio_mode = "auto"`（task/pyproject.toml）—— async 用例无需逐个标记。


# ── 桩 ────────────────────────────────────────────────────────────────────


class _Clock:
    """单调时钟桩：每次 `sleep` 推进虚拟时间，故零真实等待也能触发 deadline。"""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


class _ReadHandler:
    """`read_blueprint_context` handler 替身：按序返回预置 body，记录每轮入参。"""

    def __init__(self, *bodies: Any) -> None:
        self._bodies = list(bodies)
        self.calls: list[dict] = []

    async def __call__(self, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(args))
        index = min(len(self.calls) - 1, len(self._bodies) - 1)
        body = self._bodies[index]
        if isinstance(body, dict) and body.get("__is_error__"):
            return {
                "content": [{"type": "text", "text": "知识工具调用失败: HTTP 502"}],
                "is_error": True,
            }
        return {"content": [{"type": "text", "text": json.dumps(body, ensure_ascii=False)}]}


def _entry(key: str, seq: int) -> dict:
    return {
        "id": f"e-{seq}",
        "key": key,
        "kind": "api_surface",
        "repository_id": "B",
        "content": {"path": "/api/x"},
        "produced_by": "bp-plan-x",
        "seq": seq,
        "status": "active",
        "created_at": "2026-07-30T00:00:00+00:00",
    }


def _empty(max_seq: int) -> dict:
    return {"entries": [], "count": 0, "max_seq": max_seq}


# ===========================================================================
# 1. ⭐ 命中即停轮询
# ===========================================================================


async def test_hit_returns_immediately_and_stops_polling() -> None:
    clock = _Clock()
    handler = _ReadHandler(
        _empty(3),
        {"entries": [_entry("repo:B.api_surface", 4)], "count": 1, "max_seq": 4},
    )

    result = await await_blueprint_context(
        handler,
        "repo:B.api_surface",
        timeout_minutes=3,
        _now=clock.now,
        _sleep=clock.sleep,
    )

    assert result["hit"] is True
    assert result["entry"]["seq"] == 4
    assert result["polls"] == 2
    assert result["max_seq"] == 4
    # 命中后不再等一轮：sleep 只发生在第 1 轮未命中之后。
    assert clock.sleeps == [DEFAULT_POLL_INTERVAL_S]
    assert len(handler.calls) == 2


# ===========================================================================
# 2. ⭐ 超时返正常结果（无 is_error）
# ===========================================================================


async def test_timeout_returns_normal_result_without_is_error() -> None:
    clock = _Clock()
    handler = _ReadHandler(_empty(0))

    result = await await_blueprint_context(
        handler,
        "repo:B.api_surface",
        timeout_minutes=1,
        _now=clock.now,
        _sleep=clock.sleep,
    )

    assert result["hit"] is False
    assert result["reason"] == "timeout"
    # ⭐ 可证伪核心：超时**不是**工具错误。
    assert "is_error" not in result
    assert result["polls"] == 12  # 60s / 5s
    assert result["waited_ms"] >= 60_000


async def test_mcp_handler_wrapper_keeps_timeout_non_error() -> None:
    """经 build 出的 MCP handler 包装后，超时返回体同样不含 `is_error`。"""
    from claude_agent_sdk import SdkMcpTool

    from core.knowledge_tools import _attach_await_handler

    calls: list[dict] = []

    async def read_handler(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(args))
        return {"content": [{"type": "text", "text": json.dumps(_empty(0))}]}

    tools = [
        SdkMcpTool(
            name="read_blueprint_context",
            description="d",
            input_schema={"type": "object"},
            handler=read_handler,
        ),
        SdkMcpTool(
            name=AWAIT_CONTEXT_TOOL_NAME,
            description="d",
            input_schema={"type": "object"},
            handler=read_handler,
        ),
    ]
    await_tool = next(t for t in _attach_await_handler(tools) if t.name == AWAIT_CONTEXT_TOOL_NAME)

    # timeout_minutes=0 → deadline 立即到，零轮询零 sleep（真实时钟也毫秒级返回）。
    resp = await await_tool.handler({"key_pattern": "repo:B.*", "timeout_minutes": 0})

    assert "is_error" not in resp
    body = json.loads(resp["content"][0]["text"])
    assert body["hit"] is False
    assert body["reason"] == "timeout"
    assert calls == []


async def test_mcp_handler_wrapper_missing_key_pattern_is_error() -> None:
    """缺必填参数才是工具错误（与超时语义区分开）。"""
    from claude_agent_sdk import SdkMcpTool

    from core.knowledge_tools import _attach_await_handler

    async def read_handler(args: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(_empty(0))}]}

    tools = [
        SdkMcpTool(
            name=AWAIT_CONTEXT_TOOL_NAME,
            description="d",
            input_schema={"type": "object"},
            handler=read_handler,
        )
    ]
    await_tool = _attach_await_handler(tools)[0]

    resp = await await_tool.handler({})
    assert resp["is_error"] is True


# ===========================================================================
# 3. ⭐ since_seq 增量递增
# ===========================================================================


async def test_since_seq_advances_with_returned_max_seq() -> None:
    clock = _Clock()
    handler = _ReadHandler(_empty(5), _empty(9), _empty(11), _empty(11))

    result = await await_blueprint_context(
        handler,
        "repo:B.api_surface",
        since_seq=2,
        timeout_minutes=1,
        poll_interval_s=20.0,
        _now=clock.now,
        _sleep=clock.sleep,
    )

    assert result["hit"] is False
    passed = [call["since_seq"] for call in handler.calls]
    # 第 1 轮用入参 since_seq；之后每轮等于上一轮返回的 max_seq（不重复拉全量）。
    assert passed == [2, 5, 9]
    assert result["max_seq"] == 11
    # key_prefix 由 pattern 的字面前缀收窄
    assert handler.calls[0]["key_prefix"] == "repo:B.api_surface"
    assert handler.calls[0]["limit"] == 200


# ===========================================================================
# 4. 上界夹紧（无界等待防护，T-113-20）
# ===========================================================================


async def test_timeout_minutes_clamped_to_max() -> None:
    clock = _Clock()
    handler = _ReadHandler(_empty(0))

    result = await await_blueprint_context(
        handler,
        "repo:B.*",
        timeout_minutes=99,
        poll_interval_s=60.0,
        _now=clock.now,
        _sleep=clock.sleep,
    )

    assert result["hit"] is False
    # 60s 一轮 → 恰好 MAX_TIMEOUT_MINUTES 轮，证明 99 被夹到 5。
    assert result["polls"] == MAX_TIMEOUT_MINUTES


async def test_negative_timeout_returns_immediately() -> None:
    clock = _Clock()
    handler = _ReadHandler(_empty(0))

    result = await await_blueprint_context(
        handler, "repo:B.*", timeout_minutes=-1, _now=clock.now, _sleep=clock.sleep
    )

    assert result["hit"] is False
    assert result["polls"] == 0
    assert clock.sleeps == []
    assert len(handler.calls) == 0


# ===========================================================================
# 5/6. 向后兼容与瞬时错误
# ===========================================================================


async def test_missing_read_handler_degrades_without_raising() -> None:
    result = await await_blueprint_context(None, "repo:B.*", since_seq=7)
    assert result == {
        "hit": False,
        "reason": "tool_unavailable",
        "waited_ms": 0,
        "polls": 0,
        "max_seq": 7,
    }


async def test_is_error_body_does_not_abort_wait() -> None:
    """服务端瞬时 502 → 本轮当未命中继续等，下一轮命中仍返回条目。"""
    clock = _Clock()
    handler = _ReadHandler(
        {"__is_error__": True},
        {"entries": [_entry("repo:B.api_surface", 2)], "count": 1, "max_seq": 2},
    )

    result = await await_blueprint_context(
        handler, "repo:B.api_surface", timeout_minutes=2, _now=clock.now, _sleep=clock.sleep
    )

    assert result["hit"] is True
    assert result["polls"] == 2


async def test_persistent_is_error_returns_tool_error_not_timeout() -> None:
    """MN-01：**持续**不可用（配额耗尽 / 401 / 404）必须与「对方还没写」分流。

    连续 3 轮 `is_error` → 提前返回 `reason == "tool_error"`（而不是空转到 deadline 再回
    `timeout`）：`timeout` 的语义是「记录假设并继续」，用它承载「我读不到总线」会让 agent 把
    错误的技术结论写进 RepoPlan。仍**不带** `is_error`（约束 ②，不诱导重试）。
    """
    clock = _Clock()
    handler = _ReadHandler({"__is_error__": True})

    result = await await_blueprint_context(
        handler, "repo:B.api_surface", timeout_minutes=5, _now=clock.now, _sleep=clock.sleep
    )

    assert result["hit"] is False
    assert result["reason"] == "tool_error"
    assert "is_error" not in result
    # 提前返回省下剩余轮次的配额（5 分钟 / 5s = 60 轮，这里只花 3 轮）。
    assert result["polls"] == 3
    assert len(handler.calls) == 3


async def test_intermittent_errors_do_not_trigger_tool_error() -> None:
    """错误不连续（错-好-错-好…）→ 计数被重置，仍等满并回 `timeout`（瞬时抖动不降级）。"""
    clock = _Clock()
    handler = _ReadHandler({"__is_error__": True}, _empty(0), {"__is_error__": True}, _empty(0))

    result = await await_blueprint_context(
        handler,
        "repo:B.api_surface",
        timeout_minutes=1,
        poll_interval_s=20.0,
        _now=clock.now,
        _sleep=clock.sleep,
    )

    assert result["hit"] is False
    assert result["reason"] == "timeout"


async def test_read_handler_exception_does_not_abort_wait() -> None:
    clock = _Clock()
    calls: list[int] = []

    async def flaky(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"entries": [_entry("repo:B.api_surface", 3)], "count": 1, "max_seq": 3}
                    ),
                }
            ]
        }

    result = await await_blueprint_context(
        flaky, "repo:B.api_surface", timeout_minutes=2, _now=clock.now, _sleep=clock.sleep
    )
    assert result["hit"] is True
    assert result["polls"] == 2


async def test_non_matching_entries_are_skipped() -> None:
    clock = _Clock()
    handler = _ReadHandler(
        {"entries": [_entry("repo:C.api_surface", 1)], "count": 1, "max_seq": 1},
        {"entries": [_entry("repo:B.api_surface", 2)], "count": 1, "max_seq": 2},
    )
    result = await await_blueprint_context(
        handler, "repo:B.api_surface", timeout_minutes=2, _now=clock.now, _sleep=clock.sleep
    )
    assert result["hit"] is True
    assert result["entry"]["key"] == "repo:B.api_surface"


# ===========================================================================
# 7. 纯函数
# ===========================================================================


def test_matches_key_pattern_cases() -> None:
    assert matches_key_pattern("repo:B.api_surface", "repo:B.api_surface") is True
    assert matches_key_pattern("repo:B.api_surface", "repo:B.*") is True
    assert matches_key_pattern("repo:C.api_surface", "repo:B.*") is False
    assert matches_key_pattern("anything", "*") is True
    assert matches_key_pattern("anything", "") is False


def test_literal_prefix_cases() -> None:
    assert literal_prefix("repo:B.*") == "repo:B."
    assert literal_prefix("repo:B.api_surface") == "repo:B.api_surface"
    assert literal_prefix("*") == ""


# ===========================================================================
# 8. 🔒 工厂零改动守护
# ===========================================================================


def test_whitelist_is_ten_and_allowed_tools_match() -> None:
    assert len(KNOWLEDGE_TOOL_SCHEMAS) == 13
    assert len(knowledge_allowed_tools()) == 13
    assert f"mcp__friday-knowledge__{AWAIT_CONTEXT_TOOL_NAME}" in knowledge_allowed_tools()
    assert "mcp__friday-knowledge__detect_changes" in knowledge_allowed_tools()


def test_knowledge_handler_factory_signature_unchanged() -> None:
    """🔒 工厂签名参数名元组恒等 —— 给它加参数/改超时都会让这条先红。"""
    params = tuple(inspect.signature(_make_knowledge_handler).parameters)
    assert params == (
        "tool_name",
        "endpoint_base",
        "user_token",
        "session_id",
        "quota",
        "quota_counter",
    )
    source = inspect.getsource(_make_knowledge_handler)
    assert "timeout=60.0" in source


def test_await_tool_handler_is_not_the_factory_handler() -> None:
    """await 工具挂的是自定义包装（复用 read handler 作数据源），不是工厂直造的那一个。"""
    from claude_agent_sdk import SdkMcpTool

    from core.knowledge_tools import _attach_await_handler

    async def read_handler(args: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": json.dumps(_empty(0))}]}

    tools = [
        SdkMcpTool(
            name="read_blueprint_context",
            description="d",
            input_schema={"type": "object"},
            handler=read_handler,
        ),
        SdkMcpTool(
            name=AWAIT_CONTEXT_TOOL_NAME,
            description="d",
            input_schema={"type": "object"},
            handler=read_handler,
        ),
    ]
    patched = _attach_await_handler(tools)
    by_name = {tool.name: tool for tool in patched}
    # read 工具的 handler 原样保留；await 的被替换。
    assert by_name["read_blueprint_context"].handler is read_handler
    assert by_name[AWAIT_CONTEXT_TOOL_NAME].handler is not read_handler

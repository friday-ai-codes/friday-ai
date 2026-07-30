"""短等待原语：`await_blueprint_context` 容器侧有界轮询（BUS-02，Phase 113-04）。

五条约束（改动前先读，每条都有对应守护断言）：

① **容器侧有界轮询，不做服务端长轮询**：轮询复用 ``knowledge_tools`` 公共 handler 工厂造出的
   ``read_blueprint_context`` handler 作数据源。工厂里的 HTTP 超时常量写死且由 10 个工具共享，
   服务端长轮询会撞它，而改它波及全部既有工具 —— 故等待循环放在容器侧，本模块**不新造任何
   HTTP 客户端**（无网络库 import）。
② **超时返回正常结果，不产工具错误标记**：工具错误会诱导 agent 反复重试而不是降级；超时一律返
   ``{"hit": False, "reason": "timeout", …}``，让 agent 记录假设继续（可开澄清线程）。
   本模块唯一一处 ``is_error`` 是**读**上游返回体（判「本轮不可用」），从不**产出**该键。
③ **不发心跳**：knowledge handler 工厂不持有 ``callback``，给它加参数会波及全部既有工具。轮询自身
   每 ``poll_interval_s`` 一次 HTTP 出站即活动性证据，短等待无需额外保活。
④ **向后兼容**：``read_handler`` 为 None（endpoint / token 缺失，整个知识 MCP 未挂）→ 直接返回未命中，
   绝不崩容器。
⑤ **脱敏**：命中条目正文**绝不**进容器侧日志，只记 ``hit`` / ``polls`` / ``waited_ms``（与工厂日志
   字段白名单同口径）。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

# 默认等待 3 分钟；硬上界 5 分钟 —— 更长的依赖应当走「长等待」（waiting_context 结构化退出 +
# 条目就绪后由编排层重派续作），而不是把容器挂在轮询里烧配额。
DEFAULT_TIMEOUT_MINUTES = 3
MAX_TIMEOUT_MINUTES = 5

# 轮询间隔：不用 `ask_user` 的 3.0 —— 那边读的是共享卷本地文件，这里是 HTTP + DB 查询。
DEFAULT_POLL_INTERVAL_S = 5.0

# 单轮增量拉取上限（服务端 `_MAX_READ_LIMIT` 同值，避免被静默夹紧后误判「已拉全」）。
_READ_LIMIT = 200


def matches_key_pattern(key: str, pattern: str) -> bool:
    """key 匹配：精确 / 单 ``*`` 全匹配 / 尾部 ``*`` 前缀匹配（纯函数）。

    与服务端 ``BlueprintContextService.matches_wait_pattern`` 同口径（复制不 import：容器侧
    不依赖服务端代码）。
    """
    key = str(key or "")
    pattern = str(pattern or "")
    if not pattern:
        return False
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return key.startswith(pattern[:-1])
    return key == pattern


def literal_prefix(pattern: str) -> str:
    """取 pattern 的字面前缀（首个 ``*`` 之前），用作服务端 ``key_prefix`` 收窄。"""
    pattern = str(pattern or "")
    star = pattern.find("*")
    return pattern if star == -1 else pattern[:star]


def _parse_handler_body(raw: Any) -> dict[str, Any]:
    """把工厂 handler 的返回体（``{"content":[{"type":"text","text": json_str}]}``）解回 dict。

    解不出一律返回 ``{}`` —— 本轮当未命中继续等，绝不中断等待、绝不抛。
    """
    if not isinstance(raw, dict):
        return {}
    for item in raw.get("content") or []:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text:
            continue
        try:
            body = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(body, dict):
            return body
    return {}


async def await_blueprint_context(
    read_handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None,
    key_pattern: str,
    *,
    kind: str = "",
    since_seq: int = 0,
    timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    _now: Callable[[], float] | None = None,
    _sleep: Callable[[float], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """有界轮询等某条共享上下文出现；命中即返回并**停止轮询**，超时返正常结果。

    ``deadline`` 即 while 上界（无界 while 会让容器永久挂起）；``timeout_minutes`` 被夹到
    ``[0, MAX_TIMEOUT_MINUTES]`` —— 负值立即返回、超界按 5 分钟算。``_now`` / ``_sleep`` /
    ``poll_interval_s`` 可注入，使单测零真实 sleep 也能断言轮询次数。

    Returns:
        恒定形状 dict（下游无需判空分支）：``{"hit": bool, "entry"?: dict, "reason"?: str,
        "waited_ms": int, "polls": int, "max_seq": int}``。**任何路径都不含工具错误标记**。
    """
    now = _now or time.monotonic
    sleep = _sleep or asyncio.sleep
    started_at = now()
    last_seq = max(int(since_seq or 0), 0)

    # 向后兼容（约束 ④）：知识 MCP 整体未挂时不崩、不等，直接告诉 agent「工具不可用」。
    if read_handler is None:
        return {
            "hit": False,
            "reason": "tool_unavailable",
            "waited_ms": 0,
            "polls": 0,
            "max_seq": last_seq,
        }

    bounded_minutes = min(max(0, int(timeout_minutes or 0)), MAX_TIMEOUT_MINUTES)
    deadline = now() + bounded_minutes * 60
    key_prefix = literal_prefix(key_pattern)
    polls = 0

    while now() < deadline:
        polls += 1
        try:
            raw = await read_handler(
                {
                    "key_prefix": key_prefix,
                    "kind": str(kind or ""),
                    "since_seq": last_seq,
                    "limit": _READ_LIMIT,
                }
            )
        except Exception:  # noqa: BLE001 — 单轮读失败当未命中继续等（handler 本已 return-not-raise）
            raw = {}
        # 带工具错误标记的返回体（HTTP 非 200 / 解析失败 / 401）→ 本轮未命中，**不中断等待**：
        # 服务端瞬时不可用不应让长依赖直接降级。
        body = {} if (isinstance(raw, dict) and raw.get("is_error")) else _parse_handler_body(raw)
        entries = body.get("entries")
        entries = entries if isinstance(entries, list) else []
        # 增量幂等：下一轮从本轮 max_seq 之后拉，绝不重复拉全量（约束 ①，配额敏感）。
        max_seq = body.get("max_seq")
        if isinstance(max_seq, int):
            last_seq = max(last_seq, max_seq)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if not matches_key_pattern(str(entry.get("key") or ""), key_pattern):
                continue
            waited_ms = max(int((now() - started_at) * 1000), 0)
            logger.info(
                "blueprint_context_await_finished",
                hit=True,
                polls=polls,
                waited_ms=waited_ms,
            )
            return {
                "hit": True,
                "entry": entry,
                "waited_ms": waited_ms,
                "polls": polls,
                "max_seq": last_seq,
            }
        await sleep(poll_interval_s)

    waited_ms = max(int((now() - started_at) * 1000), 0)
    logger.info(
        "blueprint_context_await_finished",
        hit=False,
        polls=polls,
        waited_ms=waited_ms,
    )
    # 约束 ②：超时是**正常结果**（无 is_error），agent 据此降级而不是重试。
    return {
        "hit": False,
        "reason": "timeout",
        "waited_ms": waited_ms,
        "polls": polls,
        "max_seq": last_seq,
    }

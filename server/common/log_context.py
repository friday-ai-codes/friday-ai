"""用户上下文贯穿（CTX-01/02）的单一收口：structlog.contextvars 绑定/清理 helper。

定位
====
`configure_structlog`（``common/logging.py``）已把 ``merge_contextvars`` 放在
processor 链首位——即"读取当前线程/协程上下文里绑定的字段并并入每条事件"。本模块
**只负责"在正确时机 bind/clear"**：

- 请求入口（中间件）：``bind_request_context`` 绑定 ``request_id`` / ``source`` /
  ``trace_id`` + ``user_id="system"`` 占位；请求结束 ``clear_request_context``。
- DRF 认证之后（mixin）：``rebind_user`` 用 ``request.user`` 补绑真实 ``user_id``。
- 后台任务 worker 入口（durable / background_runner / workflow / apscheduler /
  feishu）：``bind_task_context`` 上下文管理器在干净 ``contextvars.Context()`` 内
  显式 bind（跨线程不自动传播，必须显式重新 bind），退出时 clear。

安全契约（务必遵守）
====================
- **只绑定非敏感字段**（``user_id`` / ``request_id`` / ``source`` / ``trace_id``
  及调用方显式传入的 extra）；明文凭证 / token / 密钥**绝不**进 contextvars
  （沿用 ``access_tokens/context.py`` 范式）。``redact_credentials`` 仍在 renderer
  前兜底。
- ``source`` 经 ``LogSource.normalize`` 受控枚举兜底，非法值回退 ``"system"``，
  防止任意字符串污染 source 基数（T-71-01-03）。
- ``user_id`` 由服务端在 DRF 认证后权威写入，不取自客户端 header（T-71-01-01）。
- 观测代码 best-effort：本模块的 bind/clear 是纯内存操作，调用方在后台链路应
  以"绝不反噬业务"为前提使用 ``bind_task_context``。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum

import structlog


class LogSource(str, Enum):
    """日志来源受控枚举（与 71-CONTEXT「source 取值受控枚举」/ LOGGING-SPEC §3 对齐）。

    取值刻意收敛为有限集合：作为指标/筛选维度时基数可控；任意字符串经
    ``normalize`` 回退 ``system``，杜绝外部输入污染 source 维度。
    """

    REST = "rest"
    MCP = "mcp"
    CHAT_SSE = "chat_sse"
    COMPAT_OPENAI = "compat_openai"
    COMPAT_ANTHROPIC = "compat_anthropic"
    WS = "ws"
    WEBHOOK_FEISHU = "webhook_feishu"
    WEBHOOK_WORKFLOW = "webhook_workflow"
    WEBHOOK_GIT = "webhook_git"
    CONTAINER_CALLBACK = "container_callback"
    DURABLE = "durable"
    BACKGROUND = "background"
    WORKFLOW = "workflow"
    SCHEDULER = "scheduler"
    SYSTEM = "system"

    @classmethod
    def normalize(cls, value: object) -> str:
        """把任意输入归一化为受控枚举字符串；非法值回退 ``"system"``。

        接受枚举成员、其字符串值、或大小写不敏感的名字；都不命中即 ``system``。
        """
        if isinstance(value, cls):
            return value.value
        if value is None:
            return cls.SYSTEM.value
        raw = str(value).strip().lower()
        for member in cls:
            if raw == member.value:
                return member.value
        return cls.SYSTEM.value


def bind_request_context(
    *,
    request_id: str | None,
    source: str,
    trace_id: str | None,
    user_id: str = "system",
) -> None:
    """请求入口绑定四字段到 ``structlog.contextvars``（中间件用）。

    ``request_id`` / ``trace_id`` 为空时各自用 ``uuid4().hex`` 兜底；``source`` 经
    ``LogSource.normalize`` 受控；``user_id`` 默认 ``"system"`` 占位，待 DRF 认证后
    经 ``rebind_user`` 补绑真实用户。
    """
    structlog.contextvars.bind_contextvars(
        request_id=request_id or uuid.uuid4().hex,
        source=LogSource.normalize(source),
        trace_id=trace_id or uuid.uuid4().hex,
        user_id=user_id or "system",
    )


def rebind_user(user_id: str | int | None) -> None:
    """仅更新 ``user_id``（DRF 认证后补绑用）。

    ``None`` / 空值 → **不覆盖**既有占位（保留中间件写入的 ``"system"``），避免未
    认证请求把已有上下文擦成空。
    """
    if user_id is None:
        return
    normalized = str(user_id).strip()
    if not normalized:
        return
    structlog.contextvars.bind_contextvars(user_id=normalized)


def bind_source(source: str) -> None:
    """仅更新 ``source``（让 MCP/compat/chat 等视图声明自己的来源）。"""
    structlog.contextvars.bind_contextvars(source=LogSource.normalize(source))


def clear_request_context() -> None:
    """请求结束清理所有 contextvars（防泄漏到同 worker 的后续请求，T-71-01-04）。"""
    structlog.contextvars.clear_contextvars()


@contextmanager
def bind_task_context(
    *,
    user_id: str | int | None,
    source: str,
    trace_id: str | None = None,
    **extra: object,
) -> Iterator[None]:
    """后台任务 worker 入口的上下文管理器：进入时 bind、退出时 clear。

    **契约**：跨线程 / durable worker / background_runner 用干净
    ``contextvars.Context()``，**不自动传播**调用方上下文，必须经本 helper 显式
    bind（per CTX-02 / LOGGING-SPEC §6.3）。无发起用户记 ``"system"``。

    Args:
        user_id: 发起用户 id（``None`` / 空 → ``"system"``）。
        source: 来源枚举（经 ``LogSource.normalize`` 受控）。
        trace_id: 关联键（空则 ``uuid4().hex`` 兜底）。
        **extra: 额外非敏感字段（如 ``component="scheduler"``）；绝不传凭证。
    """
    normalized_user = str(user_id).strip() if user_id is not None else ""
    structlog.contextvars.bind_contextvars(
        user_id=normalized_user or "system",
        source=LogSource.normalize(source),
        trace_id=trace_id or uuid.uuid4().hex,
        **extra,
    )
    try:
        yield
    finally:
        structlog.contextvars.clear_contextvars()


def resolve_user_id(request: object) -> str:
    """从 DRF ``request`` 取触发用户 id；未认证 / 取不到 → ``"system"``。

    PAT 路径下 DRF 认证已把 token 所有者注入 ``request.user``，故此处与 JWT 会话
    取值一致。**绝不**读取 / 写入任何明文凭证（per 71-CONTEXT「PAT 明文不受影响」）。
    best-effort：任何异常都回退 ``"system"``，绝不反噬主流程。
    """
    try:
        user = getattr(request, "user", None)
        if user is None:
            return "system"
        if not getattr(user, "is_authenticated", False):
            return "system"
        user_id = getattr(user, "id", None)
        return str(user_id) if user_id is not None else "system"
    except Exception:  # noqa: BLE001 — 取用户绝不反噬业务
        return "system"


__all__ = [
    "LogSource",
    "bind_request_context",
    "rebind_user",
    "bind_source",
    "clear_request_context",
    "bind_task_context",
    "resolve_user_id",
]

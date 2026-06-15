"""审计 actor 上下文管理 -- 基于 contextvars 在请求生命周期内传递 actor 信息。

使用 Python 标准库 contextvars（线程/协程安全），由中间件在请求进入时设置、
请求结束时清理。emit_audit_event() 从 contextvars 读取当前 actor。
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditActor:
    """当前请求的 actor 信息（不可变值对象）。"""

    actor_type: str  # "user" / "pat" / "system"
    actor_id: str  # user PK / PAT token_hash / "system" / "anonymous"
    actor_display: str = ""  # 冗余展示名（username / token name）
    ip_address: str | None = None
    request_id: str = ""


_current_actor: contextvars.ContextVar[AuditActor | None] = contextvars.ContextVar(
    "audit_current_actor", default=None
)


def set_current_actor(actor: AuditActor | None) -> contextvars.Token:
    """设置当前请求的 actor（中间件调用）。返回 Token 用于 reset。"""
    return _current_actor.set(actor)


def get_current_actor() -> AuditActor:
    """获取当前 actor；未设置时返回 system 默认值。"""
    return _current_actor.get() or AuditActor(actor_type="system", actor_id="system")


def reset_current_actor(token: contextvars.Token) -> None:
    """重置 contextvar 到 token 之前的值（中间件 finally 块调用）。"""
    _current_actor.reset(token)

"""请求级 PAT 明文上下文通道（RTOOL follow-up：实时明文 PAT 通道）。

唯一合法的 PAT 明文来源是「带 PAT 的实时认证请求」——明文仅在该请求的内存中存在，
DB 只存 sha256 哈希（PAT-02：明文绝不落盘、不可从 DB 取回）。本模块用
``contextvars.ContextVar`` 在请求处理上下文内携带该明文，供同一请求内的 dispatch
边界（如手动触发工作流）按需取出、显式跨线程下传给容器。

安全契约（务必遵守）：
- 明文**绝不**写入任何 ORM 字段 / DB / 持久化 ``WorkflowExecution.context``；
  仅以「运行时瞬态」形式经 ``ExecutionContext`` 内存对象传递。
- 明文**绝不**进日志（调用方只记 ``has_user_token=bool``）。
- ContextVar 仅在请求生命周期内有效：写入方负责在请求结束 ``reset``（见
  ``WorkflowViewSet.execute`` 的 finally），避免泄漏到同 worker 的后续请求。
- 取不到明文（背景触发 / 飞书 / 定时 / JWT 会话）时返回空串，下游降级为不注入
  ``env_FRIDAY_TASK_USER_TOKEN``（向后兼容，无回归）。
"""

from __future__ import annotations

import contextvars

# 仅存「实时请求线程」的 PAT 明文；默认 None（无明文来源）。
_current_pat: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "friday_current_pat_plaintext", default=None
)


def set_request_pat(plaintext: str | None) -> contextvars.Token:
    """写入当前请求的 PAT 明文，返回用于 reset 的 token。

    仅应由「确实持有实时明文」的请求边界调用（如带 ``friday_pat_`` Bearer 的
    认证请求处理路径）。空值写入等价于「无明文来源」。
    """
    return _current_pat.set(plaintext or None)


def get_request_pat() -> str:
    """取出当前请求上下文中的 PAT 明文；无则返回空串。

    绝不从 DB / AccessToken 读取——仅读本 ContextVar（PAT-02）。
    """
    return _current_pat.get() or ""


def reset_request_pat(token: contextvars.Token | None) -> None:
    """请求结束时复位 ContextVar（best-effort，token 失配时静默忽略）。"""
    if token is None:
        return
    try:
        _current_pat.reset(token)
    except (ValueError, LookupError):
        # token 来自不同 Context（如跨线程）时 reset 会抛错；按 best-effort 忽略。
        _current_pat.set(None)

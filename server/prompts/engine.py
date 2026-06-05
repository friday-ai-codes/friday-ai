"""Jinja2 sandbox engine — module-level lazy singleton.

决策依据（CONTEXT.md contract, contract）：
- ImmutableSandboxedEnvironment：禁止 list/dict/set 突变
- StrictUndefined：未定义变量 raise UndefinedError
- extensions=[]：禁用所有 Jinja2 扩展
- autoescape=False：prompt 内容按纯文本，不 HTML escape
"""

from __future__ import annotations

from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment

_ENV: ImmutableSandboxedEnvironment | None = None


def get_jinja_env() -> ImmutableSandboxedEnvironment:
    """返回进程级单例 Jinja2 环境。

    首次调用时构造；后续调用复用。Environment 首次加载 template 后不可修改，
    所以 AppConfig.ready() 时应 pre-warm 一次避免并发 race。
    """
    global _ENV
    if _ENV is None:
        _ENV = ImmutableSandboxedEnvironment(
            undefined=StrictUndefined,
            autoescape=False,
            extensions=[],
            trim_blocks=False,
            lstrip_blocks=False,
            keep_trailing_newline=True,
        )
        # Pre-warm：触发 parser lazy import，首次渲染不会 race
        _ENV.from_string("")
    return _ENV

"""DRF / adrf 视图复用 mixin：认证后补绑真实 user_id（CTX-01）。

``RequestLogContextMiddleware`` 在请求入口只能写 ``user_id="system"`` 占位（中间件
早于 DRF 认证执行）。本 mixin 重写 ``initial``：先 ``super().initial(...)`` 触发
``perform_authentication`` 使 ``request.user`` 就绪，再用 ``rebind_user`` 补绑真实
用户 id；未认证则保持 ``"system"``。

来源声明
========
MCP / compat / chat 等视图可设类属性 ``log_source`` 声明自己的来源（如 MCP view
设 ``log_source = LogSource.MCP``），mixin 在 ``initial`` 内据此覆盖 ``source``。
默认 ``None`` → 不覆盖中间件写入的 ``rest``。

binding 是纯内存操作，对同步 / adrf 异步 ``initial``（adrf 的 ``initial`` 仍为同步
调用）都安全；best-effort，绝不反噬业务。
"""

from __future__ import annotations

from common.log_context import bind_source, rebind_user, resolve_user_id


class LogContextMixin:
    """在 DRF ``initial`` 阶段（认证后）补绑 ``user_id`` / 声明 ``source``。"""

    #: 子类可声明自身来源（``LogSource`` 枚举值字符串）；None → 沿用入口 ``rest``。
    log_source: str | None = None

    def initial(self, request, *args, **kwargs):
        # 先触发 DRF 认证链路，使 request.user 可用。
        result = super().initial(request, *args, **kwargs)
        try:
            if self.log_source is not None:
                bind_source(self.log_source)
            rebind_user(resolve_user_id(request))
        except Exception:  # noqa: BLE001 — 观测代码绝不反噬业务
            pass
        return result


__all__ = ["LogContextMixin"]

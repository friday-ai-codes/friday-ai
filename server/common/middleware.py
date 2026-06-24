"""请求级日志上下文中间件（CTX-01 入口兜底）。

为什么需要"中间件外层兜底 + DRF mixin 补绑"组合
==================================================
Django ``MIDDLEWARE`` 在 DRF 的 ``perform_authentication`` **之前**执行，此时
JWT / PAT 还没解析、拿不到真实 ``request.user``。若在中间件里访问 ``request.user``
会过早触发认证、且仍取不到业务用户。因此本中间件只在入口绑定**可立即得到**的
``request_id`` / ``source`` / ``trace_id`` + ``user_id="system"`` 占位，覆盖整个
请求生命周期；真实 ``user_id`` 留给 ``common.mixins.LogContextMixin`` 在 DRF
认证后经 ``rebind_user`` 补绑。

请求结束 ``finally`` 调 ``clear_request_context()`` 清理 contextvars，防止泄漏到
同 worker 处理的后续请求（T-71-01-04）。

adrf / ASGI 异步栈下本中间件必须支持 async——按 Django 标准"同步+异步双协议"
中间件写法：``__init__`` 探测 ``get_response`` 是否协程，异步路径走 ``__acall__``。
``request_id`` / ``trace_id`` 取自客户端 header（``X-Request-ID`` / ``X-Trace-ID``）
仅作关联键、非鉴权凭证（T-71-01-01）。
"""

from __future__ import annotations

from asgiref.sync import iscoroutinefunction, markcoroutinefunction

from common.log_context import (
    LogSource,
    bind_request_context,
    clear_request_context,
)


class RequestLogContextMiddleware:
    """在请求入口绑定 request_id/source/trace_id + system 占位，请求结束清理。"""

    async_capable = True
    sync_capable = True

    def __init__(self, get_response) -> None:
        self.get_response = get_response
        self.async_mode = iscoroutinefunction(get_response)
        if self.async_mode:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self.async_mode:
            return self.__acall__(request)
        self._bind(request)
        try:
            return self.get_response(request)
        finally:
            clear_request_context()

    async def __acall__(self, request):
        self._bind(request)
        try:
            return await self.get_response(request)
        finally:
            clear_request_context()

    @staticmethod
    def _bind(request) -> None:
        """从 header 取关联键，绑定入口上下文（user_id 先占位 system）。

        best-effort：绑定失败绝不打断请求主链路。
        """
        try:
            headers = getattr(request, "headers", {})
            bind_request_context(
                request_id=headers.get("X-Request-ID"),
                source=LogSource.REST,
                trace_id=headers.get("X-Trace-ID"),
                user_id="system",
            )
        except Exception:  # noqa: BLE001 — 观测代码绝不反噬业务
            pass


__all__ = ["RequestLogContextMiddleware"]

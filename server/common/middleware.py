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

import time

import structlog
from asgiref.sync import iscoroutinefunction, markcoroutinefunction

from common.log_context import (
    LogSource,
    bind_request_context,
    clear_request_context,
)

# 运维轮询 / 健康探针 / 索引 SSE 等"合成流量"路由前缀：命中则打 labels.synthetic=true
# 隔离（Phase 73 SLA 聚合可排除，不污染业务 QPS/错误率统计，per 72-CONTEXT 隔离决策）。
_SYNTHETIC_ROUTE_MARKERS = (
    "/health",
    "/api/system/observability",
    "/api/system/dashboard",
)
_SYNTHETIC_ROUTE_SUFFIXES = ("/poll",)


def _normalize_route(request) -> str:
    """取归一化路由：优先 Django URL pattern（无 path 参数原文），回退去 query 的 path。

    **绝不**落 query string / path 参数原文（基数失控 + 泄漏，T-72-01-01）。
    """
    try:
        match = getattr(request, "resolver_match", None)
        route = getattr(match, "route", None) if match is not None else None
        if route:
            return str(route)[:200]
    except Exception:  # noqa: BLE001
        pass
    path = str(getattr(request, "path", "") or "")
    return path[:200]


def _is_synthetic(path: str) -> bool:
    """判定是否运维轮询/health/索引 SSE 等合成流量路由。"""
    if not path:
        return False
    if any(marker in path for marker in _SYNTHETIC_ROUTE_MARKERS):
        return True
    return any(path.rstrip("/").endswith(suffix) for suffix in _SYNTHETIC_ROUTE_SUFFIXES)


class RequestLogContextMiddleware:
    """在请求入口绑定 request_id/source/trace_id + system 占位，请求结束清理 + 记 RequestMetric。

    Phase 72 扩展：请求结束在 ``finally``（清理 contextvars 之前）记一行 ``RequestMetric``
    （duration/status/error_class/source/route/user_id）。**仅当 source 仍为默认 ``rest``**
    时由中间件记录——MCP / chat SSE / compat / webhook / WS 等专用入口会 ``bind_source``
    改写来源并各自记带 ttft/call_source 的指标行，避免重复计数（每请求恰一行）。
    """

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
        started = time.perf_counter()
        exc: BaseException | None = None
        response = None
        try:
            response = self.get_response(request)
            return response
        except BaseException as e:  # noqa: BLE001 — 捕获用于记指标后原样抛出
            exc = e
            raise
        finally:
            self._record_metric(request, response, started, exc)
            clear_request_context()

    async def __acall__(self, request):
        self._bind(request)
        started = time.perf_counter()
        exc: BaseException | None = None
        response = None
        try:
            response = await self.get_response(request)
            return response
        except BaseException as e:  # noqa: BLE001 — 捕获用于记指标后原样抛出
            exc = e
            raise
        finally:
            self._record_metric(request, response, started, exc)
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

    @staticmethod
    def _record_metric(request, response, started: float, exc: BaseException | None) -> None:
        """请求结束记一行 RequestMetric（best-effort，绝不反噬业务）。

        仅当 contextvars source 仍为默认 ``rest`` 时记录（专用入口已自行埋点）。
        health/poll/索引 SSE 等合成流量打 ``labels.synthetic=true`` 隔离。
        """
        try:
            ctx = structlog.contextvars.get_contextvars()
            source = str(ctx.get("source", LogSource.REST.value) or LogSource.REST.value)
            # 专用入口（mcp/chat_sse/compat/webhook/ws）已 bind_source 并自行记带 ttft/
            # call_source 的指标行；中间件只兜底默认 rest，避免重复计数。
            if source != LogSource.REST.value:
                return

            from common.request_metrics import classify_error, record_request_metric

            duration_ms = max(int((time.perf_counter() - started) * 1000), 0)
            status_code = int(getattr(response, "status_code", 0) or 0)
            if exc is not None and status_code == 0:
                status_code = 500
            error_class = classify_error(status_code=status_code, exc=exc)
            user_id = str(ctx.get("user_id", "system") or "system")

            path = str(getattr(request, "path", "") or "")
            labels = {"synthetic": True} if _is_synthetic(path) else None

            record_request_metric(
                source=LogSource.REST.value,
                route=_normalize_route(request),
                method=str(getattr(request, "method", "") or ""),
                status_code=status_code,
                error_class=error_class,
                duration_ms=duration_ms,
                user_id=user_id,
                labels=labels,
            )
        except Exception:  # noqa: BLE001 — 观测代码绝不反噬业务
            pass


__all__ = ["RequestLogContextMiddleware"]

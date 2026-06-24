"""请求级指标三口径收口 + 写入 helper（RATE-01 / SLA-02 / SLA-04）。

定位
====
本模块是请求侧指标埋点的**单一入口**，与 ``system/metric_sink.py``（队列 + 批量
落库 worker）配套：各 HTTP/MCP/SSE/compat/webhook/WS 入口调用 ``record_request_metric``
组一行 dict 经队列异步落库 ``RequestMetric``，热路径**绝不**打 ORM。

- ``classify_error``：错误三口径（none/system/business/upstream）**单一收口**，供
  72-02 与 Phase 73 复用，避免口径漂移（per 72-CONTEXT / SLA-02）。
- ``record_request_metric`` / ``arecord_request_metric``：best-effort 写入 helper，
  整段 ``try/except: pass``，观测失败**绝不反噬业务**。
- ``labels`` 经 ``_ALLOWED_LABEL_KEYS`` 白名单过滤，杜绝用户输入原文落库
  （基数失控 + 泄漏，T-72-01-01）。
"""

from __future__ import annotations

import structlog
from django.utils import timezone

# labels 受控键白名单：写入前过滤未知键（72-04 召回分层耗时复用）。
# 绝不收用户输入原文（query/body 文本），仅受控枚举/关联键/分层耗时数值。
_ALLOWED_LABEL_KEYS = frozenset(
    {
        "call_source",
        "provider",
        "credential",
        "model",
        "synthetic",
        "run_id",
        "conversation_id",
        "execution_id",
        "node_execution_id",
        "session_id",
        "repository_id",
        "tool_name",
        "ws_event",
        "stage_embedding_ms",
        "stage_sparse_ms",
        "stage_qdrant_ms",
        "stage_rerank_ms",
        "recall_count",
        "top_score",
    }
)

# 上游 provider 错误码：429/529 单列（与 72-02 ModelUsageRecord 口径一致）。
_UPSTREAM_STATUS_CODES = frozenset({429, 529})


def classify_error(
    *,
    status_code: int | None = None,
    exc: BaseException | None = None,
    upstream: bool = False,
) -> str:
    """错误三口径单一收口（per 72-CONTEXT / SLA-02），返回 none/system/business/upstream。

    规则（按优先级）：
    - ``business``：``LLMBusyError``（系统繁忙/并发限流）/ DRF·Django ``PermissionDenied``
      (403) / DRF ``ValidationError`` (400) —— 按规则拒绝的非故障，**排除 SLA 故障**。
    - ``upstream``：上游 provider 错误（``exc`` 带 ``upstream_status_code``/``status_code``
      属性命中 429/529，或调用方显式传 ``upstream=True``）。
    - ``system``：5xx / 未捕获异常（计入 SLA 故障）。
    - ``none``：2xx/3xx 无异常。

    best-effort：分类过程任何异常都回退 ``system``（有异常时）或 ``none``。
    """
    try:
        if exc is not None:
            # business：并发限流 / 权限 / 校验
            if _is_business_exc(exc):
                return "business"
            # upstream：显式标志或异常携带上游码命中 429/529
            if upstream or _is_upstream_exc(exc):
                return "upstream"
            # 其余未捕获异常 → system
            return "system"

        if upstream:
            return "upstream"

        if status_code is None:
            return "none"
        if status_code in _UPSTREAM_STATUS_CODES:
            return "upstream"
        if status_code == 403 or status_code == 400:
            return "business"
        if status_code >= 500:
            return "system"
        return "none"
    except Exception:  # noqa: BLE001 — 分类绝不反噬业务
        return "system" if exc is not None else "none"


def _is_business_exc(exc: BaseException) -> bool:
    """判定异常是否属 business 口径（LLMBusyError / 权限 / 校验）。"""
    # LLMBusyError（lazy import 避免循环依赖）
    try:
        from agents.llm_concurrency import LLMBusyError

        if isinstance(exc, LLMBusyError):
            return True
    except Exception:  # noqa: BLE001
        pass

    # DRF PermissionDenied / ValidationError
    try:
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
        from rest_framework.exceptions import ValidationError as DRFValidationError

        if isinstance(exc, (DRFPermissionDenied, DRFValidationError)):
            return True
    except Exception:  # noqa: BLE001
        pass

    # Django PermissionDenied
    try:
        from django.core.exceptions import PermissionDenied as DjangoPermissionDenied

        if isinstance(exc, DjangoPermissionDenied):
            return True
    except Exception:  # noqa: BLE001
        pass

    return False


def _is_upstream_exc(exc: BaseException) -> bool:
    """判定异常是否携带命中 429/529 的上游状态码。"""
    for attr in ("upstream_status_code", "status_code"):
        code = getattr(exc, attr, None)
        try:
            if code is not None and int(code) in _UPSTREAM_STATUS_CODES:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _filter_labels(labels: dict | None) -> dict:
    """仅保留 ``_ALLOWED_LABEL_KEYS`` 受控键，过滤未知键（防用户输入原文落库）。"""
    if not labels:
        return {}
    return {k: v for k, v in labels.items() if k in _ALLOWED_LABEL_KEYS}


def record_request_metric(
    *,
    source: str,
    route: str = "",
    method: str = "",
    status_code: int = 0,
    error_class: str = "none",
    duration_ms: int | None = None,
    ttft_ms: int | None = None,
    user_id: str | None = None,
    labels: dict | None = None,
) -> None:
    """组一行 RequestMetric dict 并入队（best-effort，绝不反噬业务）。

    ``user_id`` 缺省从 Phase 71 contextvars 读取（无则 ``system``）；``labels`` 经
    白名单过滤。整段 ``try/except: pass``：观测失败绝不打断主流程。
    """
    try:
        from system.metric_sink import enqueue_request_metric

        if user_id is None:
            ctx = structlog.contextvars.get_contextvars()
            user_id = str(ctx.get("user_id", "system") or "system")

        entry = {
            "ts": timezone.now().isoformat(),
            "source": source,
            "route": route or "",
            "method": method or "",
            "status_code": int(status_code or 0),
            "error_class": error_class or "none",
            "duration_ms": duration_ms,
            "ttft_ms": ttft_ms,
            "user_id": user_id,
            "labels": _filter_labels(labels),
        }
        enqueue_request_metric(entry)
    except Exception:  # noqa: BLE001 — 指标写入绝不反噬业务
        pass


async def arecord_request_metric(**kwargs) -> None:
    """async 入口：enqueue 是纯内存非 ORM，直接同步调用（零事件循环阻塞）。"""
    record_request_metric(**kwargs)


__all__ = [
    "classify_error",
    "record_request_metric",
    "arecord_request_metric",
]

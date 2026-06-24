"""请求级指标落库队列 + 后台批量 worker（RATE-01 / SLA-02 / SLA-04）。

镜像 ``system/log_sink.py`` 范式，把 ``RequestMetric`` 精简事件行经内存队列批量落库：

- 入队（``enqueue_request_metric``）是**同步热路径**，绝不做 ORM——只把 dict 推进
  ``deque(maxlen=5000)``，满则丢弃并 ``dropped`` 递增（背压，T-72-01-03）。
- 落库交**专用 daemon 线程**（``friday-metric-sink``）：定时或积压达阈值时 drain
  一批，一次 ``bulk_create`` 写入。
- 四计数（``enqueued`` / ``written`` / ``dropped`` / ``write_failed`` + 当前深度）
  可 ``snapshot_counters()`` 采集（Phase 73 快照消费）。

**绝不反噬业务**：enqueue / 批量 worker 的任何异常都被吞掉，不打断主流程；落库
失败丢批不重试。测试环境不起线程，用 ``flush_now()`` 同步落库（确定性 + 隔离）。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

from django.utils import timezone

# === 模块级配置 ===

_MAXLEN = 5000  # 队列上限：满则丢弃并计数
_BATCH_SIZE = 200  # 积压达此阈值即触发一次落库
_FLUSH_INTERVAL = 1.0  # 兜底定时落库间隔（秒）

# === 队列与锁 ===

# maxlen 自动丢弃**不会**触发计数，故 enqueue 内**手动**判定满丢弃，保证计数精确。
_queue: deque[dict[str, Any]] = deque(maxlen=_MAXLEN)
_lock = threading.Lock()

# === 四计数（加锁更新）===

_enqueued = 0  # 入队成功条数
_written = 0  # 成功落库条数
_dropped = 0  # 队列满丢弃条数
_write_failed = 0  # 落库失败条数

# === 后台 worker 单例 ===

_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()

# RequestMetric 专属列：以下顶层键有专属列，其余忽略（指标不收 raw payload）。
_KNOWN_KEYS = frozenset(
    {
        "ts",
        "source",
        "route",
        "method",
        "status_code",
        "error_class",
        "duration_ms",
        "ttft_ms",
        "user_id",
        "labels",
    }
)

# labels 受控键白名单（与 common/request_metrics._ALLOWED_LABEL_KEYS 对齐）：
# 落库前再过滤一道，杜绝用户输入原文进 jsonb（T-72-01-01）。
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


def enqueue_request_metric(entry: dict[str, Any]) -> None:
    """线程安全入队一条指标行；best-effort，绝不反噬业务。

    ``entry`` 由 ``record_request_metric`` 组好（已过滤 labels）；满则
    ``_dropped += 1`` 不抛；本函数**绝不**做 ORM（落库交后台 worker）。
    """
    global _enqueued, _dropped
    try:
        with _lock:
            if len(_queue) >= _MAXLEN:
                _dropped += 1
                return
            _queue.append(entry)
            _enqueued += 1
        _ensure_worker()
    except Exception:  # noqa: BLE001 — 指标入队绝不反噬业务
        pass


def _is_under_pytest() -> bool:
    """是否处于 pytest 测试会话（复刻 log_sink：测试不起线程，用 flush_now）。

    ``PYTEST_CURRENT_TEST`` 仅在单个用例执行期间存在，导入/采集期为空；故同时检测
    ``sys.modules`` 是否加载 ``pytest``，覆盖整轮会话保证"测试不起线程"稳定生效。
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "pytest" in sys.modules


def _ensure_worker() -> None:
    """懒启动落库 daemon 线程（加锁单例）；测试环境不启动（用 flush_now）。"""
    global _worker_thread
    if _is_under_pytest():
        return
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_worker_loop, name="friday-metric-sink", daemon=True
        )
        _worker_thread.start()


def _worker_loop() -> None:
    """后台循环：定时或积压达阈值时 drain 一批落库。绝不抛（吞掉所有异常）。"""
    while True:
        try:
            time.sleep(_FLUSH_INTERVAL)
            while True:
                batch = _drain(_BATCH_SIZE)
                if not batch:
                    break
                _flush(batch)
        except Exception:  # noqa: BLE001 — 后台 worker 永不反噬业务
            pass


def _drain(limit: int) -> list[dict[str, Any]]:
    """加锁从队列左端取出至多 ``limit`` 条。"""
    batch: list[dict[str, Any]] = []
    with _lock:
        for _ in range(min(limit, len(_queue))):
            batch.append(_queue.popleft())
    return batch


def _flush(batch: list[dict[str, Any]]) -> None:
    """把一批 dict 转 ``RequestMetric`` 并一次 ``bulk_create``。

    成功 ``_written += len``；异常 ``_write_failed += len(batch)`` 并丢批不重试
    （per「永不反噬业务」），绝不抛。
    """
    global _written, _write_failed
    if not batch:
        return
    from system.models import RequestMetric

    try:
        objs = [RequestMetric(**_to_metric(d)) for d in batch]
        RequestMetric.objects.bulk_create(objs)
        with _lock:
            _written += len(objs)
    except Exception:  # noqa: BLE001 — 落库失败丢批 + 计数，绝不反噬业务
        with _lock:
            _write_failed += len(batch)


def _parse_ts(value: Any) -> datetime:
    """解析事件时间：ISO 字符串 → datetime；缺失 / 解析失败 → ``timezone.now()``。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
            return parsed
        except (ValueError, TypeError):
            return timezone.now()
    return timezone.now()


def _coerce_optional_int(value: Any) -> int | None:
    """转可空非负整数（duration_ms/ttft_ms）；非法 → None。"""
    if value is None:
        return None
    try:
        coerced = int(value)
        return coerced if coerced >= 0 else None
    except (TypeError, ValueError):
        return None


def _to_metric(d: dict[str, Any]) -> dict[str, Any]:
    """dict → ``RequestMetric`` 构造 kwargs（截断列宽 + 仅保留受控 labels 键）。"""
    raw_labels = d.get("labels") or {}
    labels = (
        {k: v for k, v in raw_labels.items() if k in _ALLOWED_LABEL_KEYS}
        if isinstance(raw_labels, dict)
        else {}
    )
    return {
        "ts": _parse_ts(d.get("ts")),
        "source": str(d.get("source") or "")[:32],
        "route": str(d.get("route") or "")[:200],
        "method": str(d.get("method") or "")[:10],
        "status_code": max(0, int(d.get("status_code") or 0)),
        "error_class": str(d.get("error_class") or "none")[:10],
        "duration_ms": _coerce_optional_int(d.get("duration_ms")),
        "ttft_ms": _coerce_optional_int(d.get("ttft_ms")),
        "user_id": str(d.get("user_id") or "system")[:64],
        "labels": labels,
    }


def snapshot_counters() -> dict[str, int]:
    """返回队列四计数 + 当前深度（Phase 73 快照采集消费）。"""
    with _lock:
        return {
            "queued": len(_queue),
            "max": _MAXLEN,
            "enqueued": _enqueued,
            "written": _written,
            "dropped": _dropped,
            "write_failed": _write_failed,
        }


def flush_now() -> None:
    """同步把当前队列全部 drain + 落库（测试钩子；生产由 daemon worker 处理）。"""
    while True:
        batch = _drain(_BATCH_SIZE)
        if not batch:
            break
        _flush(batch)


def _reset_for_tests() -> None:
    """清空队列 + 归零计数（测试钩子）。"""
    global _enqueued, _written, _dropped, _write_failed
    with _lock:
        _queue.clear()
        _enqueued = 0
        _written = 0
        _dropped = 0
        _write_failed = 0


__all__ = [
    "enqueue_request_metric",
    "snapshot_counters",
    "flush_now",
]

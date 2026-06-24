"""系统日志落库队列 + 后台批量 worker（LOG-02）。

把（已脱敏的）日志事件经内存队列批量落库到 ``SystemLogEntry``，与
``common/log_buffer.py``（800 条内存环形缓冲，极速兜底）并存：

- 入队（``enqueue_system_log``）是**同步热路径**，绝不做 ORM——只把脱敏后的 dict
  推进 ``deque(maxlen=5000)``，满则丢弃并 ``log_dropped_total`` 递增。
- 落库交**专用 daemon 线程**（``friday-log-sink``）：定时（``_FLUSH_INTERVAL``）或
  积压达阈值（``_BATCH_SIZE``）时 drain 一批，一次 ``bulk_create`` 写入。
- 四计数（``enqueued`` / ``written`` / ``dropped`` / ``write_failed`` + 当前队列深度）
  可 ``snapshot_counters()`` 采集（71-04 计数端点 / Phase 73 快照消费）。

**绝不反噬业务**（沿用 ``log_buffer.append_log`` 的 ``except: pass`` 范式）：
enqueue / 批量 worker 的任何异常都被吞掉，不打断主流程；落库失败丢批不重试。
"""

from __future__ import annotations

import os
import random
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
_sampled_out = 0  # 采样丢弃条数（与队列满 dropped 区分：sampling 类按配置抽样未中）

# 采样进程内计数：(component, event) → 已见条数（首 N 全记的 N 维度）。
_sample_counts: dict[tuple[str, str], int] = {}

# 采样配置默认值（LOG-05 / LOG-06，可经 SettingKeys.LOG_SAMPLING_* 运行时覆盖）。
_DEFAULT_SAMPLING_INITIAL = 50  # 首 N 条全记
_DEFAULT_SAMPLING_RATE = 0.1  # 之后按比例

# === 后台 worker 单例 ===

_worker_thread: threading.Thread | None = None
_worker_lock = threading.Lock()

# 落库内容映射：以下顶层键有专属列，其余收进 payload。
_KNOWN_KEYS = frozenset(
    {
        "ts",
        "timestamp",
        "level",
        "component",
        "category",
        "event",
        "message",
        "user_id",
        "source",
        "trace_id",
        "request_id",
    }
)

# 关联键：从 payload 提取到 correlation（供 71-05 下钻 + 三链关联，不复制数据）。
_CORRELATION_KEYS = frozenset(
    {"run_id", "conversation_id", "execution_id", "node_execution_id", "session_id"}
)


def _should_record(entry: dict[str, Any]) -> bool:
    """采样判定（LOG-05）：``caller`` 全量记录；``sampling``（或缺省）按运行时配置抽样。

    - ``category=="caller"`` → 始终 ``True``（用户可归因调用绝不采样丢弃，LOGGING-SPEC §2）。
    - 其余按 ``(component, event)`` 维度：首 ``LOG_SAMPLING_INITIAL`` 条全记，之后
      ``random.random() < LOG_SAMPLING_RATE`` 才记。

    配置经 ``settings_service``（60s 缓存命中即可，不每条打库）。读配置失败 → 保守
    全记（不采样丢弃），绝不因观测配置异常丢业务可归因之外的日志。
    """
    category = str(entry.get("category") or "").strip().lower()
    if category == "caller":
        return True

    try:
        from system.models import SettingKeys
        from system.settings_service import get_float_setting, get_int_setting

        initial = max(0, get_int_setting(SettingKeys.LOG_SAMPLING_INITIAL, _DEFAULT_SAMPLING_INITIAL))
        rate = min(1.0, max(0.0, get_float_setting(SettingKeys.LOG_SAMPLING_RATE, _DEFAULT_SAMPLING_RATE)))
    except Exception:  # noqa: BLE001 — 读采样配置失败 → 保守全记
        return True

    key = (str(entry.get("component") or ""), str(entry.get("event") or ""))
    with _lock:
        seen = _sample_counts.get(key, 0)
        _sample_counts[key] = seen + 1
    if seen < initial:
        return True
    return random.random() < rate


def enqueue_system_log(entry: dict[str, Any]) -> None:
    """线程安全入队一条（已脱敏的）日志事件；best-effort，绝不反噬业务。

    ``entry`` 由 processor 传入，**已脱敏**。``sampling`` 类先经 ``_should_record``
    采样过滤（未中 ``_sampled_out += 1``，与队列满 ``_dropped`` 区分）；满则
    ``_dropped += 1`` 不抛；本函数**绝不**做 ORM（落库交后台 worker）。
    """
    global _enqueued, _dropped, _sampled_out
    try:
        if not _should_record(entry):
            with _lock:
                _sampled_out += 1
            return
        with _lock:
            if len(_queue) >= _MAXLEN:
                _dropped += 1
                return
            _queue.append(entry)
            _enqueued += 1
        _ensure_worker()
    except Exception:  # noqa: BLE001 — 日志入队绝不反噬业务
        pass


def _ensure_worker() -> None:
    """懒启动落库 daemon 线程（加锁单例）。

    测试环境（``PYTEST_CURRENT_TEST``）下**不**启动后台线程——测试用同步
    ``flush_now()`` 落库，保证确定性、避免跨线程 DB 连接污染测试隔离。
    """
    global _worker_thread
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if _worker_thread is not None and _worker_thread.is_alive():
        return
    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_worker_loop, name="friday-log-sink", daemon=True
        )
        _worker_thread.start()


def _worker_loop() -> None:
    """后台循环：定时或积压达阈值时 drain 一批落库。绝不抛（吞掉所有异常）。"""
    while True:
        try:
            time.sleep(_FLUSH_INTERVAL)
            # 把当前积压分批 drain 落库（单轮把队列清空，避免无限增长）。
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
    """把一批 dict 转 ``SystemLogEntry`` 并一次 ``bulk_create``。

    成功 ``_written += len``；异常 ``_write_failed += len(batch)`` 并丢批不重试
    （per「永不反噬业务」），绝不抛。
    """
    global _written, _write_failed
    if not batch:
        return
    from system.models import SystemLogEntry

    try:
        objs = [SystemLogEntry(**_to_entry(d)) for d in batch]
        SystemLogEntry.objects.bulk_create(objs, ignore_conflicts=True)
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


def _normalize_level(value: Any) -> str:
    """级别归一小写；``WARNING`` → ``warn``。截断到 10 字符（列宽）。"""
    raw = str(value or "info").strip().lower()
    if raw in ("warning", "warn"):
        return "warn"
    return raw[:10]


def _to_entry(d: dict[str, Any]) -> dict[str, Any]:
    """dict → ``SystemLogEntry`` 构造 kwargs。

    解析 ts/level，提取专属列字段，其余非标准字段收进 ``payload``，再从 payload
    提取关联键到 ``correlation``。
    """
    payload = {k: v for k, v in d.items() if k not in _KNOWN_KEYS}
    correlation = {k: payload.pop(k) for k in list(payload) if k in _CORRELATION_KEYS}
    return {
        "ts": _parse_ts(d.get("ts") or d.get("timestamp")),
        "level": _normalize_level(d.get("level")),
        "component": str(d.get("component") or "")[:40],
        "category": str(d.get("category") or "")[:10],
        "event": str(d.get("event") or "")[:128],
        "message": str(d.get("message") or d.get("event") or ""),
        "user_id": str(d.get("user_id") or "system")[:64],
        "source": str(d.get("source") or "")[:32],
        "trace_id": str(d.get("trace_id") or "")[:64],
        "request_id": str(d.get("request_id") or "")[:128],
        "payload": payload,
        "correlation": correlation,
    }


def snapshot_counters() -> dict[str, int]:
    """返回队列四计数 + 当前深度（71-04 计数端点 / Phase 73 快照采集消费）。"""
    with _lock:
        return {
            "queued": len(_queue),
            "max": _MAXLEN,
            "enqueued": _enqueued,
            "written": _written,
            "dropped": _dropped,
            "write_failed": _write_failed,
            "sampled_out": _sampled_out,
        }


def flush_now() -> None:
    """同步把当前队列全部 drain + 落库（测试钩子；生产由 daemon worker 处理）。"""
    while True:
        batch = _drain(_BATCH_SIZE)
        if not batch:
            break
        _flush(batch)


def _reset_for_tests() -> None:
    """清空队列 + 归零计数 + 采样状态（测试钩子）。"""
    global _enqueued, _written, _dropped, _write_failed, _sampled_out
    with _lock:
        _queue.clear()
        _sample_counts.clear()
        _enqueued = 0
        _written = 0
        _dropped = 0
        _write_failed = 0
        _sampled_out = 0


__all__ = [
    "enqueue_system_log",
    "snapshot_counters",
    "flush_now",
]

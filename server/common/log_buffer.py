"""进程内内存环形缓冲日志（运维监控「系统日志」面板的数据源）。

为什么用内存环形缓冲而不是读文件 / docker logs：
- 本项目 ``LOGGING`` 仅配置 console（StreamHandler → stdout），没有日志文件可 tail；
- 从 Django 进程读 docker logs 既不可移植也越权；
- 内存环形缓冲对 SQLite / Postgres / 任意部署形态都成立，零外部依赖。

注意（多进程）：缓冲是「每进程」的。多 ASGI worker 时，``/api/system/logs/``
返回的是处理该请求的那个 worker 的缓冲。作为轻量排障视图可接受。

写入两路（见 ``common.logging``）：
- structlog 业务事件经 ``buffer_log`` processor（已在 ``redact_credentials`` 之后，
  缓冲里就是脱敏后的内容）；
- stdlib logging（django / 第三方）经 ``RingBufferHandler``。
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

# 单进程最多保留的日志条数（足够排障，又不至于吃内存）。
_MAX_ENTRIES = 800

_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_ENTRIES)
_lock = threading.Lock()


def append_log(entry: dict[str, Any]) -> None:
    """线程安全地追加一条日志记录（best-effort，绝不抛出影响业务）。"""
    try:
        with _lock:
            _buffer.append(entry)
    except Exception:  # noqa: BLE001 — 日志缓冲永远不能反过来打断业务
        pass


def snapshot(limit: int = 200, level: str | None = None) -> list[dict[str, Any]]:
    """返回最近的日志（最新在前）。可选按 level 过滤。"""
    with _lock:
        items = list(_buffer)
    if level:
        wanted = level.strip().upper()
        items = [e for e in items if str(e.get("level", "")).upper() == wanted]
    if limit > 0:
        items = items[-limit:]
    items.reverse()  # 最新在前
    return items


def clear() -> None:
    """清空缓冲（测试用）。"""
    with _lock:
        _buffer.clear()

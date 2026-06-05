"""深度分析事件注册表。

将 Runner WebSocket 收到的容器日志桥接到 SSE 事件流。
容器 stdout 的 [task:*] 行经 Runner → consumers.py → push_event()
写入此处注册的 asyncio.Queue，deep_analysis 轮询循环消费后
通过 event_callback 推送到前端 SSE 流。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_registries: dict[str, asyncio.Queue[dict[str, Any]]] = {}


def register(session_id: str, maxsize: int = 500) -> asyncio.Queue[dict[str, Any]]:
    """为深度分析会话注册事件队列。"""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
    _registries[session_id] = queue
    logger.debug("deep_analysis_registry_registered", session_id=session_id)
    return queue


def unregister(session_id: str) -> None:
    """移除会话的事件队列。"""
    _registries.pop(session_id, None)
    logger.debug("deep_analysis_registry_unregistered", session_id=session_id)


def push_event(session_id: str, event: dict[str, Any]) -> bool:
    """向会话队列推送事件，队列满时丢弃最旧事件。"""
    queue = _registries.get(session_id)
    if queue is None:
        return False
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(event)
        return True
    except asyncio.QueueFull:
        return False

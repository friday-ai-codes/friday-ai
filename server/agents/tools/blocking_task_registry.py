"""Blocking task 外部注册表。
当 deep_analysis 等工具返回 __blocking_task__ 标记时，同时注册到此 registry。
如果 SDK 将 tool result 序列化为 string（丢失 dict 结构），executing_node 可从
此 registry 读取 blocking task 信息作为 fallback。
线程安全：使用 asyncio.Lock 保护并发访问。
"""
from __future__ import annotations
import asyncio
from typing import Any
import structlog
logger = structlog.get_logger(__name__)
_store: dict[str, list[dict[str, Any]]] = {}
_lock = asyncio.Lock
async def register_blocking_task(session_id: str, task_info: dict[str, Any]) -> None:
 """按 session_id 注册一个 blocking task。"""
 async with _lock:
 _store.setdefault(session_id, ).append(task_info)
 logger.debug(
 "blocking_task_registered",
 session_id=session_id,
 task_id=task_info.get("task_id"),
 )
async def drain_blocking_tasks(session_id: str) -> list[dict[str, Any]]:
 """读取并清空指定 session 的所有 blocking tasks。"""
 async with _lock:
 tasks = _store.pop(session_id, )
 if tasks:
 logger.debug(
 "blocking_tasks_drained",
 session_id=session_id,
 count=len(tasks),
 )
 return tasks

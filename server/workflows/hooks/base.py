"""Lifecycle hooks base classes."""
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable
import structlog
logger = structlog.get_logger
class BaseHook(ABC):
 """钩子基类"""
 # 钩子优先级（数字越小越先执行）
 priority: int = 100
 @abstractmethod
 async def execute(self, event: str, **kwargs: Any) -> None:
 """执行钩子"""
 pass
class HookManager:
 """钩子管理器"""
 # 支持的事件
 EVENTS = [
 "execution_started",
 "execution_running",
 "execution_completed",
 "execution_failed",
 "execution_paused",
 "execution_suspended",
 "execution_resumed",
 "execution_cancelled",
 "execution_timeout",
 "node_started",
 "node_completed",
 "node_failed",
 "node_skipped",
 "node_waiting_approval",
 "node_approved",
 "node_rejected",
 ]
 def __init__(self):
 self._hooks: dict[str, list[BaseHook]] = {event: for event in self.EVENTS}
 self._callbacks: dict[str, list[Callable]] = {event: for event in self.EVENTS}
 def register_hook(self, event: str, hook: BaseHook) -> None:
 """注册钩子"""
 if event not in self._hooks:
 raise ValueError(f"未知事件: {event}")
 self._hooks[event].append(hook)
 self._hooks[event].sort(key=lambda h: h.priority)
 def register_callback(self, event: str, callback: Callable) -> None:
 """注册回调函数"""
 if event not in self._callbacks:
 raise ValueError(f"未知事件: {event}")
 self._callbacks[event].append(callback)
 async def trigger(self, event: str, **kwargs: Any) -> None:
 """触发事件"""
 if event not in self._hooks:
 return
 # 执行钩子
 for hook in self._hooks[event]:
 try:
 await hook.execute(event, **kwargs)
 except Exception as e:
 logger.error(
 "hook_execution_error",
 workflow_event_type=event,
 hook=hook.__class__.__name__,
 error=str(e),
 )
 # 执行回调
 for callback in self._callbacks[event]:
 try:
 result = callback(event, **kwargs)
 if asyncio.iscoroutine(result):
 await result
 except Exception as e:
 logger.error(
 "callback_execution_error",
 workflow_event_type=event,
 error=str(e),
 )

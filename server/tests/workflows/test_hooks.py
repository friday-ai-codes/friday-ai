"""HookManager 事件注册和触发测试。
验证所有引擎触发的事件名都在 HookManager.EVENTS 中注册，
防止类似 （node_waiting_event 未注册）的回归 bug。
"""
import re
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from workflows.hooks.base import BaseHook, HookManager
class TestHookManagerEvents:
 """验证 HookManager.EVENTS 列表完整性"""
 def test_node_waiting_event_registered(self) -> None:
 """: node_waiting_event 必须在 EVENTS 列表中"""
 assert "node_waiting_event" in HookManager.EVENTS
 def test_register_hook_for_node_waiting_event(self) -> None:
 """node_waiting_event 可以注册钩子（不抛 ValueError）"""
 manager = HookManager
 class DummyHook(BaseHook):
 async def execute(self, event: str, **kwargs) -> None:
 pass
 # 不应抛出 ValueError
 manager.register_hook("node_waiting_event", DummyHook)
 @pytest.mark.asyncio
 async def test_trigger_node_waiting_event_calls_hook(self) -> None:
 """trigger('node_waiting_event') 能触发已注册的钩子"""
 manager = HookManager
 mock_hook = AsyncMock(spec=BaseHook)
 mock_hook.priority = 100
 mock_hook.execute = AsyncMock
 manager.register_hook("node_waiting_event", mock_hook)
 await manager.trigger("node_waiting_event", execution=None)
 mock_hook.execute.assert_called_once_with(
 "node_waiting_event", execution=None
 )
 def test_all_scheduler_events_registered(self) -> None:
 """所有 scheduler.py 中触发的事件名都必须在 EVENTS 中注册（防止回归）"""
 scheduler_path = (
 Path(__file__).resolve.parent.parent.parent
 / "workflows"
 / "engine"
 / "scheduler.py"
 )
 assert scheduler_path.exists, f"scheduler.py 未找到: {scheduler_path}"
 content = scheduler_path.read_text
 # 提取所有 hooks.trigger("event_name", ...) 调用中的事件名
 # 匹配模式：hooks.trigger("xxx" 或 self.hooks.trigger("xxx"
 pattern = r'hooks\.trigger\(\s*["\'](\w+)["\']'
 triggered_events = set(re.findall(pattern, content))
 assert triggered_events, "未在 scheduler.py 中找到任何 hooks.trigger 调用"
 missing = triggered_events - set(HookManager.EVENTS)
 assert not missing, (
 f"scheduler.py 中触发的事件未在 HookManager.EVENTS 中注册: {missing}"
 )
 def test_register_unknown_event_raises_error(self) -> None:
 """注册未知事件应抛出 ValueError"""
 manager = HookManager
 class DummyHook(BaseHook):
 async def execute(self, event: str, **kwargs) -> None:
 pass
 with pytest.raises(ValueError, match="未知事件"):
 manager.register_hook("nonexistent_event", DummyHook)

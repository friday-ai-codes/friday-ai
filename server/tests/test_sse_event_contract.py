"""SSE 事件类型契约测试。
验证后端 events.py 的事件类型常量定义完整、正确，
确保前后端 SSE 事件类型始终保持一致。
前端 SSEEvent.type 联合类型应与 ALL_EVENT_TYPES 一一对应：
 'text_delta' | 'tool_use_start' | 'tool_use_result' | 'message_complete'
 | 'title_generated' | 'error' | 'thinking' | 'budget_warning'
"""
from __future__ import annotations
from agents.core.events import (
 ALL_EVENT_TYPES,
 BUDGET_WARNING,
 KEEPALIVE,
)
class TestSSEEventTypeContract:
 """SSE 事件类型契约：后端常量必须覆盖所有前端已知事件类型。"""
 # 前端 SSEEvent.type 联合类型中的全部事件类型
 EXPECTED_EVENT_TYPES: frozenset[str] = frozenset({
 "text_delta",
 "tool_use_start",
 "tool_use_result",
 "message_complete",
 "thinking",
 "error",
 "title_generated",
 "budget_warning",
 "deep_analysis_progress",
 })
 def test_all_event_types_contains_expected(self) -> None:
 """ALL_EVENT_TYPES 恰好包含 9 种预期事件类型。"""
 assert ALL_EVENT_TYPES == self.EXPECTED_EVENT_TYPES, (
 f"ALL_EVENT_TYPES 与预期不符。\n"
 f" 多余: {ALL_EVENT_TYPES - self.EXPECTED_EVENT_TYPES}\n"
 f" 缺少: {self.EXPECTED_EVENT_TYPES - ALL_EVENT_TYPES}"
 )
 def test_all_event_types_count(self) -> None:
 """ALL_EVENT_TYPES 应恰好包含 9 种类型。"""
 assert len(ALL_EVENT_TYPES) == 9, (
 f"期望 9 种事件类型，实际 {len(ALL_EVENT_TYPES)}: {ALL_EVENT_TYPES}"
 )
 def test_budget_warning_constant(self) -> None:
 """BUDGET_WARNING 常量值为 'budget_warning'。"""
 assert BUDGET_WARNING == "budget_warning"
 def test_keepalive_constant(self) -> None:
 """KEEPALIVE 常量值为 'keepalive'。"""
 assert KEEPALIVE == "keepalive"
 def test_keepalive_not_in_all_event_types(self) -> None:
 """KEEPALIVE 不应在 ALL_EVENT_TYPES 中（它是连接级事件，不走 SSE data 行）。"""
 assert KEEPALIVE not in ALL_EVENT_TYPES, (
 "keepalive 是连接级事件，不应被包含在 SSE data 事件类型集合中"
 )
 def test_heartbeat_default_interval(self) -> None:
 """Keepalive 心跳间隔默认值为 15.0 秒。"""
 from agents.sdk.runner import SdkRunnerConfig
 # 使用必须参数创建默认配置
 config = SdkRunnerConfig(
 system_prompt="test",
 model="test",
 project_id="test",
 session_id="test",
 )
 assert config.heartbeat_timeout == 15.0, (
 f"期望心跳间隔 15.0 秒，实际 {config.heartbeat_timeout}"
 )

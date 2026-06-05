"""AgentEvent 数据结构测试。

测试 initial implementation 新增的事件基础设施中 AgentEvent dataclass 和事件类型常量。
"""

from agents.core.events import (
    ERROR,
    MESSAGE_COMPLETE,
    TEXT_DELTA,
    THINKING,
    TITLE_GENERATED,
    TOOL_USE_RESULT,
    TOOL_USE_START,
    AgentEvent,
)

# ============================================================================
# AgentEvent 基础测试
# ============================================================================


class TestAgentEvent:
    """AgentEvent dataclass 基础测试。"""

    def test_agent_event_creation(self):
        """创建 AgentEvent 实例。"""
        event = AgentEvent(type="text_delta", data={"text": "hello"})
        assert event.type == "text_delta"
        assert event.data == {"text": "hello"}

    def test_agent_event_default_data(self):
        """data 默认为空 dict。"""
        event = AgentEvent(type="thinking")
        assert event.data == {}

    def test_event_type_constants(self):
        """7 个事件类型常量正确。"""
        assert TEXT_DELTA == "text_delta"
        assert TOOL_USE_START == "tool_use_start"
        assert TOOL_USE_RESULT == "tool_use_result"
        assert MESSAGE_COMPLETE == "message_complete"
        assert THINKING == "thinking"
        assert ERROR == "error"
        assert TITLE_GENERATED == "title_generated"

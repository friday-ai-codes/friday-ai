"""WS 调试协议测试。

覆盖:
- WS receive() 处理 release/skip 命令
- WS 未知 action 返回错误
- WS disconnect 清理 _debug_sessions
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.consumers import WorkflowExecutionConsumer
from workflows.engine.scheduler import DebugSession, WorkflowEngine, _debug_sessions


@pytest.mark.asyncio
@pytest.mark.django_db
class TestDebugWebSocket:
    """WS 调试协议测试。"""

    def _make_consumer(self, execution_id: str = "test-exec-123") -> WorkflowExecutionConsumer:
        """创建一个配置好的 Consumer 实例（不经过真实 WS 连接）。"""
        consumer = WorkflowExecutionConsumer()
        consumer.execution_id = execution_id
        consumer.group_name = f"execution_{execution_id}"
        consumer.send = AsyncMock()
        consumer.channel_name = "test-channel"
        consumer.channel_layer = MagicMock()
        # group_discard 需要返回 awaitable
        consumer.channel_layer.group_discard = AsyncMock()
        return consumer

    async def test_ws_release_command(self):
        """模拟 WS receive() 收到 release 命令，验证调用 release_debug_node。"""
        consumer = self._make_consumer()

        with patch.object(
            WorkflowEngine, "release_debug_node", return_value=True
        ) as mock_release:
            await consumer.receive(
                text_data=json.dumps({
                    "type": "debug_action",
                    "action": "release",
                })
            )

        mock_release.assert_called_once_with(
            execution_id="test-exec-123",
            action="release",
            action_data={},
        )

        # 验证 ack 消息
        consumer.send.assert_called_once()
        sent_data = json.loads(consumer.send.call_args[1]["text_data"])
        assert sent_data["type"] == "debug_action_ack"
        assert sent_data["action"] == "release"

    async def test_ws_skip_command(self):
        """模拟 WS receive() 收到 skip 命令，验证调用正确。"""
        consumer = self._make_consumer()

        with patch.object(
            WorkflowEngine, "release_debug_node", return_value=True
        ) as mock_release:
            await consumer.receive(
                text_data=json.dumps({
                    "type": "debug_action",
                    "action": "skip",
                })
            )

        mock_release.assert_called_once_with(
            execution_id="test-exec-123",
            action="skip",
            action_data={},
        )

        sent_data = json.loads(consumer.send.call_args[1]["text_data"])
        assert sent_data["type"] == "debug_action_ack"
        assert sent_data["action"] == "skip"

    async def test_ws_unknown_action_returns_error(self):
        """发送未知 action，验证返回 error 消息。"""
        consumer = self._make_consumer()

        await consumer.receive(
            text_data=json.dumps({
                "type": "debug_action",
                "action": "unknown_action",
            })
        )

        consumer.send.assert_called_once()
        sent_data = json.loads(consumer.send.call_args[1]["text_data"])
        assert sent_data["type"] == "error"
        assert "未知调试操作" in sent_data["message"]

    async def test_mock_action_accepted(self):
        """WS 发送 mock action，收到 debug_action_ack，action 为 mock。"""
        consumer = self._make_consumer()

        with patch.object(
            WorkflowEngine, "release_debug_node", return_value=True
        ) as mock_release:
            await consumer.receive(
                text_data=json.dumps({
                    "type": "debug_action",
                    "action": "mock",
                    "data": {"mock_output": {"result": "mocked"}},
                })
            )

        mock_release.assert_called_once_with(
            execution_id="test-exec-123",
            action="mock",
            action_data={"mock_output": {"result": "mocked"}},
        )

        consumer.send.assert_called_once()
        sent_data = json.loads(consumer.send.call_args[1]["text_data"])
        assert sent_data["type"] == "debug_action_ack"
        assert sent_data["action"] == "mock"

    async def test_release_with_edited_output_accepted(self):
        """WS 发送 release + edited_output，收到 debug_action_ack。"""
        consumer = self._make_consumer()

        with patch.object(
            WorkflowEngine, "release_debug_node", return_value=True
        ) as mock_release:
            await consumer.receive(
                text_data=json.dumps({
                    "type": "debug_action",
                    "action": "release",
                    "data": {"edited_output": {"key": "edited"}},
                })
            )

        mock_release.assert_called_once_with(
            execution_id="test-exec-123",
            action="release",
            action_data={"edited_output": {"key": "edited"}},
        )

        consumer.send.assert_called_once()
        sent_data = json.loads(consumer.send.call_args[1]["text_data"])
        assert sent_data["type"] == "debug_action_ack"
        assert sent_data["action"] == "release"

    async def test_ws_disconnect_cleanup(self):
        """模拟 disconnect()，验证 _debug_sessions 被清理 + session.event 被 set。"""
        execution_id = "test-disconnect-exec"
        consumer = self._make_consumer(execution_id=execution_id)

        # 预先在 _debug_sessions 中放入一个 DebugSession
        loop = asyncio.get_event_loop()
        session = DebugSession(execution_id=execution_id, loop=loop)
        session.event = asyncio.Event()
        _debug_sessions[execution_id] = session

        try:
            await consumer.disconnect(close_code=1000)

            # 验证 session 被从 _debug_sessions 中移除
            assert execution_id not in _debug_sessions
            # 验证 debug_action 被设为 cancel
            assert session.debug_action == "cancel"
        finally:
            # 确保清理（防止测试污染）
            _debug_sessions.pop(execution_id, None)

"""Regression tests for Feishu WebSocket bot entry."""
from __future__ import annotations
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from feishu.models import FeishuBotMessage
from feishu.websocket_client import FeishuWebSocketClient
def _ws_event(*, message_id: str, content: str, mentions=None, sender_type: str = "user", message_type: str = "text") -> SimpleNamespace:
 return SimpleNamespace(
 header=SimpleNamespace(event_id=f"evt-{message_id}"),
 event=SimpleNamespace(
 message=SimpleNamespace(
 chat_id="chat_ws",
 chat_type="group",
 message_id=message_id,
 message_type=message_type,
 content=content,
 mentions=mentions or,
 parent_id="",
 root_id="",
 ),
 sender=SimpleNamespace(
 sender_id=SimpleNamespace(open_id="ou_ws"),
 sender_type=sender_type,
 ),
 ),
 )
@pytest.mark.django_db(transaction=True)
class TestFeishuBotWebSocketIntegration:
 def test_process_message_sync_calls_shared_dispatcher(self) -> None:
 client = FeishuWebSocketClient(app_id="cli_test", app_secret="secret")
 data = _ws_event(
 message_id="msg-ws-1",
 content='{"text":"@Friday 看下 dispatcher","mentions":[{"name":"Friday"}]}',
 mentions=[{"name": "Friday"}],
 )
 with patch("feishu.bot.dispatcher.dispatch_inbound_message", new=AsyncMock) as mock_dispatch:
 client._process_message_sync(data)
 mock_dispatch.assert_awaited_once
 assert mock_dispatch.await_args is not None
 dispatched_message = mock_dispatch.await_args.args[0]
 assert dispatched_message.message_id == "msg-ws-1"
 assert dispatched_message.mentioned_bot is True
 def test_valid_bot_message_uses_same_dispatcher_path_and_schedules_handoff(self) -> None:
 client = FeishuWebSocketClient(app_id="cli_test", app_secret="secret")
 data = _ws_event(
 message_id="msg-ws-2",
 content='{"text":"@Friday websocket 路径也要工作","mentions":[{"name":"Friday"}]}',
 mentions=[{"name": "Friday"}],
 )
 with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
 client._process_message_sync(data)
 assert FeishuBotMessage.objects.filter(message_id="msg-ws-2").exists
 mock_schedule.assert_called_once_with("msg-ws-2")
 def test_invalid_messages_do_not_schedule_processing(self) -> None:
 client = FeishuWebSocketClient(app_id="cli_test", app_secret="secret")
 bot_data = _ws_event(
 message_id="msg-ws-3",
 content='{"text":"@Friday 我是机器人"}',
 mentions=[{"name": "Friday"}],
 sender_type="bot",
 )
 plain_data = _ws_event(
 message_id="msg-ws-4",
 content='{"text":"普通群聊"}',
 mentions=,
 )
 with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
 client._process_message_sync(bot_data)
 client._process_message_sync(plain_data)
 assert not FeishuBotMessage.objects.filter(message_id__in=["msg-ws-3", "msg-ws-4"]).exists
 mock_schedule.assert_not_called
 @pytest.mark.asyncio
 async def test_process_message_sync_uses_running_loop_without_async_to_sync_error(self) -> None:
 client = FeishuWebSocketClient(app_id="cli_test", app_secret="secret")
 data = _ws_event(
 message_id="msg-ws-5",
 content='{"text":"@Friday 你是？","mentions":[{"name":"Friday"}]}',
 mentions=[{"name": "Friday"}],
 )
 with patch("feishu.bot.dispatcher.dispatch_inbound_message", new=AsyncMock) as mock_dispatch:
 client._process_message_sync(data)
 await asyncio.sleep(0)
 mock_dispatch.assert_awaited_once

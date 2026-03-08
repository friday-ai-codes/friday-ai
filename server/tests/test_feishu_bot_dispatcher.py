"""Tests for shared Feishu bot dispatcher."""
from __future__ import annotations
from unittest.mock import patch
import pytest
from feishu.bot.dispatcher import dispatch_inbound_message
from feishu.bot.parser import InboundLarkMessage
from feishu.models import FeishuBotMessage, FeishuBotThread
@pytest.mark.django_db(transaction=True)
class TestFeishuBotDispatcher:
 async def test_group_message_with_bot_mention_is_persisted_and_scheduled(self) -> None:
 message = InboundLarkMessage(
 event_id="evt-1",
 chat_id="chat_1",
 chat_type="group",
 message_id="msg_1",
 sender_open_id="ou_user",
 sender_type="user",
 sender_is_bot=False,
 message_type="text",
 normalized_text="帮我看看这次发布",
 mentioned_bot=True,
 has_effective_body=True,
 quote_message_id="",
 parent_id="",
 attachments=,
 raw_payload={"event": {}},
 )
 with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
 result = await dispatch_inbound_message(message)
 assert result.status == "bot_message_accepted"
 assert await FeishuBotThread.objects.filter(chat_id="chat_1").aexists
 bot_message = await FeishuBotMessage.objects.aget(message_id="msg_1")
 assert bot_message.normalized_text == "帮我看看这次发布"
 mock_schedule.assert_called_once_with("msg_1")
 async def test_non_mentioned_group_message_is_ignored(self) -> None:
 message = InboundLarkMessage(
 event_id="evt-2",
 chat_id="chat_1",
 chat_type="group",
 message_id="msg_2",
 sender_open_id="ou_user",
 sender_type="user",
 sender_is_bot=False,
 message_type="text",
 normalized_text="普通聊天",
 mentioned_bot=False,
 has_effective_body=True,
 quote_message_id="",
 parent_id="",
 attachments=,
 raw_payload={},
 )
 with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
 result = await dispatch_inbound_message(message)
 assert result.status == "ignored"
 assert result.reason == "mention_required"
 assert not await FeishuBotMessage.objects.filter(message_id="msg_2").aexists
 mock_schedule.assert_not_called
 async def test_duplicate_message_returns_duplicate_without_rescheduling(self) -> None:
 thread = await FeishuBotThread.objects.acreate(chat_id="chat_1", root_message_id="msg_1")
 await FeishuBotMessage.objects.acreate(
 message_id="msg_1",
 thread=thread,
 chat_id="chat_1",
 sender_open_id="ou_user",
 message_type="text",
 normalized_text="第一次消息",
 quote_message_id="",
 mentioned_bot=True,
 raw_payload={},
 )
 message = InboundLarkMessage(
 event_id="evt-3",
 chat_id="chat_1",
 chat_type="group",
 message_id="msg_1",
 sender_open_id="ou_user",
 sender_type="user",
 sender_is_bot=False,
 message_type="text",
 normalized_text="第一次消息",
 mentioned_bot=True,
 has_effective_body=True,
 quote_message_id="",
 parent_id="",
 attachments=,
 raw_payload={},
 )
 with patch("feishu.bot.dispatcher.schedule_process_feishu_bot_message") as mock_schedule:
 result = await dispatch_inbound_message(message)
 assert result.status == "duplicate"
 mock_schedule.assert_not_called

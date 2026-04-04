"""Bot 消息 payload 工厂函数。"""
import uuid
from feishu.bot.parser import InboundLarkMessage
def create_bot_text_message(
 *,
 chat_id: str = "oc_test_group",
 chat_type: str = "group",
 text: str = "帮我看看这个 Bug",
 mentioned_bot: bool = True,
 sender_open_id: str = "ou_user_001",
 message_id: str | None = None,
 quote_message_id: str = "",
) -> InboundLarkMessage:
 """创建标准的 @Bot 文本消息。"""
 if message_id is None:
 message_id = f"om_{uuid.uuid4.hex[:12]}"
 return InboundLarkMessage(
 event_id=f"evt_{uuid.uuid4.hex[:8]}",
 chat_id=chat_id,
 chat_type=chat_type,
 message_id=message_id,
 sender_open_id=sender_open_id,
 sender_type="user",
 sender_is_bot=False,
 message_type="text",
 normalized_text=text,
 mentioned_bot=mentioned_bot,
 has_effective_body=bool(text.strip),
 quote_message_id=quote_message_id,
 parent_id="",
 )
def create_bot_message_from_bot(*, chat_id: str = "oc_test_group") -> InboundLarkMessage:
 """创建来自 Bot 的消息（应被忽略）。"""
 return InboundLarkMessage(
 event_id=f"evt_{uuid.uuid4.hex[:8]}",
 chat_id=chat_id,
 chat_type="group",
 message_id=f"om_{uuid.uuid4.hex[:12]}",
 sender_open_id="",
 sender_type="bot",
 sender_is_bot=True,
 message_type="text",
 normalized_text="自动回复",
 mentioned_bot=False,
 has_effective_body=True,
 quote_message_id="",
 parent_id="",
 )
def create_p2p_message(*, text: str = "私聊消息") -> InboundLarkMessage:
 """创建私聊消息（当前应被忽略，chat_type != group）。"""
 return InboundLarkMessage(
 event_id=f"evt_{uuid.uuid4.hex[:8]}",
 chat_id=f"oc_p2p_{uuid.uuid4.hex[:8]}",
 chat_type="p2p",
 message_id=f"om_{uuid.uuid4.hex[:12]}",
 sender_open_id="ou_user_001",
 sender_type="user",
 sender_is_bot=False,
 message_type="text",
 normalized_text=text,
 mentioned_bot=True,
 has_effective_body=True,
 quote_message_id="",
 parent_id="",
 )
def create_empty_body_message(*, chat_id: str = "oc_test_group") -> InboundLarkMessage:
 """创建空消息体（应被忽略）。"""
 return InboundLarkMessage(
 event_id=f"evt_{uuid.uuid4.hex[:8]}",
 chat_id=chat_id,
 chat_type="group",
 message_id=f"om_{uuid.uuid4.hex[:12]}",
 sender_open_id="ou_user_001",
 sender_type="user",
 sender_is_bot=False,
 message_type="text",
 normalized_text="",
 mentioned_bot=True,
 has_effective_body=False,
 quote_message_id="",
 parent_id="",
 )

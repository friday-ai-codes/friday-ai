"""SDK 事件适配层：StreamEvent / AssistantMessage → AgentEvent 映射。
将 Claude Agent SDK 的消息转换为统一的 AgentEvent 格式，
兼容 chat/streaming.py 的 format_sse。
核心策略：SDK 的 include_partial_messages=True 会在每个对话轮次
产出 AssistantMessage（包含该轮的完整 content blocks）。通过跟踪
已处理的 block 数量和文本长度，实现增量事件提取。
"""
from __future__ import annotations
from typing import Any
import structlog
from agents.core.events import (
 ERROR,
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_START,
 AgentEvent,
)
logger = structlog.get_logger(__name__)
class EventAdapter:
 """将 SDK 消息转换为 AgentEvent 列表。
 维护状态以实现 AssistantMessage 的增量提取：
 - _seen_blocks: 已处理过的 content block 数量
 - _seen_text_len: 最后一个 text block 已发送的字符数
 - _seen_thinking_len: 最后一个 thinking block 已发送的字符数
 """
 def __init__(self, model: str, session_id: str) -> None:
 self._model = model
 self._session_id = session_id
 self._seen_blocks: int = 0
 self._seen_text_len: int = 0
 self._seen_thinking_len: int = 0
 self._seen_tool_ids: set[str] = set
 def _inject_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
 data["model"] = self._model
 data["session_id"] = self._session_id
 return data
 def adapt(self, message: Any) -> list[AgentEvent]:
 """将 SDK message 转换为 AgentEvent 列表。"""
 # ResultMessage（有 result 属性，无 event 属性）
 if hasattr(message, "result") and not hasattr(message, "event"):
 return self._adapt_result_message(message)
 # StreamEvent（有 event 属性）
 if hasattr(message, "event"):
 return self._adapt_stream_event(message)
 # AssistantMessage — 从中提取增量内容
 message_type = type(message).__name__
 if message_type == "AssistantMessage":
 return self._adapt_assistant_message(message)
 if message_type in {"SystemMessage", "UserMessage"}:
 return
 if message_type == "RateLimitEvent":
 logger.info(
 "sdk_rate_limit_event",
 rate_limit_info=getattr(message, "rate_limit_info", None),
 )
 return
 logger.warning("unknown_sdk_message_type", message_type=message_type)
 return
 def adapt_error(self, error: Exception) -> list[AgentEvent]:
 return [
 AgentEvent(
 type=ERROR,
 data=self._inject_metadata({"message": str(error)}),
 )
 ]
 # ------------------------------------------------------------------
 # AssistantMessage 增量提取
 # ------------------------------------------------------------------
 def _adapt_assistant_message(self, message: Any) -> list[AgentEvent]:
 """从 AssistantMessage 增量提取 thinking / text / tool_use。
 SDK 的 include_partial_messages 会多次 yield 同一轮的 AssistantMessage，
 每次 content blocks 可能增长或最后一个 block 内容变长。
 通过比较已处理的 block 索引和文本长度实现增量。
 """
 content = getattr(message, "content", None)
 if not content:
 return
 events: list[AgentEvent] =
 blocks = list(content)
 for i, block in enumerate(blocks):
 block_type = type(block).__name__
 if block_type == "ThinkingBlock":
 thinking = getattr(block, "thinking", "") or ""
 if len(thinking) > self._seen_thinking_len:
 delta = thinking[self._seen_thinking_len:]
 self._seen_thinking_len = len(thinking)
 events.append(
 AgentEvent(
 type=THINKING,
 data=self._inject_metadata({"thinking": delta}),
 )
 )
 elif block_type == "TextBlock":
 text = getattr(block, "text", "") or ""
 if len(text) > self._seen_text_len:
 delta = text[self._seen_text_len:]
 self._seen_text_len = len(text)
 events.append(
 AgentEvent(
 type=TEXT_DELTA,
 data=self._inject_metadata({"text": delta}),
 )
 )
 elif block_type == "ToolUseBlock":
 tool_id = getattr(block, "id", "") or ""
 if tool_id and tool_id not in self._seen_tool_ids:
 self._seen_tool_ids.add(tool_id)
 tool_name = getattr(block, "name", "") or ""
 tool_input = getattr(block, "input", {}) or {}
 events.append(
 AgentEvent(
 type=TOOL_USE_START,
 data=self._inject_metadata({
 "tool_name": tool_name,
 "tool_call_id": tool_id,
 "input": tool_input,
 }),
 )
 )
 if events:
 logger.debug(
 "assistant_message_extracted",
 event_count=len(events),
 event_types=[e.type for e in events],
 )
 return events
 # ------------------------------------------------------------------
 # ResultMessage
 # ------------------------------------------------------------------
 def _adapt_result_message(self, message: Any) -> list[AgentEvent]:
 result_text = str(message.result) if message.result else ""
 return [
 AgentEvent(
 type=MESSAGE_COMPLETE,
 data=self._inject_metadata({"result": result_text}),
 )
 ]
 # ------------------------------------------------------------------
 # StreamEvent（保留，若 SDK 未来产出 StreamEvent 仍可用）
 # ------------------------------------------------------------------
 def _adapt_stream_event(self, message: Any) -> list[AgentEvent]:
 event: dict[str, Any] = message.event
 event_type: str = event.get("type", "")
 if event_type == "content_block_delta":
 return self._adapt_content_block_delta(event)
 elif event_type == "content_block_start":
 return self._adapt_content_block_start(event)
 elif event_type in ("message_delta", "message_start", "content_block_stop", "message_stop"):
 return
 else:
 return self._adapt_unknown_event(event, event_type)
 def _adapt_content_block_delta(self, event: dict[str, Any]) -> list[AgentEvent]:
 delta: dict[str, Any] = event.get("delta", {})
 delta_type: str = delta.get("type", "")
 if delta_type == "text_delta":
 return [
 AgentEvent(
 type=TEXT_DELTA,
 data=self._inject_metadata({"text": delta.get("text", "")}),
 )
 ]
 elif delta_type == "thinking_delta":
 return [
 AgentEvent(
 type=THINKING,
 data=self._inject_metadata({"thinking": delta.get("thinking", "")}),
 )
 ]
 return
 def _adapt_content_block_start(self, event: dict[str, Any]) -> list[AgentEvent]:
 content_block: dict[str, Any] = event.get("content_block", {})
 block_type: str = content_block.get("type", "")
 if block_type == "tool_use":
 tool_id = content_block.get("id", "")
 if tool_id in self._seen_tool_ids:
 return
 self._seen_tool_ids.add(tool_id)
 return [
 AgentEvent(
 type=TOOL_USE_START,
 data=self._inject_metadata({
 "tool_name": content_block.get("name", ""),
 "tool_call_id": tool_id,
 }),
 )
 ]
 elif block_type == "thinking":
 return [
 AgentEvent(
 type=THINKING,
 data=self._inject_metadata({"thinking": ""}),
 )
 ]
 return
 def _adapt_unknown_event(self, event: dict[str, Any], event_type: str) -> list[AgentEvent]:
 logger.info("unknown_stream_event_passthrough", event_type=event_type)
 data = {k: v for k, v in event.items if k != "type"}
 return [
 AgentEvent(
 type=event_type,
 data=self._inject_metadata(data),
 )
 ]

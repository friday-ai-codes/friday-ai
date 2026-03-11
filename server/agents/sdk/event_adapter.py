"""SDK 事件适配层：StreamEvent → AgentEvent 映射。
将 Claude Agent SDK 的 StreamEvent 和 ResultMessage 转换为
统一的 AgentEvent 格式，兼容 chat/streaming.py 的 format_sse。
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
 SDK 启用 include_partial_messages=True 后，query 会 yield 两种对象：
 - StreamEvent: 包含 .event dict（Anthropic API 原始事件）
 - ResultMessage: 包含 .result（最终回复文本）
 本类将这些对象映射为统一的 AgentEvent，供 SSE 流式输出。
 Args:
 model: 当前使用的模型标识
 session_id: 会话 ID，注入每个事件的 metadata
 """
 def __init__(self, model: str, session_id: str) -> None:
 self._model = model
 self._session_id = session_id
 def _inject_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
 """注入通用元数据到事件 data。"""
 data["model"] = self._model
 data["session_id"] = self._session_id
 return data
 def adapt(self, message: Any) -> list[AgentEvent]:
 """将 SDK message 转换为 AgentEvent 列表。
 一个 message 可能产生 0-N 个事件。
 Args:
 message: SDK 的 StreamEvent 或 ResultMessage 对象
 Returns:
 AgentEvent 列表
 """
 # ResultMessage 检测（有 result 属性，无 event 属性）
 if hasattr(message, "result") and not hasattr(message, "event"):
 return self._adapt_result_message(message)
 # StreamEvent 检测（有 event 属性）
 if hasattr(message, "event"):
 return self._adapt_stream_event(message)
 # 未识别的消息类型
 logger.warning(
 "unknown_sdk_message_type",
 message_type=type(message).__name__,
 )
 return
 def adapt_error(self, error: Exception) -> list[AgentEvent]:
 """将异常转换为 ERROR AgentEvent。
 Args:
 error: 异常实例
 Returns:
 包含单个 ERROR 事件的列表
 """
 return [
 AgentEvent(
 type=ERROR,
 data=self._inject_metadata({"message": str(error)}),
 )
 ]
 def _adapt_result_message(self, message: Any) -> list[AgentEvent]:
 """将 ResultMessage 映射为 MESSAGE_COMPLETE 事件。"""
 result_text = str(message.result) if message.result else ""
 return [
 AgentEvent(
 type=MESSAGE_COMPLETE,
 data=self._inject_metadata({"result": result_text}),
 )
 ]
 def _adapt_stream_event(self, message: Any) -> list[AgentEvent]:
 """将 StreamEvent 映射为对应的 AgentEvent。"""
 event: dict[str, Any] = message.event
 event_type: str = event.get("type", "")
 if event_type == "content_block_delta":
 return self._adapt_content_block_delta(event)
 elif event_type == "content_block_start":
 return self._adapt_content_block_start(event)
 elif event_type == "message_delta":
 # message_delta 包含 stop_reason，内部信号，不直接发出事件
 return
 elif event_type in ("message_start", "content_block_stop", "message_stop"):
 # 这些是协议控制事件，不需要映射
 return
 else:
 # 未识别的事件类型 — 透传
 return self._adapt_unknown_event(event, event_type)
 def _adapt_content_block_delta(self, event: dict[str, Any]) -> list[AgentEvent]:
 """处理 content_block_delta 事件。"""
 delta: dict[str, Any] = event.get("delta", {})
 delta_type: str = delta.get("type", "")
 if delta_type == "text_delta":
 text: str = delta.get("text", "")
 return [
 AgentEvent(
 type=TEXT_DELTA,
 data=self._inject_metadata({"text": text}),
 )
 ]
 elif delta_type == "thinking_delta":
 thinking: str = delta.get("thinking", "")
 return [
 AgentEvent(
 type=THINKING,
 data=self._inject_metadata({"thinking": thinking}),
 )
 ]
 elif delta_type == "input_json_delta":
 # tool_use 的输入 JSON 增量，内部累积，不直接发出事件
 return
 else:
 logger.debug(
 "unhandled_delta_type",
 delta_type=delta_type,
 )
 return
 def _adapt_content_block_start(self, event: dict[str, Any]) -> list[AgentEvent]:
 """处理 content_block_start 事件。"""
 content_block: dict[str, Any] = event.get("content_block", {})
 block_type: str = content_block.get("type", "")
 if block_type == "tool_use":
 tool_name: str = content_block.get("name", "")
 tool_use_id: str = content_block.get("id", "")
 return [
 AgentEvent(
 type=TOOL_USE_START,
 data=self._inject_metadata({
 "tool_name": tool_name,
 "tool_call_id": tool_use_id,
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
 elif block_type == "text":
 # text block 开始，不需要单独事件（delta 会跟随）
 return
 else:
 logger.debug(
 "unhandled_content_block_type",
 block_type=block_type,
 )
 return
 def _adapt_unknown_event(
 self, event: dict[str, Any], event_type: str
 ) -> list[AgentEvent]:
 """将未识别的事件透传为通用 AgentEvent。"""
 logger.info(
 "unknown_stream_event_passthrough",
 event_type=event_type,
 )
 # 移除 type 字段避免冲突，其余数据透传
 data = {k: v for k, v in event.items if k != "type"}
 return [
 AgentEvent(
 type=event_type,
 data=self._inject_metadata(data),
 )
 ]

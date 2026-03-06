"""Context 窗口管理：消息截断 + tool_result 截断。
控制发送给 LLM 的消息数量和 tool_result 内容长度，
避免超出 token 限制。所有操作返回新 list，不修改原始数据。
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any
DEFAULT_MAX_MESSAGES = 50
DEFAULT_TOOL_RESULT_MAX_CHARS = 2000
TRUNCATION_MARKER = "\n\n... [内容已截断，完整结果共 {total} 字符] ..."
def truncate_messages(
 messages: list[dict[str, Any]],
 max_messages: int = DEFAULT_MAX_MESSAGES,
) -> list[dict[str, Any]]:
 """截断消息列表，保留 system 消息 + 最近 N 条非 system 消息。
 Args:
 messages: 消息列表，每条消息包含 role 和 content 字段
 max_messages: 保留的最大非 system 消息数
 Returns:
 截断后的新消息列表
 """
 system_messages = [m for m in messages if m.get("role") == "system"]
 non_system_messages = [m for m in messages if m.get("role") != "system"]
 if len(non_system_messages) <= max_messages:
 return list(messages)
 # 保留最近的 max_messages 条非 system 消息
 truncated = non_system_messages[-max_messages:]
 return system_messages + truncated
def truncate_tool_results(
 messages: list[dict[str, Any]],
 max_chars: int = DEFAULT_TOOL_RESULT_MAX_CHARS,
) -> list[dict[str, Any]]:
 """截断 tool_result 类型消息中过长的 content。
 Anthropic API 格式中，tool_result 消息的 content 可能是 list[block]，
 每个 block 可能包含 type="tool_result" 和 content 字段。
 Args:
 messages: 消息列表
 max_chars: tool_result content 的最大字符数
 Returns:
 截断后的新消息列表
 """
 result =
 for msg in messages:
 content = msg.get("content")
 if isinstance(content, list):
 new_content =
 for block in content:
 if (
 isinstance(block, dict)
 and block.get("type") == "tool_result"
 and isinstance(block.get("content"), str)
 and len(block["content"]) > max_chars
 ):
 new_block = dict(block)
 total = len(new_block["content"])
 new_block["content"] = (
 new_block["content"][:max_chars]
 + TRUNCATION_MARKER.format(total=total)
 )
 new_content.append(new_block)
 else:
 new_content.append(deepcopy(block) if isinstance(block, dict) else block)
 new_msg = dict(msg)
 new_msg["content"] = new_content
 result.append(new_msg)
 else:
 result.append(dict(msg))
 return result

"""
Google Gemini/Vertex AI LLM Provider 实现。
使用 google-genai SDK（from google import genai），支持：
- Gemini API 模式（api_key 认证）
- Vertex AI 模式（vertexai=True，服务账号认证）
重要：异步调用必须使用 client.aio.models.generate_content。
"""
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
import structlog
from google import genai
from google.genai import types
from agents.llm.base import LLMConfig
from agents.llm.types import LLMResponse, ToolCall
from agents.tools.base import ToolDefinition
logger = structlog.get_logger
class GoogleProvider:
 """Google Gemini/Vertex AI LLM Provider。
 通过 vertex_mode 参数切换 Gemini API 和 Vertex AI 模式。
 """
 def __init__(
 self,
 config: LLMConfig | None = None,
 api_key: str | None = None,
 model: str = "gemini-2.5-flash",
 vertex_mode: bool = False,
 project: str | None = None,
 location: str = "us-central1",
 ) -> None:
 if config is not None:
 self.model = config.model
 self.max_tokens = config.max_tokens
 self.temperature = config.temperature
 resolved_api_key = config.api_key
 else:
 self.model = model
 self.max_tokens = 4096
 self.temperature = 0.0
 resolved_api_key = api_key
 self.vertex_mode = vertex_mode
 if vertex_mode:
 self.client = genai.Client(
 vertexai=True,
 project=project or os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
 location=location,
 )
 else:
 self.client = genai.Client(
 api_key=resolved_api_key or os.environ.get("GEMINI_API_KEY", ""),
 )
 async def chat(
 self,
 messages: list[dict[str, Any]],
 tools: list[dict[str, Any]] | None = None,
 max_tokens: int | None = None,
 ) -> LLMResponse:
 """发送生成内容请求，将 Anthropic 格式 messages 转换为 Google genai 格式。"""
 system_instruction, contents = _convert_messages_to_genai(messages)
 genai_tools = _convert_tools_to_genai(tools) if tools else None
 config = types.GenerateContentConfig(
 max_output_tokens=max_tokens or self.max_tokens,
 temperature=self.temperature,
 )
 if system_instruction:
 config.system_instruction = system_instruction
 if genai_tools:
 config.tools = genai_tools
 # 禁用自动函数调用，由 AgentLoop 控制
 config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
 response = await self.client.aio.models.generate_content(
 model=self.model,
 contents=contents,
 config=config,
 )
 result = _parse_genai_response(response)
 logger.info(
 "llm_chat_complete",
 model=self.model,
 provider="google_genai",
 vertex_mode=self.vertex_mode,
 input_tokens=result.usage.get("input_tokens", 0),
 output_tokens=result.usage.get("output_tokens", 0),
 stop_reason=result.stop_reason,
 tool_calls=len(result.tool_calls),
 )
 return result
 async def stream_chat(
 self,
 messages: list[dict[str, Any]],
 tools: list[dict[str, Any]] | None = None,
 max_tokens: int | None = None,
 on_text: Callable[[str], Awaitable[None]] | None = None,
 ) -> LLMResponse:
 """流式生成内容请求。"""
 system_instruction, contents = _convert_messages_to_genai(messages)
 genai_tools = _convert_tools_to_genai(tools) if tools else None
 config = types.GenerateContentConfig(
 max_output_tokens=max_tokens or self.max_tokens,
 temperature=self.temperature,
 )
 if system_instruction:
 config.system_instruction = system_instruction
 if genai_tools:
 config.tools = genai_tools
 config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
 text_parts: list[str] =
 tool_calls: list[ToolCall] =
 raw_content: list[dict[str, Any]] =
 usage: dict[str, int] = {}
 async for chunk in await self.client.aio.models.generate_content_stream(
 model=self.model,
 contents=contents,
 config=config,
 ):
 # 安全遍历 chunk 中的 parts，避免 ValueError
 if chunk.candidates:
 for candidate in chunk.candidates:
 if candidate.content and candidate.content.parts:
 for part in candidate.content.parts:
 # 检查 part 类型，不要直接访问 .text
 if hasattr(part, "text") and part.text is not None:
 text_parts.append(part.text)
 if on_text:
 await on_text(part.text)
 elif hasattr(part, "function_call") and part.function_call:
 fc = part.function_call
 call_id = getattr(fc, "id", "") or f"call_{len(tool_calls)}"
 name = fc.name or ""
 args = dict(fc.args) if fc.args else {}
 tool_calls.append(ToolCall(id=call_id, name=name, arguments=args))
 # 提取 usage
 if chunk.usage_metadata:
 usage = {
 "input_tokens": getattr(chunk.usage_metadata, "prompt_token_count", 0) or 0,
 "output_tokens": getattr(chunk.usage_metadata, "candidates_token_count", 0) or 0,
 }
 content = "".join(text_parts)
 if content:
 raw_content.append({"type": "text", "text": content})
 for tc in tool_calls:
 raw_content.append({
 "type": "tool_use",
 "id": tc.id,
 "name": tc.name,
 "input": tc.arguments,
 })
 stop_reason = "end_turn" if not tool_calls else "tool_use"
 result = LLMResponse(
 content=content,
 raw_content=raw_content,
 tool_calls=tool_calls,
 usage=usage,
 stop_reason=stop_reason,
 )
 logger.info(
 "llm_stream_chat_complete",
 model=self.model,
 provider="google_genai",
 vertex_mode=self.vertex_mode,
 input_tokens=result.usage.get("input_tokens", 0),
 output_tokens=result.usage.get("output_tokens", 0),
 stop_reason=result.stop_reason,
 tool_calls=len(result.tool_calls),
 )
 return result
 def get_tool_schema(self, tools: list[ToolDefinition]) -> list[dict[str, Any]]:
 """返回 Anthropic 格式 schemas（转换在 chat 内部进行）。"""
 return [
 {"name": t.name, "description": t.description, "input_schema": t.parameters}
 for t in tools
 ]
# === Format conversion helpers ===
def _convert_messages_to_genai(
 messages: list[dict[str, Any]],
) -> tuple[str, list[types.Content] | str]:
 """将 Anthropic 格式 messages 转换为 Google genai 格式。
 Returns:
 (system_instruction, contents) 元组
 """
 system_instruction = ""
 contents: list[types.Content] =
 for msg in messages:
 role = msg.get("role", "user")
 content = msg.get("content", "")
 if role == "system":
 system_instruction = content if isinstance(content, str) else str(content)
 continue
 # Google genai 使用 "user" 和 "model"（不是 "assistant"）
 genai_role = "model" if role == "assistant" else "user"
 if isinstance(content, str):
 contents.append(types.Content(role=genai_role, parts=[types.Part.from_text(text=content)]))
 elif isinstance(content, list):
 parts: list[types.Part] =
 for block in content:
 if isinstance(block, dict):
 if block.get("type") == "text":
 parts.append(types.Part.from_text(text=block.get("text", "")))
 elif block.get("type") == "tool_use":
 # 工具调用作为 function_call
 parts.append(types.Part.from_function_call(
 name=block.get("name", ""),
 args=block.get("input", {}),
 ))
 elif block.get("type") == "tool_result":
 # 工具结果作为 function_response
 result_content = block.get("content", "")
 if isinstance(result_content, (dict, list)):
 result_content = json.dumps(result_content, ensure_ascii=False)
 parts.append(types.Part.from_function_response(
 name=block.get("tool_use_id", "unknown"),
 response={"result": str(result_content)},
 ))
 elif isinstance(block, str):
 parts.append(types.Part.from_text(text=block))
 if parts:
 contents.append(types.Content(role=genai_role, parts=parts))
 # 如果只有一条简单消息，直接传字符串
 if len(contents) == 1 and len(contents[0].parts) == 1:
 part = contents[0].parts[0]
 if hasattr(part, "text") and part.text:
 return system_instruction, part.text
 return system_instruction, contents
def _convert_tools_to_genai(
 tools: list[dict[str, Any]],
) -> list[types.Tool]:
 """将 Anthropic 格式 tools 转换为 Google genai 格式。"""
 declarations =
 for t in tools:
 declarations.append(types.FunctionDeclaration(
 name=t["name"],
 description=t.get("description", ""),
 parameters_json_schema=t.get("input_schema", {}),
 ))
 return [types.Tool(function_declarations=declarations)]
def _parse_genai_response(response: Any) -> LLMResponse:
 """解析 Google genai 响应为 LLMResponse。"""
 text_parts: list[str] =
 tool_calls: list[ToolCall] =
 raw_content: list[dict[str, Any]] =
 if response.candidates:
 candidate = response.candidates[0]
 if candidate.content and candidate.content.parts:
 for part in candidate.content.parts:
 # 安全检查 part 类型，避免 ValueError
 if hasattr(part, "text") and part.text is not None:
 text_parts.append(part.text)
 raw_content.append({"type": "text", "text": part.text})
 elif hasattr(part, "function_call") and part.function_call:
 fc = part.function_call
 call_id = getattr(fc, "id", "") or f"call_{len(tool_calls)}"
 name = fc.name or ""
 args = dict(fc.args) if fc.args else {}
 tool_calls.append(ToolCall(id=call_id, name=name, arguments=args))
 raw_content.append({
 "type": "tool_use",
 "id": call_id,
 "name": name,
 "input": args,
 })
 # Usage
 usage: dict[str, int] = {}
 if response.usage_metadata:
 usage = {
 "input_tokens": getattr(response.usage_metadata, "prompt_token_count", 0) or 0,
 "output_tokens": getattr(response.usage_metadata, "candidates_token_count", 0) or 0,
 }
 stop_reason = "end_turn" if not tool_calls else "tool_use"
 return LLMResponse(
 content="\n".join(text_parts),
 raw_content=raw_content,
 tool_calls=tool_calls,
 usage=usage,
 stop_reason=stop_reason,
 )

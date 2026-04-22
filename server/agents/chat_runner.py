"""ChatAnthropicRunner：LangGraph Chat 场景的 LangChain 执行器。
使用 ChatAnthropic + 现有本地工具定义实现：
- 普通流式文本输出
- tool call 执行与事件回放
- deep_analysis blocking marker 透传
- interrupt 中断
"""
from __future__ import annotations
import asyncio
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, cast
import structlog
from django.utils import timezone
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model
# 触发 @tool 注册
import agents.tools.chat_tools # noqa: F401
import agents.tools.coding_tools # noqa: F401
import agents.tools.project_tools # noqa: F401
from agents.core.events import (
 ERROR,
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_RESULT,
 TOOL_USE_START,
 AgentEvent,
)
from agents.core.result import AgentResult
from agents.langchain_runner import (
 _CONTEXT_SAFETY_BUFFER,
 ContextWindowExceededError,
)
from agents.models import AgentSession, ToolCallLog
from agents.tools.base import ToolDefinition, ToolResult, _tool_registry
from agents.tools.langchain_adapter import build_langchain_tools
from repositories.models import Repository
from services.model_capabilities import ModelCapabilities
from services.provider_config import ProviderType
logger = structlog.get_logger(__name__)
_BASE_TOOL_NAMES = ["get_project_overview"]
_FULL_TOOL_NAMES = _BASE_TOOL_NAMES + [
 "browse_file_content",
 "list_project_structure",
 "search_repository_code",
 "list_project_repositories",
 "get_repository_info",
 "deep_analysis",
 "create_coding_plan",
 "update_coding_plan",
]
@dataclass
class ChatRunnerConfig:
 """Chat 场景运行配置。"""
 system_prompt: str
 model: str
 project_id: str
 session_id: str
 conversation_id: str = ""
 api_key: str = ""
 api_base_url: str = ""
 max_turns: int = 30
 timeout_seconds: float = 0
 agent_session: Any = field(default=None)
 max_budget_usd: float | None = None
 default_search_branch: str | None = None
@dataclass
class _ChatToolSpec:
 """LangChain tool 与本地执行器的桥接定义。"""
 tool: StructuredTool
 definition: ToolDefinition
 execute: Any
def _inject_metadata(data: dict[str, Any], model: str, session_id: str) -> dict[str, Any]:
 payload = dict(data)
 payload["model"] = model
 payload["session_id"] = session_id
 return payload
def _schema_type_to_python(prop: dict[str, Any]) -> Any:
 schema_type = prop.get("type", "string")
 if isinstance(schema_type, list):
 non_null = [item for item in schema_type if item != "null"]
 schema_type = non_null[0] if non_null else "string"
 return {
 "string": str,
 "integer": int,
 "number": float,
 "boolean": bool,
 "object": dict[str, Any],
 "array": list[Any],
 }.get(schema_type, Any)
def _build_args_schema(tool_def: ToolDefinition, hidden_fields: set[str]) -> type[BaseModel]:
 properties = tool_def.parameters.get("properties", {})
 required = set(tool_def.parameters.get("required", )) - hidden_fields
 fields: dict[str, tuple[Any, Any]] = {}
 for name, prop in properties.items:
 if name in hidden_fields:
 continue
 annotation = _schema_type_to_python(prop)
 description = prop.get("description", "")
 if name in required:
 default = Field(..., description=description)
 else:
 default = Field(prop.get("default", None), description=description)
 fields[name] = (annotation, default)
 model_name = "".join(part.capitalize for part in tool_def.name.split("_")) + "Args"
 return create_model(model_name, **cast(dict[str, Any], fields))
async def _get_tool_names(project_id: str) -> list[str]:
 has_indexed = await Repository.objects.filter(
 projects__id=project_id,
 index_status="indexed",
 is_deleted=False,
 ).aexists
 return _FULL_TOOL_NAMES if has_indexed else _BASE_TOOL_NAMES
def _extract_content_blocks(message: Any) -> list[dict[str, Any]]:
 blocks = getattr(message, "content_blocks", None)
 if isinstance(blocks, list):
 return [block for block in blocks if isinstance(block, dict)]
 content = getattr(message, "content", None)
 if isinstance(content, list):
 return [block for block in content if isinstance(block, dict)]
 if isinstance(content, str) and content:
 return [{"type": "text", "text": content}]
 return
def _extract_message_text(message: Any) -> str:
 text = getattr(message, "text", "")
 if isinstance(text, str) and text:
 return text
 parts: list[str] =
 for block in _extract_content_blocks(message):
 if block.get("type") == "text" and block.get("text"):
 parts.append(str(block["text"]))
 return "".join(parts)
def _extract_usage(message: Any) -> dict[str, int]:
 usage = getattr(message, "usage_metadata", None) or getattr(message, "response_metadata", {}).get("usage")
 if not isinstance(usage, dict):
 return {}
 return {
 "input_tokens": int(usage.get("input_tokens", 0) or 0),
 "output_tokens": int(usage.get("output_tokens", 0) or 0),
 }
def _thinking_budget_tokens(model: str) -> int | None:
 lowered = model.lower
 if "claude" not in lowered:
 return None
 if (
 "thinking" in lowered
 or "sonnet-4" in lowered
 or "opus-4" in lowered
 or "3-7" in lowered
 or "3.7" in lowered
 ):
 return 4096
 return None
async def _persist_usage(agent_session: AgentSession | None, usage: dict[str, int]) -> None:
 if agent_session is None:
 return
 try:
 agent_session.add_usage(
 usage.get("input_tokens", 0),
 usage.get("output_tokens", 0),
 )
 await AgentSession.objects.filter(session_id=agent_session.session_id).aupdate(
 metadata=agent_session.metadata,
 )
 except Exception:
 logger.exception("agent_session_usage_update_failed", session_id=agent_session.session_id)
async def _log_tool_call(
 agent_session: AgentSession | None,
 *,
 tool_name: str,
 tool_call_id: str,
 arguments: dict[str, Any],
 result: ToolResult,
) -> None:
 if agent_session is None:
 return
 try:
 iteration = agent_session.increment_tool_calls
 now = timezone.now
 await AgentSession.objects.filter(session_id=agent_session.session_id).aupdate(
 metadata=agent_session.metadata,
 )
 await ToolCallLog.objects.acreate(
 session=agent_session,
 tool_name=tool_name,
 tool_call_id=tool_call_id,
 arguments=arguments,
 result_success=result.success,
 result_output=result.output,
 result_error=result.error or "",
 started_at=now,
 completed_at=now,
 duration_ms=0,
 iteration=iteration,
 )
 except Exception:
 logger.exception(
 "chat_tool_log_write_failed",
 tool_name=tool_name,
 tool_use_id=tool_call_id,
 session_id=agent_session.session_id,
 )
def _normalize_tool_result(result: ToolResult) -> Any:
 if result.success:
 return result.output
 return {"error": result.error or "未知错误", "is_error": True}
def _build_message_complete(
 *,
 final_answer: str,
 usage: dict[str, int],
 model: str,
 session_id: str,
 status: str = "completed",
) -> AgentEvent:
 return AgentEvent(
 type=MESSAGE_COMPLETE,
 data=_inject_metadata(
 {
 "final_answer": final_answer,
 "result": final_answer,
 "status": status,
 "usage": usage,
 "cost_usd": 0,
 },
 model,
 session_id,
 ),
 )
def _check_chat_context_window(
 messages: list[Any],
 *,
 model: str,
 max_output_tokens: int = 4096,
) -> None:
 """前 astream budget check（strict_error 策略）；超限抛 ContextWindowExceededError。
 消息格式与 ``langchain_runner.py`` 共用，保证 ``base_agent.py``
 的 regex 可复用（Phase Pitfall 1 单一事实源 / Pitfall 3 每 turn
 check）。
 Args:
 messages: LangChain message 列表（含 accumulated ToolMessage）。
 model: Anthropic model id（caller 传 ``self._config.model``）。
 max_output_tokens: 可选覆盖；0 / None 走 ``caps.max_output_tokens``。
 """
 caps = ModelCapabilities.get(str(ProviderType.ANTHROPIC), model)
 effective_max_out = max_output_tokens or caps.max_output_tokens
 budget = caps.max_input_tokens - effective_max_out - _CONTEXT_SAFETY_BUFFER
 current = count_tokens_approximately(messages)
 if current > budget:
 raise ContextWindowExceededError(
 f"context too long: {current} tokens > budget {budget} "
 f"(max_input={caps.max_input_tokens}, "
 f"max_output={effective_max_out}, "
 f"buffer={_CONTEXT_SAFETY_BUFFER})"
 )
def _make_agent_result(
 *,
 status: str,
 usage: dict[str, int],
 final_answer: str | None = None,
 error: str | None = None,
 metadata: dict[str, Any] | None = None,
) -> AgentResult:
 return AgentResult(,
 status,
 final_answer,
 usage,
 metadata or {},
 error,
 )
async def _build_tool_specs(
 project_id: str,
 conversation_id: str,
 *,
 default_search_branch: str | None = None,
) -> dict[str, _ChatToolSpec]:
 """装配 chat 场景可用的工具清单。
 内部通过 `build_langchain_tools` (Phase) 统一产出 StructuredTool：
 project_id / conversation_id 由 adapter 从 args_schema 剔除 + 闭包注入。
 `default_search_branch` "LLM 未提供 branch 时回填"语义属于 chat 场景特有
 （非强制覆盖；Pitfall #12 / Q2 选项 B），保留在本二次闭包中，不下沉到
 adapter。二次闭包 `execute(arguments: dict) -> ToolResult` 的签名保持
 不变，下游 `_execute_tool_call` 契约零破坏。
 """
 tool_names = await _get_tool_names(project_id)
 langchain_tools = build_langchain_tools(
 tool_names,
 injected_values={
 "project_id": project_id,
 "conversation_id": conversation_id,
 },
 )
 tool_specs: dict[str, _ChatToolSpec] = {}
 for lc_tool in langchain_tools:
 tool_def = _tool_registry[lc_tool.name]
 properties = tool_def.parameters.get("properties", {})
 injected_values: dict[str, Any] = {}
 if "project_id" in properties:
 injected_values["project_id"] = project_id
 if "conversation_id" in properties:
 injected_values["conversation_id"] = conversation_id
 async def _execute(
 arguments: dict[str, Any],
 *,
 _tool_def: ToolDefinition = tool_def,
 _injected: dict[str, Any] = injected_values,
 _props: dict[str, Any] = properties,
 _dsb: str | None = default_search_branch,
 ) -> ToolResult:
 merged = {**_injected, **arguments}
 # Pitfall #12：LLM 未提供 branch 时用 default，非无条件覆盖
 if "branch" in _props and _dsb:
 cur = merged.get("branch")
 if cur in (None, ""):
 merged["branch"] = _dsb
 return await _tool_def.func(**merged)
 tool_specs[lc_tool.name] = _ChatToolSpec(
 tool=lc_tool, # type: ignore[arg-type]
 definition=tool_def,
 execute=_execute,
 )
 return tool_specs
class ChatAnthropicRunner:
 """基于 ChatAnthropic 的 Chat 执行器。"""
 def __init__(self, config: ChatRunnerConfig) -> None:
 self._config = config
 self._result: AgentResult | None = None
 self._run_task: asyncio.Task[Any] | None = None
 @property
 def result(self) -> AgentResult | None:
 return self._result
 async def interrupt(self) -> None:
 if self._run_task and not self._run_task.done:
 self._run_task.cancel
 logger.info("chat_runner_interrupted", session_id=self._config.session_id)
 def _build_model(self) -> ChatAnthropic:
 kwargs: dict[str, Any] = {
 "model_name": self._config.model,
 "api_key": self._config.api_key,
 "streaming": True,
 }
 thinking_budget = _thinking_budget_tokens(self._config.model)
 if thinking_budget is not None:
 kwargs["thinking"] = {
 "type": "enabled",
 "budget_tokens": thinking_budget,
 }
 # Anthropic thinking 模式要求 temperature=1
 kwargs["temperature"] = 1
 if self._config.api_base_url:
 kwargs["base_url"] = self._config.api_base_url
 if self._config.timeout_seconds > 0:
 kwargs["timeout"] = self._config.timeout_seconds
 return ChatAnthropic(**kwargs)
 async def _execute_tool_call(
 self,
 tool_specs: dict[str, _ChatToolSpec],
 *,
 tool_name: str,
 tool_call_id: str,
 arguments: dict[str, Any],
 ) -> tuple[ToolResult, ToolMessage]:
 spec = tool_specs[tool_name]
 result = await spec.execute(arguments)
 await _log_tool_call(
 self._config.agent_session,
 tool_name=tool_name,
 tool_call_id=tool_call_id,
 arguments=arguments,
 result=result,
 )
 tool_message = ToolMessage(
 content=result.to_content,
 tool_call_id=tool_call_id,
 name=tool_name,
 status="success" if result.success else "error",
 artifact=result.output,
 )
 return result, tool_message
 async def stream(self, prompt: str): # type: ignore[override]
 if not self._config.api_key:
 raise ValueError("ChatRunnerConfig.api_key 不能为空")
 model = self._build_model
 tool_specs = await _build_tool_specs(
 self._config.project_id,
 self._config.conversation_id,
 default_search_branch=self._config.default_search_branch,
 )
 model_with_tools = model.bind_tools([spec.tool for spec in tool_specs.values])
 messages: list[Any] = [
 SystemMessage(content=self._config.system_prompt),
 HumanMessage(content=prompt),
 ]
 total_usage = {"input_tokens": 0, "output_tokens": 0}
 accumulated_text: list[str] =
 self._run_task = asyncio.current_task
 try:
 for _ in range(self._config.max_turns):
 full_message: AIMessageChunk | None = None
 # Phase Plan：每 turn 进入 astream 前做前置 budget check。
 # messages 会随 ToolMessage 累积增长，必须每轮 check，不能只 turn 0 check
 # （Pitfall 3）。超限抛 ContextWindowExceededError，由下方专属 except 分支捕获。
 _check_chat_context_window(messages, model=self._config.model)
 async for chunk in model_with_tools.astream(messages):
 if not isinstance(chunk, AIMessageChunk):
 continue
 full_message = chunk if full_message is None else full_message + chunk
 for block in _extract_content_blocks(chunk):
 block_type = block.get("type")
 if block_type == "text" and block.get("text"):
 text = str(block["text"])
 accumulated_text.append(text)
 yield AgentEvent(
 type=TEXT_DELTA,
 data=_inject_metadata({"text": text}, self._config.model, self._config.session_id),
 )
 elif block_type in {"reasoning", "thinking"}:
 reasoning = block.get("reasoning") or block.get("thinking") or block.get("text")
 if reasoning:
 yield AgentEvent(
 type=THINKING,
 data=_inject_metadata(
 {"thinking": str(reasoning)},
 self._config.model,
 self._config.session_id,
 ),
 )
 if full_message is None:
 continue
 usage = _extract_usage(full_message)
 total_usage["input_tokens"] += usage.get("input_tokens", 0)
 total_usage["output_tokens"] += usage.get("output_tokens", 0)
 await _persist_usage(self._config.agent_session, usage)
 messages.append(full_message)
 tool_calls = getattr(full_message, "tool_calls", )
 if tool_calls:
 blocking_marker_seen = False
 for tool_call in tool_calls:
 tool_name = str(tool_call.get("name", ""))
 tool_call_id = str(tool_call.get("id", "") or f"tool_{uuid.uuid4.hex[:8]}")
 arguments = tool_call.get("args", {})
 if tool_name not in tool_specs:
 error_msg = f"未知工具: {tool_name}"
 yield AgentEvent(
 type=ERROR,
 data=_inject_metadata({"message": error_msg}, self._config.model, self._config.session_id),
 )
 self._result = _make_agent_result(
 status="error",
 error=error_msg,
 usage=total_usage,
 )
 return
 yield AgentEvent(
 type=TOOL_USE_START,
 data=_inject_metadata(
 {
 "tool_name": tool_name,
 "tool_call_id": tool_call_id,
 "input": arguments,
 },
 self._config.model,
 self._config.session_id,
 ),
 )
 result, tool_message = await self._execute_tool_call(
 tool_specs,
 tool_name=tool_name,
 tool_call_id=tool_call_id,
 arguments=arguments,
 )
 raw_result = _normalize_tool_result(result)
 yield AgentEvent(
 type=TOOL_USE_RESULT,
 data=_inject_metadata(
 {
 "tool_name": tool_name,
 "tool_call_id": tool_call_id,
 "success": result.success,
 "input": arguments,
 "result": raw_result,
 },
 self._config.model,
 self._config.session_id,
 ),
 )
 messages.append(tool_message)
 if isinstance(result.output, dict) and result.output.get("__blocking_task__"):
 blocking_marker_seen = True
 if blocking_marker_seen:
 self._result = _make_agent_result(
 status="completed",
 final_answer="".join(accumulated_text),
 usage=total_usage,
 metadata={"cost_usd": 0},
 )
 return
 continue
 final_answer = _extract_message_text(full_message)
 self._result = _make_agent_result(
 status="completed",
 final_answer=final_answer,
 usage=total_usage,
 metadata={"cost_usd": 0},
 )
 yield _build_message_complete(
 final_answer=final_answer,
 usage=total_usage,
 model=self._config.model,
 session_id=self._config.session_id,
 )
 return
 self._result = _make_agent_result(
 status="error",
 error="达到最大 tool 调用轮次限制",
 usage=total_usage,
 )
 yield AgentEvent(
 type=ERROR,
 data=_inject_metadata(
 {"message": "达到最大 tool 调用轮次限制"},
 self._config.model,
 self._config.session_id,
 ),
 )
 except asyncio.CancelledError:
 partial_text = "".join(accumulated_text)
 self._result = _make_agent_result(
 status="interrupted",
 final_answer=partial_text,
 usage=total_usage,
 metadata={"cost_usd": 0},
 )
 yield _build_message_complete(
 final_answer=partial_text,
 usage=total_usage,
 model=self._config.model,
 session_id=self._config.session_id,
 status="interrupted",
 )
 raise
 except ContextWindowExceededError as exc:
 # Phase chat 路径集成：SSE ERROR 结构化 payload。
 # 消息格式同源 ``langchain_runner.py`` strict_error；
 # regex / payload schema 照抄 ``base_agent.py`` （字段名差异：
 # base_agent 走 NodeResult.output["error_code"]；chat_runner 直接
 # yield AgentEvent data={"code": ...}，前端 stores/chat.ts:work-item
 # 读 event.code / event.data —— Pitfall 8）。
 # 位置：严格在 CancelledError 之后、generic Exception 之前（Pitfall 2）。
 msg = str(exc)
 m = re.match(
 r"context too long: (\d+) tokens > budget (\d+) "
 r"\(max_input=(\d+), max_output=(\d+), buffer=(\d+)\)",
 msg,
 )
 if m is not None:
 estimated = int(m.group(1))
 budget = int(m.group(2))
 exceeded = max(0, estimated - budget)
 else:
 estimated = 0
 budget = 0
 exceeded = 0
 # structlog kwargs 风格 —— redact_credentials processor 兜底；
 # 禁止 f-string 插入任何可能的凭证值（V4 ASVS Information Disclosure，
 # T- / T- mitigation）。字段白名单：
 # session_id / model / estimated_tokens / max_tokens / exceeded_by。
 logger.warning(
 "chat_runner_context_exceeded",
 session_id=self._config.session_id,
 model=self._config.model,
 estimated_tokens=estimated,
 max_tokens=budget,
 exceeded_by=exceeded,
 )
 self._result = _make_agent_result(
 status="error",
 error=msg,
 usage=total_usage,
 )
 yield AgentEvent(
 type=ERROR,
 data=_inject_metadata(
 {
 "code": "context_window_exceeded",
 "message": msg,
 "data": {
 "estimated_tokens": estimated,
 "max_tokens": budget,
 "exceeded_by": exceeded,
 "model": self._config.model,
 "recommended_actions": [
 {
 "id": "trim_prompt",
 "label": "精简 system prompt",
 "action_type": "navigate",
 "target": "/prompts/",
 },
 {
 "id": "switch_model",
 "label": "换大 context 模型",
 "action_type": "navigate",
 "target": "settings.model",
 },
 {
 "id": "cleanup_history",
 "label": "清理对话历史",
 "action_type": "dialog",
 "target": "CleanupDialog",
 },
 ],
 },
 },
 self._config.model,
 self._config.session_id,
 ),
 )
 except Exception as exc:
 logger.exception("chat_runner_error", session_id=self._config.session_id)
 self._result = _make_agent_result(
 status="error",
 error=str(exc),
 usage=total_usage,
 )
 yield AgentEvent(
 type=ERROR,
 data=_inject_metadata({"message": str(exc)}, self._config.model, self._config.session_id),
 )
 finally:
 self._run_task = None

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
from langchain_core.runnables import Runnable
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model
# 触发 @tool 注册
import agents.tools.chat_tools # noqa: F401
import agents.tools.coding_tools # noqa: F401
import agents.tools.space_tools # noqa: F401
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
from agents.tool_budget import _ToolBudget
from agents.tools.base import ToolDefinition, ToolResult, _tool_registry
from agents.tools.langchain_adapter import build_langchain_tools
from repositories.models import Repository
from services.model_capabilities import ModelCapabilities
from services.provider_config import ProviderType
logger = structlog.get_logger(__name__)
_BASE_TOOL_NAMES = ["get_space_overview"]
# 普通模式：检索 + 代码浏览 + coding plan，但 **不含 deep_analysis**。
# 只有用户在前端显式开启「深度分析」开关时，deep_analysis 才会进入工具列表
# （由 _get_tool_names(force_deep_analysis=True) 控制）。
# 该闸门避免 LLM 在普通问答中被系统 prompt 诱导自主调用 deep_analysis ——
# 历史上这会导致一次普通追问消耗一次远程 Runner 容器，体验差且成本高。
_INDEXED_TOOL_NAMES = _BASE_TOOL_NAMES + [
 "browse_file_content",
 "list_space_structure",
 "search_repository_code",
 "list_space_repositories",
 "get_repository_info",
 "create_coding_plan",
 "update_coding_plan",
]
_DEEP_ANALYSIS_TOOL_NAMES = _INDEXED_TOOL_NAMES + ["deep_analysis"]
@dataclass
class ChatRunnerConfig:
 """Chat 场景运行配置。"""
 system_prompt: str
 model: str
 space_id: str
 session_id: str
 conversation_id: str = ""
 api_key: str = ""
 api_base_url: str = ""
 max_turns: int = 30
 timeout_seconds: float = 0
 agent_session: Any = field(default=None)
 max_budget_usd: float | None = None
 default_search_branch: str | None = None
 # 用户是否显式开启「深度分析」开关。仅当 True 时 deep_analysis 工具会被
 # 暴露给 LLM 并下发"策略二"system prompt。
 force_deep_analysis: bool = False
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
async def _get_tool_names(
 space_id: str, *, force_deep_analysis: bool = False,
) -> list[str]:
 """返回 LLM 可用工具名列表。
 - 无已索引仓库：仅 `_BASE_TOOL_NAMES`（避免误调检索工具拿空结果）。
 - 有已索引仓库 + 普通模式：`_INDEXED_TOOL_NAMES`，**不含** `deep_analysis`。
 - 有已索引仓库 + 用户开启「深度分析」开关：`_DEEP_ANALYSIS_TOOL_NAMES`。
 """
 has_indexed = await Repository.objects.filter(
 projects__id=space_id,
 index_status="indexed",
 is_deleted=False,
 ).aexists
 if not has_indexed:
 return _BASE_TOOL_NAMES
 return _DEEP_ANALYSIS_TOOL_NAMES if force_deep_analysis else _INDEXED_TOOL_NAMES
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
 space_id: str,
 conversation_id: str,
 *,
 default_search_branch: str | None = None,
 force_deep_analysis: bool = False,
) -> dict[str, _ChatToolSpec]:
 """装配 chat 场景可用的工具清单。
 内部通过 `build_langchain_tools` (Phase) 统一产出 StructuredTool：
 space_id / conversation_id 由 adapter 从 args_schema 剔除 + 闭包注入。
 `default_search_branch` "LLM 未提供 branch 时回填"语义属于 chat 场景特有
 （非强制覆盖；Pitfall #12 / Q2 选项 B），保留在本二次闭包中，不下沉到
 adapter。二次闭包 `execute(arguments: dict) -> ToolResult` 的签名保持
 不变，下游 `_execute_tool_call` 契约零破坏。
 """
 tool_names = await _get_tool_names(
 space_id, force_deep_analysis=force_deep_analysis,
 )
 langchain_tools = build_langchain_tools(
 tool_names,
 injected_values={
 "space_id": space_id,
 "conversation_id": conversation_id,
 },
 )
 tool_specs: dict[str, _ChatToolSpec] = {}
 for lc_tool in langchain_tools:
 tool_def = _tool_registry[lc_tool.name]
 properties = tool_def.parameters.get("properties", {})
 injected_values: dict[str, Any] = {}
 if "space_id" in properties:
 injected_values["space_id"] = space_id
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
 # Phase：按 schema properties 过滤 LLM 自创的未知字段。
 # 背景：LLM 偶尔会在 tool_call.args 里塞 schema 不存在的字段（比如
 # 对只接受 space_id 的 list_space_structure 传了 repository_id）。
 # LangChain 的 bind_tools 不强校验 schema，这些未知字段会被原样
 # 透传，unpack 到工具函数时直接抛 TypeError 让整轮失败。
 # 静默 drop 这些字段比硬抛 TypeError 友好：保留 LLM 真实想做的事
 # （调这个工具），下一轮 LLM 看到 ToolMessage 会自己修正参数。
 allowed = set(_props.keys)
 unknown = set(arguments.keys) - allowed
 if unknown:
 logger.warning(
 "chat_runner_dropped_unknown_tool_args",
 tool_name=_tool_def.name,
 dropped_args=sorted(unknown),
 allowed_args=sorted(allowed),
 )
 arguments = {k: v for k, v in arguments.items if k in allowed}
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
 budget: _ToolBudget,
 ) -> tuple[ToolResult, ToolMessage, bool]:
 """执行一次工具调用，受 ``_ToolBudget`` 拦截。
 Returns:
 ``(result, tool_message, intercepted)``：``intercepted=True`` 表示
 该调用被去重 / 文件硬上限拦截，未真实执行（也不会写 ToolCallLog，
 避免污染观测）。``tool_message`` 的 content 已附加预算提示。
 """
 decision = budget.precheck(tool_name, arguments)
 if decision.intercepted and decision.intercepted_result is not None:
 result = decision.intercepted_result
 logger.info(
 "chat_runner_tool_intercepted",
 session_id=self._config.session_id,
 tool_name=tool_name,
 tool_call_id=tool_call_id,
 reason=decision.reason,
 remaining=budget.remaining,
 )
 else:
 spec = tool_specs[tool_name]
 result = await spec.execute(arguments)
 await _log_tool_call(
 self._config.agent_session,
 tool_name=tool_name,
 tool_call_id=tool_call_id,
 arguments=arguments,
 result=result,
 )
 budget.record(tool_name, arguments, result)
 tool_message = ToolMessage(
 content=budget.annotate(result.to_content),
 tool_call_id=tool_call_id,
 name=tool_name,
 status="success" if result.success else "error",
 artifact=result.output,
 )
 return result, tool_message, decision.intercepted
 async def stream(self, prompt: str): # type: ignore[override]
 if not self._config.api_key:
 raise ValueError("ChatRunnerConfig.api_key 不能为空")
 model = self._build_model
 tool_specs = await _build_tool_specs(
 self._config.space_id,
 self._config.conversation_id,
 default_search_branch=self._config.default_search_branch,
 force_deep_analysis=self._config.force_deep_analysis,
 )
 model_with_tools = model.bind_tools([spec.tool for spec in tool_specs.values])
 messages: list[Any] = [
 SystemMessage(content=self._config.system_prompt),
 HumanMessage(content=prompt),
 ]
 total_usage = {"input_tokens": 0, "output_tokens": 0}
 accumulated_text: list[str] =
 self._run_task = asyncio.current_task
 # Phase：单 stream 工具预算控制（去重 + 单文件硬上限 + 剩余
 # 预算注入 + 强制 final-turn）。详见 agents/tool_budget.py。
 budget = _ToolBudget(max_turns=self._config.max_turns)
 try:
 for _ in range(self._config.max_turns):
 full_message: AIMessageChunk | None = None
 # Phase Plan：每 turn 进入 astream 前做前置 budget check。
 # messages 会随 ToolMessage 累积增长，必须每轮 check，不能只 turn 0 check
 # （Pitfall 3）。超限抛 ContextWindowExceededError，由下方专属 except 分支捕获。
 _check_chat_context_window(messages, model=self._config.model)
 # Phase：剩余 ≤ BUDGET_FORCE_FINAL_AT 时切到原始 model
 # （未 bind_tools），强制 LLM 基于已收集信息出最终回答，避免硬抛
 # MaxTurnsExceeded 丢弃中间产出（OpenAI Agents SDK 反模式）。
 # active_model 是 ChatAnthropic | Runnable 联合，astream 接口
 # 一致 —— 显式注解防 mypy 推断成更窄的 ChatAnthropic。
 active_model: ChatAnthropic | Runnable[Any, Any]
 if budget.should_force_final:
 active_model = model
 logger.info(
 "chat_runner_force_final_turn",
 session_id=self._config.session_id,
 remaining=budget.remaining,
 max_turns=self._config.max_turns,
 )
 else:
 active_model = model_with_tools
 async for chunk in active_model.astream(messages):
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
 # 同一个 LLM response 内多个 tool_call 共享 batch_id，前端据此
 # 渲染为"同批并行"的横向 chip 流。语义对齐：LLM 一次决定要调
 # 哪几个工具就是一批，即使执行上是串行的（执行串行是当前实现
 # 细节，未来若改并发也不影响 batch 语义）。
 batch_id = f"batch_{uuid.uuid4.hex[:8]}" if len(tool_calls) > 1 else ""
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
 start_payload: dict[str, Any] = {
 "tool_name": tool_name,
 "tool_call_id": tool_call_id,
 "input": arguments,
 }
 if batch_id:
 start_payload["batch_id"] = batch_id
 yield AgentEvent(
 type=TOOL_USE_START,
 data=_inject_metadata(
 start_payload,
 self._config.model,
 self._config.session_id,
 ),
 )
 result, tool_message, intercepted = await self._execute_tool_call(
 tool_specs,
 tool_name=tool_name,
 tool_call_id=tool_call_id,
 arguments=arguments,
 budget=budget,
 )
 raw_result = _normalize_tool_result(result)
 tool_event_data: dict[str, Any] = {
 "tool_name": tool_name,
 "tool_call_id": tool_call_id,
 "success": result.success,
 "input": arguments,
 "result": raw_result,
 }
 if batch_id:
 tool_event_data["batch_id"] = batch_id
 # 前端可据此 flag 提示「该次调用被自动去重/拒绝，未真实执行」
 if intercepted:
 tool_event_data["budget_intercepted"] = True
 yield AgentEvent(
 type=TOOL_USE_RESULT,
 data=_inject_metadata(
 tool_event_data,
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
 budget.on_turn_complete
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
 # Phase：max_turns 真用尽（含 force-final 那一轮）才会到这里。
 # 之前的实现直接返 status="error"，丢失已累积的 accumulated_text（reference
 # cards 也无法挂载）。改为 graceful degrade：status="completed" + metadata
 # 标记 degraded=True；若模型在 force-final turn 已经吐了 partial text，
 # 直接交付，否则给一个明确的"未完成"占位，让前端展示「已尽力」状态而非 error。
 partial_text = "".join(accumulated_text)
 degraded_answer = partial_text or (
 "（工具调用预算已耗尽，未能在 "
 f"{self._config.max_turns} 轮内完成检索。建议换更精确的提问，"
 "或在前端启用「深度分析」开关将任务转交远程 Claude Code 容器。）"
 )
 logger.warning(
 "chat_runner_max_turns_exhausted",
 session_id=self._config.session_id,
 max_turns=self._config.max_turns,
 produced_partial=bool(partial_text),
 )
 self._result = _make_agent_result(
 status="completed",
 final_answer=degraded_answer,
 usage=total_usage,
 metadata={
 "cost_usd": 0,
 "degraded": True,
 "degraded_reason": "max_turns_exhausted",
 "max_turns": self._config.max_turns,
 },
 )
 yield AgentEvent(
 type=MESSAGE_COMPLETE,
 data=_inject_metadata(
 {
 "final_answer": degraded_answer,
 "result": degraded_answer,
 "status": "completed",
 "degraded": True,
 "degraded_reason": "max_turns_exhausted",
 "usage": total_usage,
 "cost_usd": 0,
 },
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
 # Phase：原局部变量名为 budget，与方法顶部 _ToolBudget
 # 实例同名冲突（mypy 类型不兼容报错）。改名为 ctx_budget 区分语义
 # ——这里是 context window token budget，不是 tool 调用预算。
 if m is not None:
 estimated = int(m.group(1))
 ctx_budget = int(m.group(2))
 exceeded = max(0, estimated - ctx_budget)
 else:
 estimated = 0
 ctx_budget = 0
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
 max_tokens=ctx_budget,
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
 "max_tokens": ctx_budget,
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

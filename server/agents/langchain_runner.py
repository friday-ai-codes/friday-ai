"""LangChainAgentRunner —— 工作流 AI 节点通用 Runner（Phase/03/06）。
基于 LangChain `init_chat_model` 多 Provider + 朴素 ReAct loop 实现；
与 `chat_runner.py` 并存（场景差异：workflow 节点无 MCP / 无 deep_analysis / 纯 ReAct）。
**三重禁线（由静态断言测试强制）：**
- 禁止嵌入 LangGraph 子图执行器（REQUIREMENTS + RESEARCH Pitfall 9 + Out of Scope）
- 禁止自写 tool_call 归一化层（REQUIREMENTS，信任 LangChain bind_tools 归一化）
- 禁止迁移到事件流 v2（RESEARCH Pitfall 8，保持 AIMessageChunk 累加）
（具体禁止符号见 tests/ 下同 phase 两个静态断言测试文件的 AST / 字符串断言）
设计锚点：
- chat_runner.py `_inject_metadata` + `_extract_content_blocks/text` 一字不改
- chat_runner.py ReAct 主循环 6 处修改点（PATTERNS §1.4）
- RESEARCH Example 3 `_extract_usage` 六字段分派
- CONTEXT AgentEvent.data 字段锁跨 Provider 契约
参考：`project-docs/phases/work-item/work-item.md` §1.1-1.8 + S-1~S-7。
"""
from __future__ import annotations
import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Literal, cast
import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
 AIMessage,
 AIMessageChunk,
 BaseMessage,
 HumanMessage,
 ToolMessage,
)
from langchain_core.tools import BaseTool
from agents.core.events import (
 BUDGET_WARNING,
 ERROR,
 MESSAGE_COMPLETE,
 TEXT_DELTA,
 THINKING,
 TOOL_USE_RESULT,
 TOOL_USE_START,
 AgentEvent,
)
from agents.core.result import AgentResult
from agents.llm_factory import build_chat_model
from agents.types import TokenUsage
from services.model_capabilities import ModelCapabilitiesEntry
from services.provider_config import ResolvedProviderConfig
logger = structlog.get_logger(__name__)
class ContextWindowExceededError(Exception):
 """Context window 预算超限（，继承 Exception 避免掩盖其他 ValueError）。"""
# ========== helpers（PATTERNS §1.2 / §1.3 —— 与 chat_runner.py 对齐） ==========
def _inject_metadata(data: dict[str, Any], model: str, session_id: str) -> dict[str, Any]:
 """：所有 AgentEvent.data 注入 {model, session_id} 确保跨 Provider 字段一致性。"""
 payload = dict(data)
 payload["model"] = model
 payload["session_id"] = session_id
 return payload
def _extract_content_blocks(message: Any) -> list[dict[str, Any]]:
 """LangChain `output_version='v1'` content_blocks 迭代（chat_runner.py 一字不改 copy）。"""
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
 """chat_runner.py 一字不改 copy。"""
 text = getattr(message, "text", "")
 if isinstance(text, str) and text:
 return text
 parts: list[str] =
 for block in _extract_content_blocks(message):
 if block.get("type") == "text" and block.get("text"):
 parts.append(str(block["text"]))
 return "".join(parts)
def _extract_usage(aimsg: AIMessage | AIMessageChunk) -> TokenUsage:
 """ 六字段 TokenUsage 分派（RESEARCH Example 3 权威模板）。
 字段矩阵（按 LangChain `usage_metadata` 标准）：
 - input ← input_tokens
 - output ← output_tokens
 - cached_input ← input_token_details.cache_read（Anthropic prompt caching 命中）
 - cache_creation ← input_token_details.cache_creation（Anthropic prompt caching 创建）
 - reasoning ← output_token_details.reasoning（OpenAI o 系列）/ .thoughts（Gemini）
 """
 meta = getattr(aimsg, "usage_metadata", None) or {}
 if not isinstance(meta, dict):
 return {}
 result: TokenUsage = {
 "input": int(meta.get("input_tokens", 0) or 0),
 "output": int(meta.get("output_tokens", 0) or 0),
 }
 input_details = meta.get("input_token_details") or {}
 output_details = meta.get("output_token_details") or {}
 if isinstance(input_details, dict):
 if "cache_read" in input_details:
 result["cached_input"] = int(input_details.get("cache_read", 0) or 0)
 if "cache_creation" in input_details:
 result["cache_creation"] = int(input_details.get("cache_creation", 0) or 0)
 if isinstance(output_details, dict):
 reasoning_val = output_details.get("reasoning") or output_details.get("thoughts") or 0
 if reasoning_val:
 result["reasoning"] = int(reasoning_val or 0)
 return result
# ========== config dataclass ==========
@dataclass
class LangChainRunnerConfig:
 """workflow 节点场景 Runner 配置。
 与 `ChatRunnerConfig` / `SdkRunnerConfig` 接口对齐（stream/result/interrupt
 签名一致），Phase `AIAgentBaseNode` 迁移时零改动。
 """
 resolved: ResolvedProviderConfig
 model: str
 session_id: str = ""
 conversation_id: str = ""
 max_turns: int = 15 # 对齐 SdkRunnerConfig.max_turns（chat 场景走 30，此处工作流）
 timeout_seconds: float = 600.0 # 对齐 SdkRunnerConfig.timeout_seconds
 capabilities: ModelCapabilitiesEntry | None = None
 tools: list[BaseTool] = field(default_factory=list)
 max_output_tokens: int | None = None
 max_thinking_tokens: int | None = None
 reasoning_effort: Literal["low", "medium", "high"] | None = None
 # 预算策略（字段占位；实际实现见 Plan）
 context_strategy: Literal["strict_error", "auto_trim"] = "strict_error"
 agent_session: Any = field(default=None) # AgentSession | None，避免循环 import
# ========== Runner 主体 ==========
class LangChainAgentRunner:
 """LangChain 多 Provider 朴素 ReAct runner。
 严禁嵌 LangGraph 子图执行器（ + Pitfall 9）；
 tool_calls 完全信任 LangChain `AIMessage.tool_calls` 标准化产物（，
 仅在 Gemini id 缺失场景补 `uuid.uuid4.hex[:12]`）。
 """
 def __init__(self, config: LangChainRunnerConfig) -> None:
 self._config = config
 self._result: AgentResult | None = None
 self._run_task: asyncio.Task[Any] | None = None
 # Wave（Plan）auto_trim 分支会写入 {trimmed_count, budget, original_tokens}；
 # Wave 保持空 dict，配合 _check_context_window stub 零副作用。
 self._last_trim_meta: dict[str, int] = {}
 @property
 def result(self) -> AgentResult | None:
 return self._result
 async def interrupt(self) -> None:
 """：cancel 当前 task，CancelledError 分支内复用 MESSAGE_COMPLETE(status='interrupted')。"""
 if self._run_task and not self._run_task.done:
 self._run_task.cancel
 logger.info(
 "langchain_runner_interrupted",
 session_id=self._config.session_id,
 )
 # ---------- 私有工具（_build_model / _check_context_window / _normalize_prompt / _execute_tool / _adapt_chunk） ----------
 def _build_model(self) -> BaseChatModel:
 """委托 Plan 产出的 `build_chat_model` thin wrapper。
 测试通过 monkeypatch 替换 `agents.langchain_runner.build_chat_model` seam。
 """
 return build_chat_model(
 resolved=self._config.resolved,
 model=self._config.model,
 capabilities=self._config.capabilities,
 max_output_tokens=self._config.max_output_tokens,
 timeout_seconds=self._config.timeout_seconds,
 max_thinking_tokens=self._config.max_thinking_tokens,
 reasoning_effort=self._config.reasoning_effort,
 streaming=True,
 )
 def _check_context_window(
 self, messages: list[BaseMessage]
 ) -> tuple[list[BaseMessage], bool]:
 """占位：Plan 落实 strict_error / auto_trim 分派。
 Wave 恒返回 `(messages, False)`，不触发 BUDGET_WARNING；
 Wave 实现后会根据 `context_strategy` 选择抛 `ContextWindowExceededError`
 或 `trim_messages` 修剪并写入 `self._last_trim_meta`。
 """
 return messages, False
 def _normalize_prompt(self, prompt: str | list[BaseMessage]) -> list[BaseMessage]:
 """：str → [HumanMessage]；list[BaseMessage] 直接透传。"""
 if isinstance(prompt, str):
 return [HumanMessage(content=prompt)]
 return list(prompt)
 async def _execute_tool(self, tc: dict[str, Any]) -> ToolMessage:
 """从 `config.tools` 按名查找匹配 BaseTool 并执行。
 未知工具抛 `ValueError`，交由外层 异常路径处理（yield
 TOOL_USE_RESULT(success=False) + append ToolMessage(status='error') 继续下一轮）。
 """
 tool_name = str(tc.get("name", ""))
 tool_lookup = {t.name: t for t in self._config.tools}
 if tool_name not in tool_lookup:
 raise ValueError(f"Tool {tool_name!r} not found in config.tools")
 tool = tool_lookup[tool_name]
 result = await tool.arun(tc.get("args", {}))
 return ToolMessage(
 content=str(result),
 tool_call_id=str(tc["id"]),
 name=tool_name,
 )
 def _adapt_chunk(self, chunk: AIMessageChunk) -> list[AgentEvent]:
 """ 内联 EventAdapter：按 `content_blocks.type` 分派 TEXT_DELTA / THINKING。
 _inject_metadata 注入 {model, session_id}（ 跨 Provider 字段一致性）。
 """
 events: list[AgentEvent] =
 for block in _extract_content_blocks(chunk):
 block_type = block.get("type")
 if block_type == "text" and block.get("text"):
 events.append(
 AgentEvent(
 type=TEXT_DELTA,
 data=_inject_metadata(
 {"text": str(block["text"])},
 self._config.model,
 self._config.session_id,
 ),
 )
 )
 elif block_type in {"reasoning", "thinking"}:
 reasoning = (
 block.get("reasoning")
 or block.get("thinking")
 or block.get("text")
 )
 if reasoning:
 events.append(
 AgentEvent(
 type=THINKING,
 data=_inject_metadata(
 {"thinking": str(reasoning)},
 self._config.model,
 self._config.session_id,
 ),
 )
 )
 return events
 # ---------- 主循环 ----------
 async def stream(
 self, prompt: str | list[BaseMessage]
 ) -> AsyncGenerator[AgentEvent, None]:
 """ 核心入口 —— 朴素 ReAct loop（严禁嵌入 LangGraph 子图执行器）。
 流程（PATTERNS §1.4 / RESEARCH Pattern 2 权威模板）：
 1. `_normalize_prompt` → list[BaseMessage]
 2. `_build_model` → BaseChatModel；若 config.tools 非空 → `.bind_tools(tools)`
 3. `for turn in range(max_turns)`：预算检查 stub → `astream` 累加 AIMessageChunk
 4. 无 tool_calls → MESSAGE_COMPLETE + result.status='completed' 并 return
 5. 有 tool_calls → TOOL_USE_START → `_execute_tool` → TOOL_USE_RESULT → 下轮
 6. CancelledError → result.status='interrupted' + MESSAGE_COMPLETE(status='interrupted') → raise
 7. Exception → result.status='error' + ERROR event（不重试，）
 """
 messages = self._normalize_prompt(prompt)
 model = self._build_model
 # Open Question 2 /：Ollama 等不支持 function calling 的模型若传了 tools 提前 fail-fast
 caps = self._config.capabilities
 if (
 self._config.tools
 and caps is not None
 and not caps.supports_function_calling
 ):
 raise ValueError(
 f"Model {self._config.resolved.provider_type}:{self._config.model} "
 f"does not support function calling, but tools were provided"
 )
 model_with_tools: Any = (
 model.bind_tools(self._config.tools) if self._config.tools else model
 )
 self._run_task = asyncio.current_task
 total_usage: TokenUsage = {}
 accumulated_text: list[str] =
 logger.info(
 "langchain_runner_started",
 session_id=self._config.session_id,
 model=self._config.model,
 provider=str(self._config.resolved.provider_type),
 tool_count=len(self._config.tools),
 max_turns=self._config.max_turns,
 )
 try:
 for turn in range(self._config.max_turns):
 messages, trimmed = self._check_context_window(messages)
 if trimmed:
 # Plan auto_trim 策略触发；本 plan stub 永远不进入
 yield AgentEvent(
 type=BUDGET_WARNING,
 data=_inject_metadata(
 {"warning_type": "context_trimmed"},
 self._config.model,
 self._config.session_id,
 ),
 )
 aimsg: AIMessageChunk | None = None
 async for chunk in model_with_tools.astream(messages):
 if not isinstance(chunk, AIMessageChunk):
 continue
 # LangChain 原生 AIMessageChunk.__add__ 语义（不要自写累加，RESEARCH "Don't Hand-Roll"）
 aimsg = chunk if aimsg is None else aimsg + chunk
 for event in self._adapt_chunk(chunk):
 if event.type == TEXT_DELTA:
 accumulated_text.append(event.data.get("text", ""))
 yield event
 if aimsg is None:
 continue
 # 六字段 usage 合并（TypedDict total=False，缺字段保持缺省）
 usage = _extract_usage(aimsg)
 # 借道 dict[str, int] 完成累加，再 cast 回 TokenUsage（避免 TypedDict
 # total=False 下 value 被推为 object 的 5 连 mypy 噪音）
 merged: dict[str, int] = cast(dict[str, int], dict(total_usage))
 for key, value in cast(dict[str, int], usage).items:
 merged[key] = merged.get(key, 0) + value
 total_usage = cast(TokenUsage, merged)
 tool_calls = list(getattr(aimsg, "tool_calls", ) or )
 if not tool_calls:
 final_answer = "".join(accumulated_text) or _extract_message_text(aimsg)
 self._result = AgentResult(
 output=,
 status="completed",
 final_answer=final_answer,
 usage=cast(dict[str, int], dict(total_usage)),
 )
 yield AgentEvent(
 type=MESSAGE_COMPLETE,
 data=_inject_metadata(
 {
 "final_answer": final_answer,
 "status": "completed",
 "usage": cast(dict[str, int], dict(total_usage)),
 },
 self._config.model,
 self._config.session_id,
 ),
 )
 return
 # 把含 tool_calls 的 AIMessage append 到历史，供下轮 LLM 看到自己的决策
 messages.append(aimsg)
 for tc in tool_calls:
 #：Gemini tool_call id 缺失 → runner 内用 uuid 补（非 normalizer）
 if not tc.get("id"):
 tc["id"] = uuid.uuid4.hex[:12]
 tool_call_id = str(tc["id"])
 tool_name = str(tc.get("name", ""))
 tool_args = tc.get("args", {}) or {}
 yield AgentEvent(
 type=TOOL_USE_START,
 data=_inject_metadata(
 {
 "tool_call_id": tool_call_id,
 "tool_name": tool_name,
 "tool_input": tool_args,
 },
 self._config.model,
 self._config.session_id,
 ),
 )
 try:
 tool_msg = await self._execute_tool(tc)
 except Exception as tool_exc:
 #：工具异常不中断整个 stream，交由 LLM 下一轮决策恢复
 logger.warning(
 "langchain_runner_tool_failed",
 session_id=self._config.session_id,
 tool_name=tool_name,
 error=str(tool_exc),
 )
 yield AgentEvent(
 type=TOOL_USE_RESULT,
 data=_inject_metadata(
 {
 "tool_call_id": tool_call_id,
 "tool_name": tool_name,
 "success": False,
 "error": str(tool_exc),
 },
 self._config.model,
 self._config.session_id,
 ),
 )
 messages.append(
 ToolMessage(
 content=f"Error: {tool_exc}",
 tool_call_id=tool_call_id,
 name=tool_name,
 status="error",
 )
 )
 continue
 yield AgentEvent(
 type=TOOL_USE_RESULT,
 data=_inject_metadata(
 {
 "tool_call_id": tool_call_id,
 "tool_name": tool_name,
 "success": True,
 "result": tool_msg.content,
 },
 self._config.model,
 self._config.session_id,
 ),
 )
 messages.append(tool_msg)
 # max_turns 用尽
 final_answer = "".join(accumulated_text)
 self._result = AgentResult(
 output=,
 status="max_iterations",
 final_answer=final_answer,
 usage=cast(dict[str, int], dict(total_usage)),
 )
 logger.info(
 "langchain_runner_max_iterations",
 session_id=self._config.session_id,
 max_turns=self._config.max_turns,
 )
 except asyncio.CancelledError:
 # S-4 + Pitfall F：partial text 保留 + MESSAGE_COMPLETE(status='interrupted') + 必须 raise
 partial_text = "".join(accumulated_text)
 self._result = AgentResult(
 output=,
 status="interrupted",
 final_answer=partial_text,
 usage=cast(dict[str, int], dict(total_usage)),
 )
 yield AgentEvent(
 type=MESSAGE_COMPLETE,
 data=_inject_metadata(
 {
 "final_answer": partial_text,
 "status": "interrupted",
 "usage": cast(dict[str, int], dict(total_usage)),
 },
 self._config.model,
 self._config.session_id,
 ),
 )
 raise # Pitfall F：必须 re-raise 让 asyncio.Task 正常走 cancelled 状态
 except Exception as exc:
 #：LLM provider 异常 → ERROR event + AgentResult.status='error'，不重试
 logger.exception(
 "langchain_runner_error",
 session_id=self._config.session_id,
 )
 self._result = AgentResult(
 output=,
 status="error",
 error=str(exc),
 usage=cast(dict[str, int], dict(total_usage)),
 )
 yield AgentEvent(
 type=ERROR,
 data=_inject_metadata(
 {"message": str(exc)},
 self._config.model,
 self._config.session_id,
 ),
 )
 finally:
 self._run_task = None

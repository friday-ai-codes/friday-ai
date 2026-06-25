"""LangChainAgentRunner —— 工作流 AI 节点通用 Runner（implementation/03/06）。

基于 LangChain `init_chat_model` 多 Provider + 朴素 ReAct loop 实现；
与 `chat_runner.py` 并存（场景差异：workflow 节点无 MCP / 无 deep_analysis / 纯 ReAct）。

**三重禁线（由静态断言测试强制）：**
- 禁止嵌入 LangGraph 子图执行器（REQUIREMENTS work item + RESEARCH Pitfall 9 + Out of Scope）
- 禁止自写 tool_call 归一化层（REQUIREMENTS work item，信任 LangChain bind_tools 归一化）
- 禁止迁移到事件流 v2（RESEARCH Pitfall 8，保持 AIMessageChunk 累加）

（具体禁止符号见 tests/ 下同 phase 两个静态断言测试文件的 AST / 字符串断言）

设计锚点：
- chat_runner.py work item `_inject_metadata` + work item `_extract_content_blocks/text` 一字不改
- chat_runner.py work item ReAct 主循环 6 处修改点（PATTERNS §1.4）
- RESEARCH Example 3 `_extract_usage` 六字段分派（contract）
- context contract AgentEvent.data 字段锁跨 Provider 契约

参考：`project docs` §1.1-1.8 + S-1~S-7。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal, cast

import structlog
from django.utils import timezone
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.tools import BaseTool

from agents.call_source import CallSource, get_call_source
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
from agents.llm_concurrency import acquire_llm_slot
from agents.llm_factory import build_chat_model
from agents.models import AgentSession, ToolCallLog
from agents.types import TokenUsage
from interactions.ledger import arecord_llm_usage, parse_upstream_status
from services.model_capabilities import ModelCapabilities, ModelCapabilitiesEntry
from services.provider_config import ResolvedProviderConfig

logger = structlog.get_logger(__name__)


# contract：上下文安全缓冲硬编码 800 tokens，禁暴露节点配置
# 决策依据：context contract/02（预算公式 max_input - max_output - 800 safety_buffer）
_CONTEXT_SAFETY_BUFFER = 800


class ContextWindowExceededError(Exception):
    """Context window 预算超限（contract，继承 Exception 避免掩盖其他 ValueError）。"""


# ========== helpers（PATTERNS §1.2 / §1.3 —— 与 chat_runner.py 对齐） ==========


def _inject_metadata(data: dict[str, Any], model: str, session_id: str) -> dict[str, Any]:
    """contract：所有 AgentEvent.data 注入 {model, session_id} 确保跨 Provider 字段一致性。"""
    payload = dict(data)
    payload["model"] = model
    payload["session_id"] = session_id
    return payload


def _extract_content_blocks(message: Any) -> list[dict[str, Any]]:
    """LangChain `output_version='v1'` content_blocks 迭代（chat_runner.py work item 一字不改 copy）。"""
    blocks = getattr(message, "content_blocks", None)
    if isinstance(blocks, list):
        return [block for block in blocks if isinstance(block, dict)]

    content = getattr(message, "content", None)
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, str) and content:
        return [{"type": "text", "text": content}]
    return []


def _extract_message_text(message: Any) -> str:
    """chat_runner.py work item 一字不改 copy。"""
    text = getattr(message, "text", "")
    if isinstance(text, str) and text:
        return text

    parts: list[str] = []
    for block in _extract_content_blocks(message):
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "".join(parts)


def _extract_usage(aimsg: AIMessage | AIMessageChunk) -> TokenUsage:
    """contract 六字段 TokenUsage 分派（RESEARCH Example 3 权威模板）。

    字段矩阵（按 LangChain `usage_metadata` 标准）：
    - input           ← input_tokens
    - output          ← output_tokens
    - cached_input    ← input_token_details.cache_read（Anthropic prompt caching 命中）
    - cache_creation  ← input_token_details.cache_creation（Anthropic prompt caching 创建）
    - reasoning       ← output_token_details.reasoning（OpenAI o 系列）/ .thoughts（Gemini）
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
    """workflow 节点场景 Runner 配置（contract / contract）。

    与 `ChatRunnerConfig` / `SdkRunnerConfig` 接口对齐（stream/result/interrupt
    签名一致），implementation `AIAgentBaseNode` 迁移时零改动。
    """

    resolved: ResolvedProviderConfig
    model: str
    session_id: str = ""
    conversation_id: str = ""
    max_turns: int = 15  # 对齐 SdkRunnerConfig.max_turns（chat 场景走 30，此处工作流）
    timeout_seconds: float = 600.0  # 对齐 SdkRunnerConfig.timeout_seconds（contract）
    capabilities: ModelCapabilitiesEntry | None = None
    tools: list[BaseTool] = field(default_factory=list)
    max_output_tokens: int | None = None
    max_thinking_tokens: int | None = None
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    # contract 预算策略（字段占位；实际实现见 implementation plan）
    context_strategy: Literal["strict_error", "auto_trim"] = "strict_error"
    agent_session: Any = field(default=None)  # AgentSession | None，避免循环 import


# ========== Runner 主体 ==========


class LangChainAgentRunner:
    """LangChain 多 Provider 朴素 ReAct runner（contract）。

    严禁嵌 LangGraph 子图执行器（work item + Pitfall 9）；
    tool_calls 完全信任 LangChain `AIMessage.tool_calls` 标准化产物（work item，
    仅在 Gemini id 缺失场景补 `uuid.uuid4().hex[:12]`）。
    """

    def __init__(self, config: LangChainRunnerConfig) -> None:
        self._config = config
        self._result: AgentResult | None = None
        self._run_task: asyncio.Task[Any] | None = None
        # Wave（implementation plan）auto_trim 分支会写入 {trimmed_count, budget, original_tokens}；
        # Wave 保持空 dict，配合 _check_context_window stub 零副作用。
        self._last_trim_meta: dict[str, int] = {}

    @property
    def result(self) -> AgentResult | None:
        return self._result

    async def interrupt(self) -> None:
        """contract：cancel 当前 task，CancelledError 分支内复用 MESSAGE_COMPLETE(status='interrupted')。"""
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            logger.info(
                "langchain_runner_interrupted",
                session_id=self._config.session_id,
            )

    # ---------- 私有工具（_build_model / _check_context_window / _normalize_prompt / _execute_tool / _adapt_chunk） ----------

    def _build_model(self) -> BaseChatModel:
        """委托 implementation plan 产出的 `build_chat_model` thin wrapper。

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
        """contract 预算公式：``budget = max_input - max_output - 800 safety_buffer``。

        流程（context contract / RESEARCH Example 2 权威模板）：

        1. 从 ``config.capabilities``（缺省 ``ModelCapabilities.get``）拿
           ``max_input_tokens`` / ``max_output_tokens``；
        2. ``effective_max_out = config.max_output_tokens or caps.max_output_tokens``；
        3. ``budget = max_input - effective_max_out - 800``；
        4. ``current = count_tokens_approximately(messages)``；若 ≤ budget 直接透传；
        5. 超预算 + ``context_strategy == "strict_error"`` → 抛
           ``ContextWindowExceededError``（错误消息含 tokens / budget / max_input /
           max_output / buffer 5 字段）；
        6. 超预算 + ``context_strategy == "auto_trim"`` → 用
           ``trim_messages(strategy="last", include_system=True, allow_partial=False)``
           修剪至 ≤ budget；
        7. 修剪真的发生（``len(trimmed) < len(messages)``）则写入
           ``self._last_trim_meta = {trimmed_count, budget, original_tokens}``
           并返回 ``(list(trimmed), True)``；否则返回 ``(messages, False)``。

        修剪仅在每 turn 进入 ``astream`` 之前做一次，**不**在流中途 resize；
        BUDGET_WARNING event 由 ``stream()`` 在读到 ``trimmed=True`` 时发射。

        Returns:
            ``(messages, trimmed_flag)``。``trimmed_flag=True`` 才触发 BUDGET_WARNING。
        """
        caps = self._config.capabilities or ModelCapabilities.get(
            str(self._config.resolved.provider_type), self._config.model
        )
        effective_max_out = (
            self._config.max_output_tokens or caps.max_output_tokens
        )
        budget = caps.max_input_tokens - effective_max_out - _CONTEXT_SAFETY_BUFFER
        current = count_tokens_approximately(messages)

        if current <= budget:
            return messages, False

        if self._config.context_strategy == "strict_error":
            raise ContextWindowExceededError(
                f"context too long: {current} tokens > budget {budget} "
                f"(max_input={caps.max_input_tokens}, "
                f"max_output={effective_max_out}, "
                f"buffer={_CONTEXT_SAFETY_BUFFER})"
            )

        # auto_trim 策略（contract）—— RESEARCH Example 2 live venv 实证实现模板
        trimmed = trim_messages(
            messages,
            max_tokens=budget,
            strategy="last",
            token_counter=count_tokens_approximately,
            include_system=True,
            allow_partial=False,
        )
        if len(trimmed) < len(messages):
            self._last_trim_meta = {
                "trimmed_count": len(messages) - len(trimmed),
                "budget": budget,
                "original_tokens": current,
            }
            return list(trimmed), True

        # trim 未见效（罕见：系统消息已贴近 budget 上限）→ 降级为未触发
        # Security security mitigation-01 缓解：下一 turn astream 会由 LangChain 上层触发
        # 上下文溢出异常，走 except Exception 分支转 ERROR event。
        return messages, False

    def _normalize_prompt(self, prompt: str | list[BaseMessage]) -> list[BaseMessage]:
        """contract：str → [HumanMessage]；list[BaseMessage] 直接透传。"""
        if isinstance(prompt, str):
            return [HumanMessage(content=prompt)]
        return list(prompt)

    async def _execute_tool(self, tc: dict[str, Any]) -> ToolMessage:
        """从 `config.tools` 按名查找匹配 BaseTool 并执行。

        未知工具抛 `ValueError`，交由外层 contract 异常路径处理（yield
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

    async def _persist_usage(self, usage: Any) -> None:
        """contract：把单 turn usage 写到 AgentSession.metadata。

        模板来源：chat_runner.py work item（一字不改迁移，仅改日志事件名以便区分 Runner）。
        usage 是 `TokenUsage` TypedDict（六字段 total=False），add_usage 仅消费 input/output 两字段。
        agent_session=None 时静默跳过；DB 异常走 logger.exception 兜底不 crash 主循环。
        """
        sess = self._config.agent_session
        if sess is None:
            return
        try:
            sess.add_usage(
                int(usage.get("input", 0) or 0),
                int(usage.get("output", 0) or 0),
            )
            await AgentSession.objects.filter(
                session_id=sess.session_id,
            ).aupdate(metadata=sess.metadata)
        except Exception:
            logger.exception(
                "langchain_runner_usage_update_failed",
                session_id=self._config.session_id,
            )

    async def _log_tool_call(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, Any],
        tool_msg: Any,
    ) -> None:
        """contract：每次工具执行成功后写 ToolCallLog + increment_tool_calls。

        模板来源：chat_runner.py work item（一字不改迁移，仅适配 ToolMessage 代替 ToolResult）。
        tool_msg.status: Literal["success", "error"]（LangChain ToolMessage 默认 "success"；
        implementation langchain_runner.py L521 error 分支构造 status="error"，本方法仅由成功分支调用）。
        agent_session=None 时静默跳过；DB 异常走 logger.exception 兜底不 crash 主循环。
        """
        sess = self._config.agent_session
        if sess is None:
            return
        try:
            iteration = sess.increment_tool_calls()
            now = timezone.now()
            await AgentSession.objects.filter(
                session_id=sess.session_id,
            ).aupdate(metadata=sess.metadata)
            is_error = getattr(tool_msg, "status", "success") == "error"
            await ToolCallLog.objects.acreate(
                session=sess,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=arguments,
                result_success=not is_error,
                result_output=str(getattr(tool_msg, "content", "") or ""),
                result_error="",
                started_at=now,
                completed_at=now,
                duration_ms=0,
                iteration=iteration,
            )
        except Exception:
            logger.exception(
                "langchain_runner_tool_log_failed",
                tool_name=tool_name,
                tool_use_id=tool_call_id,
                session_id=self._config.session_id,
            )

    def _adapt_chunk(self, chunk: AIMessageChunk) -> list[AgentEvent]:
        """contract 内联 EventAdapter：按 `content_blocks.type` 分派 TEXT_DELTA / THINKING。

        _inject_metadata 注入 {model, session_id}（contract 跨 Provider 字段一致性）。
        """
        events: list[AgentEvent] = []
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
        """work item/03/06 核心入口 —— 朴素 ReAct loop（严禁嵌入 LangGraph 子图执行器）。

        流程（PATTERNS §1.4 / RESEARCH Pattern 2 权威模板）：
        1. `_normalize_prompt` → list[BaseMessage]
        2. `_build_model` → BaseChatModel；若 config.tools 非空 → `.bind_tools(tools)`
        3. `for turn in range(max_turns)`：预算检查 stub → `astream` 累加 AIMessageChunk
        4. 无 tool_calls → MESSAGE_COMPLETE + result.status='completed' 并 return
        5. 有 tool_calls → TOOL_USE_START → `_execute_tool` → TOOL_USE_RESULT → 下轮
        6. CancelledError → result.status='interrupted' + MESSAGE_COMPLETE(status='interrupted') → raise
        7. Exception → result.status='error' + ERROR event（不重试，contract）
        """
        messages = self._normalize_prompt(prompt)
        model = self._build_model()

        # Open Question 2 / contract：Ollama 等不支持 function calling 的模型若传了 tools 提前 fail-fast
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

        self._run_task = asyncio.current_task()
        total_usage: TokenUsage = {}
        accumulated_text: list[str] = []

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
                    # implementation plan auto_trim 策略触发 —— contract BUDGET_WARNING
                    # data 字段锁定：warning_type / trimmed_count / budget /
                    # original_tokens / model / session_id（前端 SSE 合约冻结）
                    warn_meta = self._last_trim_meta
                    yield AgentEvent(
                        type=BUDGET_WARNING,
                        data=_inject_metadata(
                            {
                                "warning_type": "context_trimmed",
                                "trimmed_count": warn_meta.get("trimmed_count", 0),
                                "budget": warn_meta.get("budget", 0),
                                "original_tokens": warn_meta.get("original_tokens", 0),
                            },
                            self._config.model,
                            self._config.session_id,
                        ),
                    )

                aimsg: AIMessageChunk | None = None
                # 72-02：本 turn 流式计时锚点（首 chunk = TTFT / 整 turn = duration）。
                _turn_start = perf_counter()
                _ttft_ms: int | None = None
                # CONC-02：按凭证申请 LLM 并发槽位（仅本 turn 的流式调用持有，
                # turn 间工具执行期释放）；超凭证上限排队等待、超时抛 LLMBusyError
                # （被下方 except 转 ERROR 事件友好提示），绝不打到 provider 触发 429。
                async with acquire_llm_slot(
                    self._config.resolved.credential_id,
                    self._config.resolved.max_concurrency,
                ):
                    async for chunk in model_with_tools.astream(messages):
                        if not isinstance(chunk, AIMessageChunk):
                            continue

                        # 72-02：首个有效 chunk 时刻 = TTFT 锚点（per SLA-04）。
                        if _ttft_ms is None:
                            _ttft_ms = int((perf_counter() - _turn_start) * 1000)

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
                for key, value in cast(dict[str, int], usage).items():
                    merged[key] = merged.get(key, 0) + value
                total_usage = cast(TokenUsage, merged)

                # implementation contract：每 turn 结束持久化 usage 到 AgentSession.metadata
                await self._persist_usage(usage)

                # 72-02：每个 LLM turn 收尾落一行 ModelUsageRecord（call_source / TTFT /
                # input·output·cache token），call_source 经 caller 的 use_call_source
                # 设定、runner 读取兜底 workflow_agent_node；best-effort 不反噬 ReAct 主链。
                try:
                    await arecord_llm_usage(
                        call_source=get_call_source() or CallSource.WORKFLOW_AGENT_NODE.value,
                        provider=str(self._config.resolved.provider_type),
                        model=self._config.model,
                        prompt_tokens=int(usage.get("input", 0) or 0),
                        completion_tokens=int(usage.get("output", 0) or 0),
                        cache_read_tokens=int(usage.get("cached_input", 0) or 0),
                        cache_write_tokens=int(usage.get("cache_creation", 0) or 0),
                        ttft_ms=_ttft_ms,
                        duration_ms=int((perf_counter() - _turn_start) * 1000),
                        source="workflow",
                    )
                except Exception:  # noqa: BLE001 — 观测绝不反噬 LLM
                    pass

                tool_calls = list(getattr(aimsg, "tool_calls", []) or [])
                if not tool_calls:
                    final_answer = "".join(accumulated_text) or _extract_message_text(aimsg)
                    self._result = AgentResult(
                        output=[],
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
                    # contract：Gemini tool_call id 缺失 → runner 内用 uuid 补（非 normalizer）
                    if not tc.get("id"):
                        tc["id"] = uuid.uuid4().hex[:12]
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
                        # contract：工具异常不中断整个 stream，交由 LLM 下一轮决策恢复
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
                    # implementation contract：工具执行成功后记录 ToolCallLog
                    await self._log_tool_call(
                        tool_name=tool_name,
                        tool_call_id=tool_call_id,
                        arguments=tool_args,
                        tool_msg=tool_msg,
                    )
                    messages.append(tool_msg)

            # max_turns 用尽
            final_answer = "".join(accumulated_text)
            self._result = AgentResult(
                output=[],
                status="max_iterations",
                final_answer=final_answer,
                usage=cast(dict[str, int], dict(total_usage)),
            )
            logger.info(
                "langchain_runner_max_iterations",
                session_id=self._config.session_id,
                max_turns=self._config.max_turns,
            )

        except ContextWindowExceededError:
            # contract / strict_error 策略必须向外抛出 ContextWindowExceededError，
            # **不**降级为 ERROR event —— 调用方（implementation AIAgentBaseNode）需要
            # 区分"预算超限需降级引导"与"LLM provider 异常"两类错误分支。
            # 该异常必须先于下方 `except Exception` 捕获，否则会被吞为 ERROR event。
            raise

        except asyncio.CancelledError:
            # S-4 + Pitfall F：partial text 保留 + MESSAGE_COMPLETE(status='interrupted') + 必须 raise
            partial_text = "".join(accumulated_text)
            self._result = AgentResult(
                output=[],
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
            raise  # Pitfall F：必须 re-raise 让 asyncio.Task 正常走 cancelled 状态

        except Exception as exc:
            # contract：LLM provider 异常 → ERROR event + AgentResult.status='error'，不重试
            logger.exception(
                "langchain_runner_error",
                session_id=self._config.session_id,
            )
            # 72-02：上游错误（429/529 单列）落一行 failure ModelUsageRecord —— 只取
            # 数值 status_code，绝不落异常文本（T-72-02-01）；best-effort 不反噬。
            try:
                _upstream_code = parse_upstream_status(exc)
                await arecord_llm_usage(
                    call_source=get_call_source() or CallSource.WORKFLOW_AGENT_NODE.value,
                    provider=str(self._config.resolved.provider_type),
                    model=self._config.model,
                    upstream_status_code=_upstream_code,
                    failure_type=str(_upstream_code) if _upstream_code is not None else "error",
                    source="workflow",
                )
            except Exception:  # noqa: BLE001 — 观测绝不反噬 LLM
                pass
            self._result = AgentResult(
                output=[],
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

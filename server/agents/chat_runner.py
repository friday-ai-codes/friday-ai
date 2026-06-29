"""ChatAnthropicRunner：LangGraph Chat 场景的 LangChain 执行器。

使用 ChatAnthropic + 现有本地工具定义实现：
- 普通流式文本输出
- tool call 执行与事件回放
- deep_analysis blocking marker 透传
- interrupt() 中断
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, cast

import structlog
from django.utils import timezone
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.runnables import Runnable
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

# 触发 @tool 注册
import agents.tools.chat_tools  # noqa: F401
import agents.tools.clarification  # noqa: F401  # implementation
import agents.tools.coding_tools  # noqa: F401
import agents.tools.delivery_knowledge_tools  # noqa: F401  # RECALL-02 交付知识召回工具
import agents.tools.plan_research_tools  # noqa: F401
import agents.tools.project_feature_tools  # noqa: F401  # ENTRY-02 chat 入口薄封装
import agents.tools.repository_relevance  # noqa: F401
import agents.tools.space_tools  # noqa: F401
from agents.call_source import CallSource, get_call_source
from agents.core.events import (
    ERROR,
    MESSAGE_COMPLETE,
    PART_COMPLETED,
    PART_DELTA,
    PART_STARTED,
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
from agents.llm_concurrency import acquire_llm_slot
from agents.models import AgentSession, ToolCallLog
from agents.tool_budget import _ToolBudget
from agents.tools.base import ToolDefinition, ToolResult, _tool_registry
from agents.tools.langchain_adapter import build_langchain_tools
from chat.multimodal import to_provider_content_blocks
from chat.parts import PartsCollector
from interactions.ledger import arecord_llm_usage, parse_upstream_status
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
    # 代码关系 / GraphRAG 游走：拿到具体起点（文件 / chunk / 符号）后沿
    # CALL / IMPORT / TEST_OF 等 chunk 级关系图遍历，补足 search_repository_code
    # 的 RAG 模糊检索拿不到的"调用方/被调用方/测试"等结构化关联。
    # 这些工具早已在 agents/tools/__init__.py 注册，此前漏挂进 chat 白名单导致
    # LLM 全程只能 RAG 搜索、无法利用 graph 能力。
    "find_related_code",
    "list_endpoints",
    "find_api_handler",
    "find_api_callers",
    # 先分析相关性，后创建方案
    "analyze_repository_relevance",
    # 不确定时主动澄清（暴露给所有有索引仓库的项目）
    "ask_clarification",
    "create_coding_plan",
    "update_coding_plan",
    # ENTRY-02：对话中发起多仓 / 跨仓方案编排（薄入口，复用同一编排 engine）
    "start_plan_research",
    # #5 Part A：把整理出的 feature list 绑定到当前对话所绑定的项目
    "save_project_feature_list",
    # #5 Part A：feature list 拆子看板/工作项并关联到当前对话所绑定的项目
    "split_feature_list_to_boards",
    # RECALL-02（v0.15.0 Phase 80）：交付知识召回接入 chat 工具白名单。
    # 这些工具以 conversation_id 解析会话 owner 做权限 fail-closed（非成员零召回），
    # 与项目上下文打包器（context packer）互补——packer 自动注入，工具供 LLM 主动追溯。
    "search_delivery_knowledge",
    "get_entity_timeline",
    "get_related_entities",
]
_DEEP_ANALYSIS_TOOL_NAMES = _INDEXED_TOOL_NAMES + ["deep_analysis"]


@dataclass
class ChatRunnerConfig:
    """Chat 场景运行配置。"""

    system_prompt: str
    model: str
    space_id: str
    session_id: str
    provider_type: ProviderType = ProviderType.ANTHROPIC
    conversation_id: str = ""
    api_key: str = ""
    api_base_url: str = ""
    # 并发治理（CONC-02）：凭证 id + 该凭证 LLM 并发上限（0=不限），
    # 供 astream 前按凭证申请并发槽位限流。
    credential_id: Any = None
    max_concurrency: int = 0
    max_turns: int = 30
    timeout_seconds: float = 0
    agent_session: Any = field(default=None)
    max_budget_usd: float | None = None
    default_search_branch: str | None = None
    # 凭证绑定的模型清单（含 input_modalities / supports_vision 等能力配置）。
    # 用于图片块构建时的能力门控，与发送入口的 available_models-aware 校验保持一致。
    available_models: Any = field(default=None)
    # 凭证级上下文窗口（用户在凭证模型条目上配置的 context_length 解析结果）；
    # 0 = 未覆盖，_check_chat_context_window 回退 fixture。
    max_input_tokens: int = 0
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


async def _astream_with_llm_slot(model: Any, messages: Any, config: ChatRunnerConfig):
    """在持有凭证级 LLM 并发槽位的前提下消费 model.astream（CONC-02）。

    薄包装生成器：首次迭代触发 :func:`acquire_llm_slot` 申请槽位（超凭证上限排队
    等待、超时抛 LLMBusyError），整段流式期间持有槽位，生成器结束/关闭即释放。
    用包装而非在调用处 `async with` 包裹，避免对庞大的 astream 消费循环重新缩进。
    """
    async with acquire_llm_slot(config.credential_id, config.max_concurrency):
        async for chunk in model.astream(messages):
            yield chunk


def _build_human_message_content(
    prompt: str,
    input_parts: list[dict[str, Any]] | None,
    config: ChatRunnerConfig,
) -> str | list[str | dict[Any, Any]]:
    """构造 HumanMessage.content；含图片时转 provider content blocks。"""
    if not input_parts:
        return prompt
    blocks = to_provider_content_blocks(
        input_parts,
        provider_type=config.provider_type,
        model=config.model,
        available_models=config.available_models,
    )
    return cast(list[str | dict[Any, Any]], blocks)


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
    required = set(tool_def.parameters.get("required", [])) - hidden_fields
    fields: dict[str, tuple[Any, Any]] = {}

    for name, prop in properties.items():
        if name in hidden_fields:
            continue
        annotation = _schema_type_to_python(prop)
        description = prop.get("description", "")
        if name in required:
            default = Field(..., description=description)
        else:
            default = Field(prop.get("default", None), description=description)
        fields[name] = (annotation, default)

    model_name = "".join(part.capitalize() for part in tool_def.name.split("_")) + "Args"
    return create_model(model_name, **cast(dict[str, Any], fields))


async def _get_tool_names(
    space_id: str,
    *,
    force_deep_analysis: bool = False,
) -> list[str]:
    """返回 LLM 可用工具名列表。

    - 无空间（space_id 为空，未绑定空间的通用对话）：不注入任何空间工具。
    - 无已索引仓库：仅 `_BASE_TOOL_NAMES`（避免误调检索工具拿空结果）。
    - 有已索引仓库 + 普通模式：`_INDEXED_TOOL_NAMES`，**不含** `deep_analysis`。
    - 有已索引仓库 + 用户开启「深度分析」开关：`_DEEP_ANALYSIS_TOOL_NAMES`。
    """
    if not space_id:
        return []
    has_indexed = await Repository.objects.filter(
        spaces__id=space_id,
        index_status="indexed",
        is_deleted=False,
    ).aexists()
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
    return []


def _extract_message_text(message: Any) -> str:
    text = getattr(message, "text", "")
    if isinstance(text, str) and text:
        return text

    parts: list[str] = []
    for block in _extract_content_blocks(message):
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "".join(parts)


def _extract_usage(message: Any) -> dict[str, int]:
    usage = getattr(message, "usage_metadata", None) or getattr(
        message, "response_metadata", {}
    ).get("usage")
    if not isinstance(usage, dict):
        return {}
    return {
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
    }


def _thinking_budget_tokens(model: str) -> int | None:
    lowered = model.lower()
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
        iteration = agent_session.increment_tool_calls()
        now = timezone.now()
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


def _make_part_event(
    *,
    type_: str,
    index: int,
    model: str,
    session_id: str,
    part: dict[str, Any] | None = None,
    delta_type: str | None = None,
    text: str | None = None,
) -> AgentEvent:
    """parts contract：构造 part_started / part_delta / part_completed 事件。

    payload schema 字面冻结（streaming parts contract / §contract 表格）；前端 contract dispatch
    分支直接按 index + delta_type 维护 streamingParts。
    """
    data: dict[str, Any] = {"index": index}
    if part is not None:
        data["part"] = part
    if delta_type is not None:
        data["delta_type"] = delta_type
    if text is not None:
        data["text"] = text
    return AgentEvent(type=type_, data=_inject_metadata(data, model, session_id))


def _build_message_complete(
    *,
    final_answer: str,
    usage: dict[str, int],
    model: str,
    session_id: str,
    parts: list[dict[str, Any]],
    status: str = "completed",
) -> AgentEvent:
    """构造 MESSAGE_COMPLETE 事件。

    parts contract：``parts`` 是必填 kwarg —— 即便 ERROR / interrupted
    路径也必须携带（可为空 list 或部分已收集 parts），保证前端能渲染已生成的
    text/tool_use 给用户看，不丢失上下文（streaming parts contract 双轨期协议）。
    """
    payload: dict[str, Any] = {
        "final_answer": final_answer,
        "result": final_answer,
        "status": status,
        "usage": usage,
        "cost_usd": 0,
        "parts": parts,
    }
    return AgentEvent(
        type=MESSAGE_COMPLETE,
        data=_inject_metadata(payload, model, session_id),
    )


def _check_chat_context_window(
    messages: list[Any],
    *,
    model: str,
    max_output_tokens: int = 4096,
    max_input_tokens_override: int = 0,
) -> None:
    """前 astream budget check（strict_error 策略）；超限抛 ContextWindowExceededError。

    消息格式与 ``langchain_runner.py`` work item 共用，保证 ``base_agent.py``
    work item 的 regex 可复用（implementation Pitfall 1 单一事实源 / Pitfall 3 每 turn
    check）。

    Args:
        messages: LangChain message 列表（含 accumulated ToolMessage）。
        model: Anthropic model id（caller 传 ``self._config.model``）。
        max_output_tokens: 可选覆盖；0 / None 走 ``caps.max_output_tokens``。
        max_input_tokens_override: 凭证级上下文窗口覆盖（用户配置的
            context_length 解析结果）；0 走 fixture ``caps.max_input_tokens``。
    """
    caps = ModelCapabilities.get(str(ProviderType.ANTHROPIC), model)
    effective_max_out = max_output_tokens or caps.max_output_tokens
    effective_max_in = max_input_tokens_override or caps.max_input_tokens
    budget = effective_max_in - effective_max_out - _CONTEXT_SAFETY_BUFFER
    current = count_tokens_approximately(messages)
    if current > budget:
        raise ContextWindowExceededError(
            f"context too long: {current} tokens > budget {budget} "
            f"(max_input={effective_max_in}, "
            f"max_output={effective_max_out}, "
            f"buffer={_CONTEXT_SAFETY_BUFFER})"
        )


def _tool_result_to_content(result: Any) -> str:
    """把 messages 表里存的 tool_call.result（dict/str/None）还原成 ToolMessage.content。

    Anthropic API 要求 ToolMessage.content 是字符串；dict / list 直接 json.dumps
    （ensure_ascii=False 保留中文可读性）。None → 空串。
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


async def _load_history_messages(conversation_id: str) -> list[BaseMessage]:
    """从 ``messages`` 表加载历史并还原成 LangChain 消息序列。

    **为什么需要**：原先 ``ChatAnthropicRunner.stream`` 每次只塞 ``SystemMessage`` +
    当前 ``HumanMessage``，LLM 完全看不到前几轮对话 —— 同一会话里反复调用同一个工具
    （典型现象：conv ``6f5d47bd...`` 三轮都调 ``list_space_repositories``）。

    **末尾 user 消息丢弃**：``send_message_stream`` 在启动 graph **前**已把本轮 user
    content 落库（``conversation_service.py`` work item），而 ``stream(prompt)`` 又会
    把同样的内容作为新的 ``HumanMessage`` 追加 —— 不剔除会导致末尾出现两条相同 user
    消息，触发 Anthropic API 的 "messages must alternate" 校验。

    **异常一律退化**：DB 不可访问（pytest-django 默认隔离）、Message schema 损坏等
    任何异常都吞掉返回 ``[]``，让 LLM 退化到"无历史"模式而不是让整轮对话 hard fail。
    生产环境 DB 真坏时，落库环节自然会暴露错误，这里 degrade 反而让用户能看到答案。
    """
    if not conversation_id:
        return []

    try:
        # lazy import 避免 agents → chat 反向依赖链
        from chat.models import Message

        rows = [
            m
            async for m in Message.objects.filter(
                conversation_id=conversation_id,
            ).order_by("created_at")
        ]
    except Exception:
        logger.warning(
            "chat_runner_history_load_failed",
            conversation_id=conversation_id,
            exc_info=True,
        )
        return []

    from chat.models import Message  # 同一进程内已 import，零成本

    # 丢弃末尾连续 user 消息（当前轮 prompt 由 caller 单独追加）
    while rows and rows[-1].role == Message.Role.USER:
        rows.pop()

    history: list[BaseMessage] = []
    for row in rows:
        if row.role == Message.Role.SYSTEM:
            # 会话内切换空间：space_switch 标记注入为 HumanMessage 标注，
            # 让模型明确知道切换边界 —— 此前回答基于旧空间仅作参考，后续基于新空间。
            # 其余 system 消息维持忽略（chat 场景不会单独落库）。
            meta = row.metadata or {}
            if meta.get("type") == "space_switch":
                to_name = meta.get("to_space_name") or ""
                from_name = meta.get("from_space_name") or ""
                from_desc = f"「{from_name}」" if from_name else "无空间（通用对话）"
                to_desc = f"「{to_name}」" if to_name else "无空间（通用对话）"
                history.append(
                    HumanMessage(
                        content=(
                            f"[系统提示] 用户已将本对话的空间从 {from_desc} 切换到 {to_desc}。"
                            "此前的回答基于旧空间上下文，仅作参考；"
                            "从现在起请基于新空间回答。"
                        )
                    )
                )
            continue
        if row.role == Message.Role.USER:
            history.append(HumanMessage(content=row.content or ""))
        elif row.role == Message.Role.ASSISTANT:
            tc_data = row.tool_calls or []
            lc_tool_calls: list[dict[str, Any]] = []
            for tc in tc_data:
                tc_id = str(tc.get("id", "") or "")
                if not tc_id:
                    continue
                lc_tool_calls.append(
                    {
                        "name": str(tc.get("name", "") or ""),
                        "args": tc.get("input") or {},
                        "id": tc_id,
                        "type": "tool_call",
                    }
                )

            history.append(
                AIMessage(
                    content=row.content or "",
                    tool_calls=lc_tool_calls,
                )
            )

            # ToolMessage 必须紧跟带 tool_calls 的 AIMessage 且 tool_call_id 一一对应，
            # 否则 Anthropic API 直接 400。tc_id 为空的项已在上面 skip，这里同步过滤
            # 保证两侧条目数严格对齐。
            for tc in tc_data:
                tc_id = str(tc.get("id", "") or "")
                if not tc_id:
                    continue
                history.append(
                    ToolMessage(
                        content=_tool_result_to_content(tc.get("result")),
                        tool_call_id=tc_id,
                        name=str(tc.get("name", "") or ""),
                    )
                )
        # role=system / tool 在 chat 场景不会单独落库，忽略

    return history


def _make_agent_result(
    *,
    status: str,
    usage: dict[str, int],
    final_answer: str | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentResult:
    return AgentResult(
        [],
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

    内部通过 `build_langchain_tools` (implementation contract) 统一产出 StructuredTool：
    space_id / conversation_id 由 adapter 从 args_schema 剔除 + 闭包注入。

    `default_search_branch` "LLM 未提供 branch 时回填"语义属于 chat 场景特有
    （非强制覆盖；Pitfall #12 / Q2 选项 B），保留在本二次闭包中，不下沉到
    adapter。二次闭包 `execute(arguments: dict) -> ToolResult` 的签名保持
    不变，下游 `_execute_tool_call` 契约零破坏。
    """
    tool_names = await _get_tool_names(
        space_id,
        force_deep_analysis=force_deep_analysis,
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
            # Phase P15：按 schema properties 过滤 LLM 自创的未知字段。
            # 背景：LLM 偶尔会在 tool_call.args 里塞 schema 不存在的字段（比如
            # 对只接受 space_id 的 list_space_structure 传了 repository_id）。
            # LangChain 的 bind_tools 不强校验 schema，这些未知字段会被原样
            # 透传，unpack 到工具函数时直接抛 TypeError 让整轮失败。
            # 静默 drop 这些字段比硬抛 TypeError 友好：保留 LLM 真实想做的事
            # （调这个工具），下一轮 LLM 看到 ToolMessage 会自己修正参数。
            allowed = set(_props.keys())
            unknown = set(arguments.keys()) - allowed
            if unknown:
                logger.warning(
                    "chat_runner_dropped_unknown_tool_args",
                    tool_name=_tool_def.name,
                    dropped_args=sorted(unknown),
                    allowed_args=sorted(allowed),
                )
                arguments = {k: v for k, v in arguments.items() if k in allowed}

            merged = {**_injected, **arguments}
            # Pitfall #12：LLM 未提供 branch 时用 default，非无条件覆盖
            if "branch" in _props and _dsb:
                cur = merged.get("branch")
                if cur in (None, ""):
                    merged["branch"] = _dsb
            return await _tool_def.func(**merged)

        tool_specs[lc_tool.name] = _ChatToolSpec(
            tool=lc_tool,  # type: ignore[arg-type]
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
        # interrupt 在 stream() 设置 _run_task 之前到达的窗口期：
        # register_runner(runner) 在 _execute_first_run 进入时就完成，但 stream()
        # 体内的 self._run_task = current_task() 要等用户的第一个 yield 才执行。
        # 这中间几十毫秒到几百毫秒，如果用户在这窗口里点了"停止"，老逻辑只检查
        # _run_task is None 就 silently no-op → graph 继续跑完 → finalize 覆盖
        # interrupted 状态。这里把请求 latch 住，stream() 启动时自检自取消。
        self._interrupt_requested: bool = False

    @property
    def result(self) -> AgentResult | None:
        return self._result

    async def interrupt(self) -> None:
        self._interrupt_requested = True
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
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
                remaining=budget.remaining(),
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
            content=budget.annotate(result.to_content()),
            tool_call_id=tool_call_id,
            name=tool_name,
            status="success" if result.success else "error",
            artifact=result.output,
        )
        return result, tool_message, decision.intercepted

    async def stream(
        self,
        prompt: str,
        *,
        input_parts: list[dict[str, Any]] | None = None,
    ):  # type: ignore[override]
        if not self._config.api_key:
            raise ValueError("ChatRunnerConfig.api_key 不能为空")

        model = self._build_model()
        tool_specs = await _build_tool_specs(
            self._config.space_id,
            self._config.conversation_id,
            default_search_branch=self._config.default_search_branch,
            force_deep_analysis=self._config.force_deep_analysis,
        )
        model_with_tools = model.bind_tools([spec.tool for spec in tool_specs.values()])

        # 把 messages 表里的历史回灌给 LLM —— 否则同会话里 LLM 每轮都从零开始，
        # 会反复调同一个工具拿同一份数据。详见 _load_history_messages docstring。
        history_messages = await _load_history_messages(self._config.conversation_id)
        human_content = _build_human_message_content(prompt, input_parts, self._config)
        messages: list[Any] = [
            SystemMessage(content=self._config.system_prompt),
            *history_messages,
            HumanMessage(content=human_content),
        ]
        total_usage = {"input_tokens": 0, "output_tokens": 0}
        accumulated_text: list[str] = []
        # parts contract：parts 状态机持有者（collector state contract）。
        # 所有 text / thinking / tool_use 真相走 collector；``accumulated_text``
        # 仅作 ``final_answer`` 兼容副本保留（向后兼容旧消费方）。
        collector = PartsCollector()
        self._run_task = asyncio.current_task()
        # Phase P15：单 stream 工具预算控制（去重 + 单文件硬上限 + 剩余
        # 预算注入 + 强制 final-turn）。详见 agents/tool_budget.py。
        budget = _ToolBudget(max_turns=self._config.max_turns)

        # REGION: interrupt-latch-fix-coding-plan workflow-2026-05-21
        # ↑ implementation DEBUG 修复保护区，不可触碰：
        #   1) _interrupt_requested latch（构造器 + interrupt()）
        #   2) _run_task 生命周期管理（assign / cancel / finally 清零）
        #   3) collector.flush_all() 在三个 except 分支的强制调用契约（major #1）
        # 详见 project docs
        try:
            # 窗口期补救：interrupt() 可能早于 stream() 第一次被驱动就到达
            # （register_runner 比 _run_task 赋值早；用户在用户消息刚发出去就立刻
            # 点"停止"会撞这个窗口）。这里在主循环前显式自检，让 except 分支接管，
            # 产出与运行中 cancel 完全一致的 message_complete(status=interrupted)
            # 事件序列，下游 graph / finalize 路径无需区分两种 cancel 时机。
            if self._interrupt_requested:
                raise asyncio.CancelledError("interrupt requested before stream start")
            for _ in range(self._config.max_turns):
                full_message: AIMessageChunk | None = None
                # 72-02：本 turn 流式计时锚点（首 chunk = TTFT / 整 turn = duration）。
                _turn_start = perf_counter()
                _ttft_ms: int | None = None

                # 每 turn 进入 astream 前做前置 budget check。
                # messages 会随 ToolMessage 累积增长，必须每轮 check，不能只 turn 0 check
                # （Pitfall 3）。超限抛 ContextWindowExceededError，由下方专属 except 分支捕获。
                _check_chat_context_window(
                    messages,
                    model=self._config.model,
                    max_input_tokens_override=self._config.max_input_tokens,
                )

                # Phase P15：剩余 ≤ BUDGET_FORCE_FINAL_AT 时切到原始 model
                # （未 bind_tools），强制 LLM 基于已收集信息出最终回答，避免硬抛
                # MaxTurnsExceeded 丢弃中间产出（OpenAI Agents SDK 反模式）。
                # active_model 是 ChatAnthropic | Runnable 联合，astream 接口
                # 一致 —— 显式注解防 mypy 推断成更窄的 ChatAnthropic。
                active_model: ChatAnthropic | Runnable[Any, Any]
                if budget.should_force_final():
                    active_model = model
                    logger.info(
                        "chat_runner_force_final_turn",
                        session_id=self._config.session_id,
                        remaining=budget.remaining(),
                        max_turns=self._config.max_turns,
                    )
                else:
                    active_model = model_with_tools

                async for chunk in _astream_with_llm_slot(active_model, messages, self._config):
                    if not isinstance(chunk, AIMessageChunk):
                        continue

                    # 72-02：首个有效 chunk 时刻 = TTFT 锚点（per SLA-04）。
                    if _ttft_ms is None:
                        _ttft_ms = int((perf_counter() - _turn_start) * 1000)

                    full_message = chunk if full_message is None else full_message + chunk
                    for block in _extract_content_blocks(chunk):
                        block_type = block.get("type")
                        if block_type == "text" and block.get("text"):
                            text = str(block["text"])
                            accumulated_text.append(text)
                            part_id, part_idx, is_new = collector.append_text(text)
                            # 旧事件先发（双轨期前端可选 flag 消费）
                            yield AgentEvent(
                                type=TEXT_DELTA,
                                data=_inject_metadata(
                                    {"text": text}, self._config.model, self._config.session_id
                                ),
                            )
                            # 新事件后发：is_new 时先 part_started 再 part_delta；
                            # 否则直接 part_delta（同一 streaming text part append）
                            if is_new:
                                yield _make_part_event(
                                    type_=PART_STARTED,
                                    index=part_idx,
                                    model=self._config.model,
                                    session_id=self._config.session_id,
                                    part={
                                        "id": part_id,
                                        "type": "text",
                                        "index": part_idx,
                                        "text": "",
                                        "state": "streaming",
                                    },
                                )
                            yield _make_part_event(
                                type_=PART_DELTA,
                                index=part_idx,
                                model=self._config.model,
                                session_id=self._config.session_id,
                                delta_type="text_append",
                                text=text,
                            )
                        elif block_type in {"reasoning", "thinking"}:
                            reasoning = (
                                block.get("reasoning") or block.get("thinking") or block.get("text")
                            )
                            if reasoning:
                                part_id, part_idx, is_new = collector.append_thinking(
                                    str(reasoning)
                                )
                                yield AgentEvent(
                                    type=THINKING,
                                    data=_inject_metadata(
                                        {"thinking": str(reasoning)},
                                        self._config.model,
                                        self._config.session_id,
                                    ),
                                )
                                if is_new:
                                    yield _make_part_event(
                                        type_=PART_STARTED,
                                        index=part_idx,
                                        model=self._config.model,
                                        session_id=self._config.session_id,
                                        part={
                                            "id": part_id,
                                            "type": "thinking",
                                            "index": part_idx,
                                            "text": "",
                                            "state": "streaming",
                                        },
                                    )
                                yield _make_part_event(
                                    type_=PART_DELTA,
                                    index=part_idx,
                                    model=self._config.model,
                                    session_id=self._config.session_id,
                                    delta_type="text_append",
                                    text=str(reasoning),
                                )

                if full_message is None:
                    continue

                usage = _extract_usage(full_message)
                total_usage["input_tokens"] += usage.get("input_tokens", 0)
                total_usage["output_tokens"] += usage.get("output_tokens", 0)
                await _persist_usage(self._config.agent_session, usage)

                # 72-02：每个 LLM turn 收尾落一行 ModelUsageRecord（call_source / TTFT /
                # input·output token），best-effort 绝不反噬流式主链（T-72-02-05）。
                try:
                    await arecord_llm_usage(
                        call_source=get_call_source() or CallSource.CHAT.value,
                        provider=str(self._config.provider_type),
                        model=self._config.model,
                        prompt_tokens=usage.get("input_tokens", 0),
                        completion_tokens=usage.get("output_tokens", 0),
                        ttft_ms=_ttft_ms,
                        duration_ms=int((perf_counter() - _turn_start) * 1000),
                        source="chat",
                    )
                except Exception:  # noqa: BLE001 — 观测绝不反噬 LLM
                    pass

                messages.append(full_message)
                tool_calls = getattr(full_message, "tool_calls", [])
                if tool_calls:
                    blocking_marker_seen = False
                    # 同一个 LLM response 内多个 tool_call 共享 batch_id，前端据此
                    # 渲染为"同批并行"的横向 chip 流。语义对齐：LLM 一次决定要调
                    # 哪几个工具就是一批，即使执行上是串行的（执行串行是当前实现
                    # 细节，未来若改并发也不影响 batch 语义）。
                    batch_id = f"batch_{uuid.uuid4().hex[:8]}" if len(tool_calls) > 1 else ""
                    for tool_call in tool_calls:
                        tool_name = str(tool_call.get("name", ""))
                        tool_call_id = str(
                            tool_call.get("id", "") or f"tool_{uuid.uuid4().hex[:8]}"
                        )
                        arguments = tool_call.get("args", {})
                        if tool_name not in tool_specs:
                            error_msg = f"未知工具: {tool_name}"
                            yield AgentEvent(
                                type=ERROR,
                                data=_inject_metadata(
                                    {"message": error_msg},
                                    self._config.model,
                                    self._config.session_id,
                                ),
                            )
                            self._result = _make_agent_result(
                                status="error",
                                error=error_msg,
                                usage=total_usage,
                            )
                            return

                        tool_part_id, tool_part_idx, prev_closed_idx = collector.start_tool_use(
                            tool_call_id=tool_call_id,
                            name=tool_name,
                            input=arguments if isinstance(arguments, dict) else {},
                            batch_id=batch_id or None,
                        )
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
                        # 新事件：tool_use 会封口当前 streaming text/thinking。
                        # 先发被封口 part 的 part_completed，再发新 tool_use part 的 part_started。
                        if prev_closed_idx is not None:
                            yield _make_part_event(
                                type_=PART_COMPLETED,
                                index=prev_closed_idx,
                                model=self._config.model,
                                session_id=self._config.session_id,
                                part={"index": prev_closed_idx, "state": "done"},
                            )
                        tool_part_payload: dict[str, Any] = {
                            "id": tool_part_id,
                            "type": "tool_use",
                            "index": tool_part_idx,
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "input": arguments,
                            "status": "running",
                        }
                        if batch_id:
                            tool_part_payload["batch_id"] = batch_id
                        yield _make_part_event(
                            type_=PART_STARTED,
                            index=tool_part_idx,
                            model=self._config.model,
                            session_id=self._config.session_id,
                            part=tool_part_payload,
                        )

                        result, tool_message, intercepted = await self._execute_tool_call(
                            tool_specs,
                            tool_name=tool_name,
                            tool_call_id=tool_call_id,
                            arguments=arguments,
                            budget=budget,
                        )
                        raw_result = _normalize_tool_result(result)
                        # 序列化 result 为 string —— 与 langchain_runner.py L608
                        # (tool_msg.content) 和 graph.py:_coerce_snapshot_result 对齐。
                        # 否则前端收到 dict 后用 JSON.parse 会因为隐式 toString 成
                        # "[object Object]" 而失败，导致 create_coding_plan 的
                        # session_id 在 ChatMessageBubble 里解析为空字符串，进而
                        # confirm 请求 URL 变成 /coding-sessions//confirm/ → 404。
                        result_for_event = _tool_result_to_content(raw_result)
                        completed_idx = collector.complete_tool_use(
                            tool_call_id=tool_call_id,
                            success=result.success,
                            result=result_for_event,
                        )
                        tool_event_data: dict[str, Any] = {
                            "tool_name": tool_name,
                            "tool_call_id": tool_call_id,
                            "success": result.success,
                            "input": arguments,
                            "result": result_for_event,
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
                        # 新事件：tool_use part 完成
                        if completed_idx is not None:
                            yield _make_part_event(
                                type_=PART_COMPLETED,
                                index=completed_idx,
                                model=self._config.model,
                                session_id=self._config.session_id,
                                part={
                                    "id": tool_part_id,
                                    "type": "tool_use",
                                    "index": completed_idx,
                                    "tool_call_id": tool_call_id,
                                    "status": "done" if result.success else "error",
                                    "result": result_for_event,
                                },
                            )
                        messages.append(tool_message)

                        if isinstance(result.output, dict) and result.output.get(
                            "__blocking_task__"
                        ):
                            blocking_marker_seen = True

                    if blocking_marker_seen:
                        collector.flush_all()
                        payload = collector.to_message_payload()
                        self._result = _make_agent_result(
                            status="completed",
                            final_answer="".join(accumulated_text),
                            usage=total_usage,
                            metadata={"cost_usd": 0, "parts": payload["parts"]},
                        )
                        return
                    budget.on_turn_complete()
                    continue

                final_answer = _extract_message_text(full_message)
                collector.flush_all()
                payload = collector.to_message_payload()
                self._result = _make_agent_result(
                    status="completed",
                    final_answer=final_answer,
                    usage=total_usage,
                    metadata={"cost_usd": 0, "parts": payload["parts"]},
                )
                yield _build_message_complete(
                    final_answer=final_answer,
                    usage=total_usage,
                    model=self._config.model,
                    session_id=self._config.session_id,
                    parts=payload["parts"],
                )
                return

            # Phase P15：max_turns 真用尽（含 force-final 那一轮）才会到这里。
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
            collector.flush_all()
            payload = collector.to_message_payload()
            self._result = _make_agent_result(
                status="completed",
                final_answer=degraded_answer,
                usage=total_usage,
                metadata={
                    "cost_usd": 0,
                    "degraded": True,
                    "degraded_reason": "max_turns_exhausted",
                    "max_turns": self._config.max_turns,
                    "parts": payload["parts"],
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
                        "parts": payload["parts"],
                    },
                    self._config.model,
                    self._config.session_id,
                ),
            )
        except asyncio.CancelledError:
            # REGION: interrupt-latch-fix-coding-plan workflow-2026-05-21
            # major #1 ERROR 路径 parts 携带契约：flush_all 后再发 message_complete。
            # 不可短路：collector 把所有 streaming text 标 done、未完成 tool_use 标
            # error+cancelled，message_complete payload 必须带 parts 给前端兜底渲染。
            partial_text = "".join(accumulated_text)
            collector.flush_all()
            payload = collector.to_message_payload()
            self._result = _make_agent_result(
                status="interrupted",
                final_answer=partial_text,
                usage=total_usage,
                metadata={"cost_usd": 0, "parts": payload["parts"]},
            )
            yield _build_message_complete(
                final_answer=partial_text,
                usage=total_usage,
                model=self._config.model,
                session_id=self._config.session_id,
                status="interrupted",
                parts=payload["parts"],
            )
            # ENDREGION: interrupt-latch-fix-coding-plan workflow-2026-05-21
            raise
        except ContextWindowExceededError as exc:
            # implementation contract chat 路径集成：SSE ERROR 结构化 payload。
            # 消息格式同源 ``langchain_runner.py`` work item strict_error；
            # regex / payload schema 照抄 ``base_agent.py`` work item（字段名差异：
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
            # Phase P15：原局部变量名为 budget，与方法顶部 _ToolBudget
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
            # security mitigation-01 / security mitigation-02 mitigation）。字段白名单：
            # session_id / model / estimated_tokens / max_tokens / exceeded_by。
            logger.warning(
                "chat_runner_context_exceeded",
                session_id=self._config.session_id,
                model=self._config.model,
                estimated_tokens=estimated,
                max_tokens=ctx_budget,
                exceeded_by=exceeded,
            )
            # REGION: interrupt-latch-fix-coding-plan workflow-2026-05-21
            # major #1 ERROR 路径 parts 携带契约：context exceeded 同样需要 flush_all
            # + 追发一条 MESSAGE_COMPLETE 让前端能渲染已收集 parts（不替代结构化 ERROR）。
            collector.flush_all()
            payload = collector.to_message_payload()
            self._result = _make_agent_result(
                status="error",
                error=msg,
                usage=total_usage,
                metadata={"parts": payload["parts"]},
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
            yield _build_message_complete(
                final_answer="".join(accumulated_text),
                usage=total_usage,
                model=self._config.model,
                session_id=self._config.session_id,
                status="error",
                parts=payload["parts"],
            )
            # ENDREGION: interrupt-latch-fix-coding-plan workflow-2026-05-21
        except Exception as exc:
            # REGION: interrupt-latch-fix-coding-plan workflow-2026-05-21
            # major #1 ERROR 路径 parts 携带契约：generic Exception 同样发 ERROR +
            # 追发 MESSAGE_COMPLETE，让前端能渲染中段已生成的 text/tool_use。
            logger.exception("chat_runner_error", session_id=self._config.session_id)
            # 72-02：上游错误（429/529 单列）落一行 failure ModelUsageRecord —— 只取
            # 数值 status_code，绝不落异常文本（T-72-02-01）；best-effort 不反噬。
            try:
                _upstream_code = parse_upstream_status(exc)
                await arecord_llm_usage(
                    call_source=get_call_source() or CallSource.CHAT.value,
                    provider=str(self._config.provider_type),
                    model=self._config.model,
                    upstream_status_code=_upstream_code,
                    failure_type=str(_upstream_code) if _upstream_code is not None else "error",
                    source="chat",
                )
            except Exception:  # noqa: BLE001 — 观测绝不反噬 LLM
                pass
            collector.flush_all()
            payload = collector.to_message_payload()
            self._result = _make_agent_result(
                status="error",
                error=str(exc),
                usage=total_usage,
                metadata={"parts": payload["parts"]},
            )
            yield AgentEvent(
                type=ERROR,
                data=_inject_metadata(
                    {"message": str(exc)}, self._config.model, self._config.session_id
                ),
            )
            yield _build_message_complete(
                final_answer="".join(accumulated_text),
                usage=total_usage,
                model=self._config.model,
                session_id=self._config.session_id,
                status="error",
                parts=payload["parts"],
            )
            # ENDREGION: interrupt-latch-fix-coding-plan workflow-2026-05-21
        finally:
            self._run_task = None
        # ENDREGION: interrupt-latch-fix-coding-plan workflow-2026-05-21

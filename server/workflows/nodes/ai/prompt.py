"""AI Prompt node for general LLM interactions.

implementation / contract：三路径收敛到 build_chat_model.ainvoke 单入口
（contract~05）。保留 BaseNode 继承与 OpenResponses dataclass 向后兼容。
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger()

# Pitfall #11：reasoning 模型 `.bind(temperature=...)` 静默 strip（llm_factory work item
# 已 pop temperature/top_p）；本节点在 _call_llm 入口处先行 warning，便于 observability。
_REASONING_MODEL_PATTERN = re.compile(r"^(o[1-9]|o4-mini|gpt-5)")


# ============================================================================
# OpenResponses-compatible response dataclass 族（https://www.openresponses.org/）
# ============================================================================


@dataclass
class OutputItem:
    """OpenResponses output item 基类（message / reasoning / function_call）。"""

    type: Literal["message", "reasoning", "function_call"]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type}


@dataclass
class MessageItem(OutputItem):
    """message 输出项（文本内容）。"""

    type: Literal["message"] = field(default="message")
    role: str = "assistant"
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "role": self.role, "content": self.content}


@dataclass
class ReasoningItem(OutputItem):
    """reasoning 输出项（thinking 模型的推理过程）。"""

    type: Literal["reasoning"] = field(default="reasoning")
    content: str = ""
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.type, "content": self.content}
        if self.summary:
            result["summary"] = self.summary
        return result


@dataclass
class Usage:
    """OpenResponses 三字段 token 统计。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LLMResponse:
    """OpenResponses 统一响应（output / usage / model / status）。"""

    output: list[OutputItem] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    status: str = "completed"

    @property
    def text(self) -> str:
        texts = [item.content for item in self.output if isinstance(item, MessageItem)]
        return "\n".join(texts)

    @property
    def thinking(self) -> str:
        texts = [item.content for item in self.output if isinstance(item, ReasoningItem)]
        return "\n".join(texts)

    @property
    def has_thinking(self) -> bool:
        return any(isinstance(item, ReasoningItem) for item in self.output)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": [
                item.to_dict() for item in self.output if hasattr(item, "to_dict")
            ],
            "text": self.text,
            "thinking": self.thinking,
            "has_thinking": self.has_thinking,
            "usage": self.usage.to_dict(),
            "model": self.model,
            "status": self.status,
        }


# 默认支持的模型列表（当未配置自定义 API 时使用）
DEFAULT_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-3-7-sonnet-20250219",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
]


@register_node
class AIPromptNode(BaseNode):
    """AI Prompt 节点

    通用的 LLM 交互节点，支持自定义 System Prompt 和 User Prompt。
    可用于需求分析、内容生成、数据处理等各种 AI 任务。
    支持自定义 API Base URL 和 API Key，兼容 OpenAI API 协议。
    """

    node_type = "ai_prompt"
    display_name = "AI Prompt"
    description = "通用 AI 节点，支持自定义提示词和 API 配置"
    icon = "message-square"
    category = NodeCategory.AI
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            # API 配置
            "use_custom_api": {
                "type": "boolean",
                "title": "使用自定义 API",
                "description": "启用后可配置自定义的 API 地址和密钥",
                "default": False,
            },
            "api_base_url": {
                "type": "string",
                "title": "API Base URL",
                "description": "自定义 API 地址，如 https://api.openai.com/v1",
                "default": "",
            },
            "api_key": {
                "type": "string",
                "title": "API Key",
                "description": "API 密钥（可为空，某些本地部署无需密钥）",
                "default": "",
            },
            # 提示词配置
            "system_prompt": {
                "type": "string",
                "title": "System Prompt",
                "description": "系统提示词，定义 AI 的角色和行为",
                "default": "你是一个专业的软件开发助手。",
            },
            "user_prompt": {
                "type": "string",
                "title": "User Prompt",
                "description": "用户提示词，支持模板变量如 {{global.description}}",
                "minLength": 1,
            },
            # 模型配置
            "model": {
                "type": "string",
                "title": "模型",
                "description": "使用的 LLM 模型",
                "default": "",
            },
            "temperature": {
                "type": "number",
                "title": "温度",
                "description": "控制输出的随机性，0 为确定性，2 为最随机",
                "minimum": 0,
                "maximum": 2,
                "default": 0.7,
            },
            "max_tokens": {
                "type": "integer",
                "title": "最大 Token 数",
                "description": "生成的最大 token 数量",
                "minimum": 1,
                "maximum": 128000,
                "default": 4096,
            },
            "output_format": {
                "type": "string",
                "title": "输出格式",
                "description": "期望的输出格式",
                "enum": ["text", "json", "markdown"],
                "default": "text",
            },
            "json_schema": {
                "type": "object",
                "title": "JSON Schema",
                "description": "当输出格式为 JSON 时，可指定期望的结构",
                "default": {},
            },
            # 高级设置
            "max_thinking_tokens": {
                "type": "integer",
                "title": "最大思考 Token 数",
                "description": "Claude 扩展思考的 token 上限，仅 Claude 模型支持。留空使用默认值",
                "minimum": 1024,
                "maximum": 128000,
            },
            "max_budget_usd": {
                "type": "number",
                "title": "预算上限 (USD)",
                "description": "单次调用的美元成本上限，留空不限制",
                "minimum": 0.01,
                "maximum": 100.0,
            },
            "provider_credential_id": {
                "type": "string",
                "format": "uuid",
                "title": "Provider 凭证（节点级）",
                "description": "指定本节点使用的凭证 ID，空则按空间/系统默认解析。",
                "default": "",
            },
        },
        "required": ["user_prompt"],
    }

    inputs = [
        NodePort(
            name="default",
            label="输入",
            port_type=PortType.OBJECT,
            required=False,
            description="上游节点输出，可在模板中引用",
        ),
    ]

    outputs = [
        NodePort(
            name="default",
            label="AI 响应",
            port_type=PortType.OBJECT,
            description="包含 response、usage 和 OpenResponses 格式的输出",
            schema={
                "type": "object",
                "properties": {
                    "response": {
                        "oneOf": [
                            {"type": "string", "description": "文本格式的响应"},
                            {"type": "object", "description": "JSON 格式的响应"},
                        ],
                        "description": "解析后的响应内容（根据 output_format 决定类型）",
                    },
                    "text": {"type": "string", "description": "AI 回复主要文本"},
                    "thinking": {"type": "string", "description": "思考过程（仅 thinking 模型）"},
                    "has_thinking": {"type": "boolean", "description": "是否包含思考内容"},
                    "output": {
                        "type": "array",
                        "description": "OpenResponses 格式输出项列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["message", "reasoning"]},
                                "content": {"type": "string"},
                                "role": {"type": "string", "description": "仅 message"},
                                "summary": {"type": "string", "description": "仅 reasoning（可选）"},
                            },
                        },
                    },
                    "usage": {
                        "type": "object",
                        "description": "Token 使用统计",
                        "properties": {
                            "input_tokens": {"type": "integer"},
                            "output_tokens": {"type": "integer"},
                            "total_tokens": {"type": "integer"},
                        },
                    },
                    "model": {"type": "string", "description": "使用的模型名称"},
                    "output_format": {
                        "type": "string",
                        "enum": ["text", "json", "markdown"],
                    },
                    "raw_response": {"type": "string", "description": "原始文本（向后兼容）"},
                },
            },
        ),
        NodePort(
            name="error",
            label="失败",
            port_type=PortType.OBJECT,
            description="调用失败时的错误信息",
            schema={
                "type": "object",
                "properties": {
                    "error": {"type": "string", "description": "错误信息"},
                    "error_type": {"type": "string", "description": "错误类型"},
                },
            },
        ),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """执行 AI 提示词调用"""
        config = context.node_config

        # 解析配置
        system_prompt = context.render_template(config.get("system_prompt", ""))
        user_prompt = context.render_template(config.get("user_prompt", ""))
        model = config.get("model", "")
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 4096)
        output_format = config.get("output_format", "text")
        json_schema = config.get("json_schema", {})
        max_thinking_tokens: int | None = config.get("max_thinking_tokens")
        # 自定义 API 配置
        use_custom_api = config.get("use_custom_api", False)
        api_base_url = config.get("api_base_url", "")
        api_key = config.get("api_key", "")

        # 验证
        if not user_prompt:
            return NodeResult(
                status="failed",
                error="User Prompt 不能为空",
                next_handle="error",
            )

        try:
            # 根据输出格式调整提示词
            formatted_user_prompt = self._format_prompt_for_output(
                user_prompt, output_format, json_schema
            )

            # 调用 LLM（task：传入节点级 provider_credential_id）
            llm_response = await self._call_llm(
                system_prompt=system_prompt,
                user_prompt=formatted_user_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                context=context,
                use_custom_api=use_custom_api,
                api_base_url=api_base_url,
                api_key=api_key,
                max_thinking_tokens=max_thinking_tokens,
                provider_credential_id=config.get("provider_credential_id", ""),
            )

            # 解析输出
            parsed_response = self._parse_response(llm_response.text, output_format)

            logger.info(
                "ai_prompt_completed",
                model=model,
                input_tokens=llm_response.usage.input_tokens,
                output_tokens=llm_response.usage.output_tokens,
                has_thinking=llm_response.has_thinking,
            )

            return NodeResult(
                status="completed",
                output={
                    "response": parsed_response,
                    "text": llm_response.text,
                    "thinking": llm_response.thinking,
                    "raw_response": llm_response.text,  # backward compatibility
                    "model": model,
                    "usage": llm_response.usage.to_dict(),
                    "output": [
                        item.to_dict() for item in llm_response.output if hasattr(item, "to_dict")
                    ],
                    "output_format": output_format,
                    "has_thinking": llm_response.has_thinking,
                },
                next_handle="default",
            )

        except Exception as e:
            logger.error("ai_prompt_failed", error=str(e), model=model)
            return NodeResult(
                status="failed",
                error=str(e),
                next_handle="error",
            )

    def _format_prompt_for_output(self, prompt: str, output_format: str, json_schema: dict) -> str:
        """根据输出格式调整提示词"""
        if output_format == "json":
            schema_hint = ""
            if json_schema:
                schema_hint = f"\n\n期望的 JSON 结构:\n```json\n{json.dumps(json_schema, indent=2, ensure_ascii=False)}\n```"
            return f"{prompt}\n\n请以有效的 JSON 格式输出。{schema_hint}"

        elif output_format == "markdown":
            return f"{prompt}\n\n请使用 Markdown 格式输出。"

        return prompt

    def _parse_response(self, response: str, output_format: str) -> Any:
        """解析 LLM 响应"""
        if output_format == "json":
            try:
                # 尝试提取 JSON 块
                if "```json" in response:
                    start = response.find("```json") + 7
                    end = response.find("```", start)
                    json_str = response[start:end].strip()
                elif "```" in response:
                    start = response.find("```") + 3
                    end = response.find("```", start)
                    json_str = response[start:end].strip()
                else:
                    json_str = response.strip()

                return json.loads(json_str)
            except json.JSONDecodeError:
                # 如果解析失败，返回原始文本
                return {"raw": response, "parse_error": True}

        return response

    def _aimessage_to_llm_response(
        self, aimsg: AIMessage, model: str
    ) -> LLMResponse:
        """AIMessage.content_blocks → OpenResponses LLMResponse（contract 向后兼容）。

        llm_factory.py L94 已锁 output_version='v1'；content_blocks 字段矩阵：
        - {"type": "text", "text": "..."}                         → MessageItem(content=text)
        - {"type": "reasoning"/"thinking", "reasoning"/"thinking"/"text": "..."}
            → ReasoningItem(content=<first non-empty>)

        usage 按 OpenResponses 三字段（implementation contract 明确不迁六字段 TokenUsage）：
        input_tokens / output_tokens / total_tokens = input + output。
        """
        output_items: list[OutputItem] = []

        # content_blocks 迭代（对齐 langchain_runner._extract_content_blocks 策略）
        blocks = getattr(aimsg, "content_blocks", None)
        if isinstance(blocks, list):
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and block.get("text"):
                    output_items.append(MessageItem(content=str(block["text"])))
                elif btype in {"reasoning", "thinking"}:
                    content = (
                        block.get("reasoning")
                        or block.get("thinking")
                        or block.get("text")
                        or ""
                    )
                    if content:
                        output_items.append(ReasoningItem(content=str(content)))

        # fallback：content_blocks 为空（非 v1 schema；罕见）时按 aimsg.text 兜底
        if not output_items:
            text = getattr(aimsg, "text", "") or str(aimsg.content or "")
            if text:
                output_items.append(MessageItem(content=text))

        meta = getattr(aimsg, "usage_metadata", None) or {}
        input_t = int(meta.get("input_tokens", 0) or 0)
        output_t = int(meta.get("output_tokens", 0) or 0)

        return LLMResponse(
            output=output_items,
            usage=Usage(
                input_tokens=input_t,
                output_tokens=output_t,
                total_tokens=input_t + output_t,
            ),
            model=model,
        )

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
        context: ExecutionContext,
        use_custom_api: bool = False,
        api_base_url: str = "",
        api_key: str = "",
        max_thinking_tokens: int | None = None,
        provider_credential_id: str = "",
    ) -> LLMResponse:
        """单入口收敛（work item / contract 全系列）：走 build_chat_model.ainvoke 单 turn。

        - use_custom_api=True 走分歧 A（临时 ResolvedProviderConfig，source="node"
          + extra.custom_api=True）；否则走 aresolve_or_error 四层解析（Result 模式）。
        - **task 启用**：`provider_credential_id` 非空时，aresolve_or_error
          传 `node_config={"provider_credential_id": provider_credential_id}`；
          命中节点级 FK 后做 API tier scope 校验（work item 安全硬化）：
          resolved.credential_id 指向的凭证若 scope=="project" 且 scope_id != project.id
          → 拒绝（raise ValueError）。security mitigation-01 disposition=mitigate 真正落地。
        - use_custom_api=True 与 provider_credential_id 同时填 → use_custom_api 优先
          （分歧 A）。

        Returns:
            LLMResponse: OpenResponses 格式统一响应（text / thinking / usage / model）。
        """
        # 分歧 D / Pitfall #5：build_chat_model 必须函数体内 import，避免
        # FakeChatModel seam monkeypatch `workflows.nodes.ai.prompt.build_chat_model`
        # 命中但未被当前函数引用的脱靶问题（测试侧双 patch 同时覆盖两条路径）。
        from agents.llm_factory import build_chat_model
        from services.provider_config import (
            ProviderConfigService,
            ProviderMissingError,
            ProviderType,
            ResolvedProviderConfig,
        )

        project = await self._get_project(context)

        # 分歧 A：use_custom_api=True 降级路径 —— 构造临时 ResolvedProviderConfig。
        # source 仍为四态之一（"node"），不新增第 5 种枚举值（严禁 D 守护）；
        # custom_api 事实通过 extra 标记，implementation contract Inspector 可识别。
        if use_custom_api and api_base_url:
            if not model:
                raise ValueError("使用自定义 API 时必须指定模型")
            resolved = ResolvedProviderConfig(
                provider_type=ProviderType.OPENAI_CHAT,
                api_key=api_key,
                base_url=api_base_url,
                source="node",
                credential_id=None,
                extra={"custom_api": True, "source_detail": "node_custom_api"},
            )
        else:
            # 四层解析 Result 模式（contract）。task 启用 node_config 字段传值：
            # provider_credential_id 非空时传入 aresolve_or_error（节点级 FK 解析）。
            node_config: dict[str, Any] | None = None
            if provider_credential_id:
                node_config = {"provider_credential_id": provider_credential_id}
            result = await ProviderConfigService.aresolve_or_error(
                node_config=node_config,
                project=project,
            )
            if isinstance(result, ProviderMissingError):
                raise ValueError(
                    f"未配置 {result.missing_provider} Provider 凭证："
                    f"{result.recommended_action}"
                )
            resolved = result

            # work item API tier 安全硬化（security mitigation-01 disposition=mitigate）：
            # 节点级凭证 scope 校验，防跨 project 越权。仅当命中节点级 FK 时检查。
            # 权威路径 server/system/models.py L102。
            if resolved.source == "node" and resolved.credential_id is not None:
                from system.models import ProviderCredential

                try:
                    cred = await ProviderCredential.objects.aget(
                        id=resolved.credential_id
                    )
                except ProviderCredential.DoesNotExist as exc:
                    raise ValueError(
                        f"未配置 Provider 凭证：provider_credential_id="
                        f"{resolved.credential_id} 不存在"
                    ) from exc
                space_id_str = str(project.id) if project is not None else ""
                if cred.scope == "project" and str(cred.scope_id) != space_id_str:
                    raise ValueError(
                        f"未配置 {resolved.provider_type.value} Provider 凭证："
                        f"节点 provider_credential_id 指向他 project 凭证，"
                        f"已拒绝（scope 校验失败）"
                    )

            # model 空值 fallback（contract：不再按模型前缀分派；仅 model 本身空时兜底）
            # 从 resolved.extra.default_model 读取（替代 v8.1 aget_claude_config 路径）
            if not model:
                model = (resolved.extra or {}).get("default_model", "") or ""
            if not model:
                raise ValueError(
                    "未配置默认模型，请在系统设置或空间设置中配置默认模型"
                )

        # Pitfall #11：reasoning 模型 .bind(temperature=...) 会被 llm_factory 静默 strip。
        # 本节点在入口处先 warning，便于 observability（不阻断执行）。
        if _REASONING_MODEL_PATTERN.match(model) and abs(temperature - 1.0) > 1e-6:
            logger.warning(
                "ai_prompt_temperature_stripped",
                model=model,
                temperature=temperature,
                reason="reasoning 模型不支持 temperature；LangChain 会自动 strip",
            )

        # 构造 BaseChatModel（非 streaming 单 turn；max_tokens>0 时覆盖 capabilities 默认）
        chat_model = build_chat_model(
            resolved=resolved,
            model=model,
            max_thinking_tokens=max_thinking_tokens,
            max_output_tokens=max_tokens if max_tokens and max_tokens > 0 else None,
            streaming=False,
        )

        # 构造 messages（Anti-pattern A：不使用 prompt template；纯字符串双包装）。
        # system_prompt 为空时不加 SystemMessage（与旧 OpenAI 兼容路径行为对齐）。
        messages: list[BaseMessage] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=user_prompt))

        # contract / contract：temperature 通过 .bind 透传；reasoning 模型自动 strip。
        ai_msg: AIMessage = await chat_model.bind(
            temperature=temperature
        ).ainvoke(messages)

        return self._aimessage_to_llm_response(ai_msg, model)

    async def _get_project(self, context: ExecutionContext):
        """获取关联的空间"""
        if context.workflow_execution:
            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related(
                "workflow__space"
            ).aget(id=context.workflow_execution.id)
            if we.workflow:
                return we.workflow.space
        return None

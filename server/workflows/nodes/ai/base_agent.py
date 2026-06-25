"""AIAgentBaseNode - Shared base class for AI agent workflow nodes.

Extracts common execution logic (session management, LangChainAgentRunner
construction, result mapping) into a base class. Subclasses only need to
override 5 hook methods to define specialized node behavior.

implementation Wave AIAgentBaseNode.execute 统一走 LangChainAgentRunner
（替换 v20.0 之前的 SDK 子工厂路径）；`_resolve_api_key_and_model` 签名由三元组
`(api_key, model, base_url)` 调整为二元组
`(ResolvedProviderConfig, model)`（contract）；use_custom_api 路径构造临时
ResolvedProviderConfig(source="node", extra={"custom_api": True, ...})
（分歧 A 覆盖 contract）；None -> [] 工具映射（分歧 B 覆盖 contract）。
"""

import asyncio
import re
from abc import abstractmethod
from typing import Any, ClassVar, Literal

import structlog
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from agents.core.result import AgentResult
from agents.langchain_runner import (
    ContextWindowExceededError,
    LangChainAgentRunner,
    LangChainRunnerConfig,
)
from agents.models import AgentSession
from agents.tools.langchain_adapter import build_langchain_tools
from services.model_capabilities import ModelCapabilities
from services.provider_config import (
    ProviderConfigService,
    ProviderMissingError,
    ProviderType,
    ResolvedProviderConfig,
)
from workflows.nodes.ai.sub_step_mixin import SubStepMixin
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodeResult,
)

logger = structlog.get_logger()


class AIAgentBaseNode(SubStepMixin, BaseNode):
    """Base class for AI agent workflow nodes.

    Provides unified execute flow with 5 hook methods for subclass customization:
    1. get_system_prompt  - Return system prompt (abstract)
    2. get_user_prompt    - Return user prompt (abstract)
    3. get_enabled_tools  - Return enabled tool names (default: from config)
    4. get_max_iterations  - Return max iterations (default: from config)
    5. map_output         - Map AgentResult to output dict (default implementation)

    Common infrastructure (session, LangChainAgentRunner) is handled here.
    """

    category: ClassVar[NodeCategory] = NodeCategory.AI
    execution_mode: ClassVar[Literal["server_local", "runner_dispatched"]] = "server_local"
    is_blocking: ClassVar[bool] = True

    # Base config schema with common fields; subclasses extend via dict merge
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "model": {
                "type": "string",
                "title": "模型",
                "description": "使用的 LLM 模型",
                "default": "",
            },
            "chat_id": {
                "type": "string",
                "title": "Chat ID",
                "description": "Feishu chat group ID for sending messages, supports template variables",
                "default": "",
            },
            "use_custom_api": {
                "type": "boolean",
                "title": "使用自定义 API",
                "description": "启用后可配置自定义的 API 地址和密钥",
                "default": False,
            },
            "api_base_url": {
                "type": "string",
                "title": "API Base URL",
                "description": "自定义 API 地址",
                "default": "",
            },
            "api_key": {
                "type": "string",
                "title": "API Key",
                "description": "API 密钥",
                "default": "",
            },
            "api_format": {
                "type": "string",
                "title": "API 格式",
                "description": "API 协议格式：anthropic（Claude 原生）或 openai（兼容格式）",
                "enum": ["anthropic", "openai"],
                "default": "anthropic",
            },
            "provider_type": {
                "type": "string",
                "title": "Provider 类型",
                "description": "LLM Provider 类型，为空时继承空间级或系统级配置",
                "default": "",
            },
            "timeout_hours": {
                "type": "integer",
                "title": "Suspension Timeout (hours)",
                "description": "Maximum wait time after agent suspension",
                "default": 24,
            },
            # 高级设置
            "max_thinking_tokens": {
                "type": "integer",
                "title": "最大思考 Token 数",
                "description": "Claude 扩展思考的 token 上限，仅 Claude 模型支持。留空使用默认值",
                "minimum": 1024,
                "maximum": 128000,
            },
            "max_output_tokens": {
                "type": "integer",
                "title": "最大输出 Token 数",
                "description": "LLM 单次响应的最大 token 数。留空使用模型 capabilities 默认值。",
                "minimum": 100,
                "maximum": 200000,
            },
            "max_budget_usd": {
                "type": "number",
                "title": "预算上限 (USD)",
                "description": "单次调用的美元成本上限，留空不限制",
                "minimum": 0.01,
                "maximum": 100.0,
            },
            "timeout_minutes": {
                "type": "integer",
                "title": "超时时间 (分钟)",
                "description": "Agent 执行的最大超时时间，超时后自动终止。留空使用默认值（10 分钟）",
                "minimum": 1,
                "maximum": 120,
            },
            "provider_credential_id": {
                "type": "string",
                "format": "uuid",
                "title": "Provider 凭证（节点级）",
                "description": "指定本节点使用的凭证 ID，空则按空间/系统默认解析。",
                "default": "",
            },
        },
        "required": [],
    }

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> list[str]:
        """扩展 BaseNode.validate_config：启用自定义 API 时 api_base_url 必填（228 work item 关闭）。

        Pitfall 6：必须先 super() 才能保留既有 jsonschema.validate（max_thinking_tokens
        范围、max_output_tokens 边界等规则）。
        Pitfall 7：jsonschema validator 默认 Draft 4，不一定支持 allOf.if/then/required
        → 走 Python 侧显式判定最稳（方案 B）。
        implementation / work item §Fix 4 后端错误锁文案。

        Threat mitigation：
        - security mitigation-01 Spoofing / Authentication Confusion：保存前拒绝非法组合 → 运行时
          ``if use_custom_api and api_base_url:`` fallthrough 永不命中
        - security mitigation-03 Input Validation：``.strip()`` 同时兼顾 None / 空字符串 / 空白符
        - security mitigation-05 Bypass：DRF Serializer 链路拦截 curl 直连构造
        """
        errors = super().validate_config(config)
        if config.get("use_custom_api") is True and not str(
            config.get("api_base_url", ""),
        ).strip():
            errors.append("启用自定义 API 时必须填写 API Base URL")
        return errors

    # ===== Hook methods (subclass overrides) =====

    @abstractmethod
    def get_system_prompt(self, context: ExecutionContext) -> str:
        """Return the system prompt for the agent.

        Args:
            context: Node execution context.

        Returns:
            System prompt string.
        """

    @abstractmethod
    def get_user_prompt(self, context: ExecutionContext) -> str:
        """Return the user prompt for the agent.

        Args:
            context: Node execution context.

        Returns:
            User prompt string.
        """

    def get_enabled_tools(self, context: ExecutionContext) -> list[str] | None:
        """Return list of enabled tool names, or None for all tools.

        Default: reads 'enabled_tools' from config. Empty list -> None (all tools).

        Args:
            context: Node execution context.

        Returns:
            List of tool name strings, or None to enable all tools.
        """
        tools: list[str] = context.node_config.get("enabled_tools", [])
        return tools if tools else None

    def get_max_iterations(self, context: ExecutionContext) -> int:
        """Return maximum agent turns.

        Default: reads 'max_iterations' from config, fallback 25.

        Args:
            context: Node execution context.

        Returns:
            Maximum iteration count.
        """
        value: int = context.node_config.get("max_iterations", 25)
        return value

    def map_output(self, result: AgentResult) -> dict[str, Any]:
        """Map AgentResult to node output dict.

        Default: returns final_answer, output, usage, metadata.

        Args:
            result: Completed agent result.

        Returns:
            Output dict for NodeResult.
        """
        return {
            "final_answer": result.final_answer,
            "output": result.output,
            "usage": result.usage,
            "metadata": result.metadata,
        }

    # ===== Common infrastructure methods =====

    async def _get_project(self, context: ExecutionContext) -> Any:
        """Get associated project via workflow_execution."""
        if context.workflow_execution:
            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related(
                "workflow__space"
            ).aget(id=context.workflow_execution.id)
            if we.workflow:
                return we.workflow.space
        return None

    async def _get_user(self, context: ExecutionContext) -> Any:
        """Get triggering user via workflow_execution."""
        if context.workflow_execution:
            from workflows.models import WorkflowExecution

            we = await WorkflowExecution.objects.select_related(
                "triggered_by"
            ).aget(id=context.workflow_execution.id)
            return we.triggered_by
        return None

    async def _resolve_from_snapshot_or_runtime(
        self,
        context: ExecutionContext,
        project: Any,
        config_model: str = "",
        use_custom_api: bool = False,
        api_base_url: str = "",
        api_key: str = "",
        provider_type: str = "",
        provider_credential_id: str = "",
    ) -> tuple[ResolvedProviderConfig, str]:
        """implementation contract contract/contract：优先读 ExecutionContext.node_snapshots，
        miss 时 fallback 到 _resolve_api_key_and_model 运行时解析。

        快照命中契约（contract）：
            - context.node_snapshots[node_id] 存在且结构合法 → 从快照构造
              ResolvedProviderConfig（不再调 aresolve_or_error，保证 Replay 稳定）
            - snapshot.credential_id 非 None 时，异步加载凭证 api_key / base_url
              （与运行时路径一致，避免 chat runner 拿不到 api_key）
            - use_custom_api=True 时绕过快照（节点级自定义 API 始终走运行时路径）

        Miss 契约（contract）：
            - 无 snapshot dict / node_id 不在 dict / snapshot 字段非法 →
              结构化 warning log `snapshot.miss_fallback_to_runtime_resolve`
              + 委托 _resolve_api_key_and_model 继续运行时解析
        """
        # 1. use_custom_api 始终绕过快照（自定义 API 不持久化到 snapshot）
        if use_custom_api:
            return await self._resolve_api_key_and_model(
                project,
                config_model=config_model,
                use_custom_api=use_custom_api,
                api_base_url=api_base_url,
                api_key=api_key,
                provider_type=provider_type,
                provider_credential_id=provider_credential_id,
            )

        # 2. 读 snapshot dict（ExecutionContext 字段 OR workflow_execution.context 兜底）
        snap_dict: dict[str, dict] = getattr(context, "node_snapshots", {}) or {}
        if not snap_dict and getattr(context, "workflow_execution", None) is not None:
            we_ctx = (context.workflow_execution.context or {})
            snap_dict = we_ctx.get("node_snapshots") or {}

        snapshot = snap_dict.get(str(context.node_id)) if snap_dict else None

        # 3. snapshot miss → warning log + runtime fallback
        if not snapshot or not isinstance(snapshot, dict):
            logger.warning(
                "snapshot.miss_fallback_to_runtime_resolve",
                execution_id=(
                    str(context.workflow_execution.id)
                    if getattr(context, "workflow_execution", None) is not None
                    else None
                ),
                node_id=str(context.node_id),
                reason="snapshot_missing" if not snapshot else "snapshot_malformed",
            )
            return await self._resolve_api_key_and_model(
                project,
                config_model=config_model,
                use_custom_api=False,
                api_base_url=api_base_url,
                api_key=api_key,
                provider_type=provider_type,
                provider_credential_id=provider_credential_id,
            )

        # 4. snapshot 命中 → 构造 ResolvedProviderConfig
        snap_provider_type = snapshot.get("provider_type", "")
        snap_model = snapshot.get("model", "") or config_model
        snap_source = snapshot.get("source", "system")
        snap_credential_id_raw = snapshot.get("credential_id")

        try:
            pt_enum = ProviderType(snap_provider_type)
        except ValueError:
            logger.warning(
                "snapshot.invalid_provider_type_fallback",
                node_id=str(context.node_id),
                snapshot_provider_type=snap_provider_type,
            )
            return await self._resolve_api_key_and_model(
                project,
                config_model=config_model,
                use_custom_api=False,
                api_base_url=api_base_url,
                api_key=api_key,
                provider_type=provider_type,
                provider_credential_id=provider_credential_id,
            )

        # 加载凭证 api_key / base_url（contract snapshot 仅存 credential_id，不存 api_key）
        snap_api_key = ""
        snap_base_url = ""
        from services.provider_config import PROVIDER_REGISTRY

        if snap_credential_id_raw:
            from uuid import UUID

            from system.models import ProviderCredential

            try:
                cred = await ProviderCredential.objects.aget(
                    id=UUID(str(snap_credential_id_raw)), is_active=True
                )
                raw_cfg = cred.get_decrypted_config()
                schema_cls = PROVIDER_REGISTRY[pt_enum].credential_schema
                validated = schema_cls.model_validate(raw_cfg)
                if hasattr(validated, "api_key") and validated.api_key is not None:
                    secret = validated.api_key
                    snap_api_key = (
                        secret.get_secret_value()
                        if hasattr(secret, "get_secret_value")
                        else str(secret)
                    )
                snap_base_url = (
                    getattr(validated, "base_url", "") or ""
                )
            except Exception as load_err:  # noqa: BLE001
                logger.warning(
                    "snapshot.credential_load_failed_fallback",
                    node_id=str(context.node_id),
                    credential_id=str(snap_credential_id_raw),
                    error=str(load_err),
                )
                return await self._resolve_api_key_and_model(
                    project,
                    config_model=config_model,
                    use_custom_api=False,
                    api_base_url=api_base_url,
                    api_key=api_key,
                    provider_type=provider_type,
                    provider_credential_id=provider_credential_id,
                )

        if not snap_base_url:
            snap_base_url = PROVIDER_REGISTRY[pt_enum].default_base_url

        credential_uuid = None
        if snap_credential_id_raw:
            from uuid import UUID

            try:
                credential_uuid = UUID(str(snap_credential_id_raw))
            except ValueError:
                credential_uuid = None

        resolved = ResolvedProviderConfig(
            provider_type=pt_enum,
            api_key=snap_api_key,
            base_url=snap_base_url,
            source=snap_source,
            credential_id=credential_uuid,
            extra={"from_snapshot": True},
        )

        if not snap_model:
            # snapshot model 为空且 config 也无 model → 保留 fallback 到运行时
            logger.warning(
                "snapshot.missing_model_fallback",
                node_id=str(context.node_id),
            )
            return await self._resolve_api_key_and_model(
                project,
                config_model=config_model,
                use_custom_api=False,
                api_base_url=api_base_url,
                api_key=api_key,
                provider_type=provider_type,
                provider_credential_id=provider_credential_id,
            )

        logger.info(
            "snapshot.hit_used_for_resolve",
            node_id=str(context.node_id),
            source=snap_source,
            provider_type=snap_provider_type,
        )
        return resolved, snap_model

    async def _resolve_api_key_and_model(
        self,
        project: Any,
        config_model: str = "",
        use_custom_api: bool = False,
        api_base_url: str = "",
        api_key: str = "",
        provider_type: str = "",
        provider_credential_id: str = "",
    ) -> tuple[ResolvedProviderConfig, str]:
        """四层优先级解析 Provider 凭证 + 模型（implementation contract 二元组新签名）。

        优先级：use_custom_api > provider_credential_id(节点 FK) > provider_type(节点类型)
                 > conversation > project > system。

        分歧 A（覆盖 context contract）：use_custom_api=True 路径构造临时
        ResolvedProviderConfig(source="node", extra={"custom_api": True,
        "source_detail": "node_custom_api"})；source 仍为四态 ("node")，
        不新增第 5 种枚举值（严禁 D）。

        Args:
            project: 关联的空间对象（可能为 None）。
            config_model: 节点 config.model 字段值。
            use_custom_api: 节点是否启用自定义 API 分支。
            api_base_url: 自定义 API 地址（仅 use_custom_api=True 生效）。
            api_key: 自定义 API Key（仅 use_custom_api=True 生效）。
            provider_type: 节点级 provider_type 字段（兼容老字段）。
            provider_credential_id: 节点级凭证 FK（contract，task 传真值；
                本 plan 默认空字符串保持兼容）。

        Returns:
            (resolved, model) 二元组。``resolved`` 可传给
            ``LangChainRunnerConfig.resolved`` 或 ``build_chat_model``。

        Raises:
            ValueError: 凭证缺失（ProviderMissingError 转发）或 model 未配置。
        """
        # 分支 1：自定义 API（分歧 A：source="node" + extra.custom_api=True）
        if use_custom_api and api_base_url:
            if not config_model:
                raise ValueError("使用自定义 API 时必须指定模型")
            resolved = ResolvedProviderConfig(
                provider_type=ProviderType.OPENAI_CHAT,
                api_key=api_key,
                base_url=api_base_url,
                source="node",  # 四态之一；严禁 D 守护
                credential_id=None,
                extra={"custom_api": True, "source_detail": "node_custom_api"},
            )
            return resolved, config_model

        # 分支 2：四层解析（contract Result 模式）
        node_config: dict[str, Any] = {}
        if provider_credential_id:
            node_config["provider_credential_id"] = provider_credential_id
        if provider_type:
            node_config["provider_type"] = provider_type

        result = await ProviderConfigService.aresolve_or_error(
            node_config=node_config or None,
            project=project,
        )
        if isinstance(result, ProviderMissingError):
            raise ValueError(
                f"未配置 {result.missing_provider} Provider 凭证："
                f"{result.recommended_action}"
            )
        resolved = result

        # work item API tier 安全硬化（security mitigation-01 disposition=mitigate）：
        # 节点级凭证 scope 校验，防跨 project 越权。仅当命中节点级 FK 时检查；
        # resolved.scope == "project" 且 scope_id != project.id 直接拒绝。
        # 权威路径 server/system/models.py L102（grep 已确认）。
        if resolved.source == "node" and resolved.credential_id is not None:
            from system.models import ProviderCredential

            try:
                cred = await ProviderCredential.objects.aget(id=resolved.credential_id)
            except ProviderCredential.DoesNotExist as exc:
                raise ValueError(
                    f"未配置 Provider 凭证：provider_credential_id="
                    f"{resolved.credential_id} 不存在"
                ) from exc
            space_id_str = str(project.id) if project is not None else ""
            if cred.scope == "project" and str(cred.scope_id) != space_id_str:
                raise ValueError(
                    f"未配置 {resolved.provider_type.value} Provider 凭证："
                    f"节点 provider_credential_id 指向他 space 凭证，"
                    f"已拒绝（scope 校验失败）"
                )

        # 模型 fallback（contract / contract）：config_model 为空时从 resolved.extra.default_model
        # 读取（替代 v8.1 aget_claude_config 路径）
        if config_model:
            resolved_model = config_model
        else:
            resolved_model = (resolved.extra or {}).get("default_model", "") or ""
        if not resolved_model:
            raise ValueError("未配置默认模型，请在系统设置或空间设置中配置默认模型")

        return resolved, resolved_model

    def _build_session_id(self, context: ExecutionContext) -> str:
        """Generate unique session ID: wf-{execution_id}-{node_id}."""
        return f"wf-{context.execution_id}-{context.node_id}"

    async def _ensure_agent_session(
        self,
        session_id: str,
        project: Any,
        user: Any,
        chat_id: str,
    ) -> AgentSession | None:
        """Pre-create AgentSession with chat_id for ask_user_question tool.

        Returns:
            AgentSession 实例（用于 LangChainAgentRunner usage/ToolCallLog 持久化 hooks），
            或 None（无 project/chat_id 时）。
        """
        if chat_id and project:
            session, _created = await AgentSession.objects.aupdate_or_create(
                session_id=session_id,
                defaults={
                    "space_id": project.id,
                    "user_id": user.id if user else None,
                    "status": AgentSession.Status.RUNNING,
                    "temp_data": {"chat_id": chat_id},
                },
            )
            return session
        return None

    def _enhance_system_prompt(self, system_prompt: str, session_id: str) -> str:
        """Inject session_id into system prompt for tools that need it."""
        return (
            f"{system_prompt}\n\n"
            f"[System Info]\n"
            f"- session_id: {session_id}\n"
            f"When calling tools that require session_id, always use: {session_id}"
        )

    # ===== Unified execute method =====

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """Execute the AI agent node using LangChainAgentRunner (implementation Wave)."""
        config = context.node_config

        # 1. Call hook methods
        system_prompt = self.get_system_prompt(context)
        user_prompt = self.get_user_prompt(context)
        max_iterations = self.get_max_iterations(context)

        if not user_prompt:
            return NodeResult(
                status="failed",
                error="User Prompt cannot be empty",
                next_handle="error",
            )

        try:
            # 2. Common construction
            project = await self._get_project(context)
            user = await self._get_user(context)
            session_id = self._build_session_id(context)
            chat_id = context.render_template(config.get("chat_id", ""))
            model_cfg: str = config.get("model", "")
            use_custom_api: bool = config.get("use_custom_api", False)
            api_base_url: str = config.get("api_base_url", "")
            api_key_cfg: str = config.get("api_key", "")
            provider_type_cfg: str = config.get("provider_type", "")

            logger.info(
                "agent_node_start",
                session_id=session_id,
                space_id=project.id if project else None,
                user_id=user.id if user else None,
                max_iterations=max_iterations,
                chat_id=chat_id,
                custom_api=bool(use_custom_api),  # Pitfall #8：仅布尔，不泄漏 api_key / api_base_url
            )

            agent_session = await self._ensure_agent_session(session_id, project, user, chat_id)
            enhanced_prompt = self._enhance_system_prompt(system_prompt, session_id)

            # 解析 Provider 凭证 + 模型
            # implementation contract contract/contract：优先读 ExecutionContext.node_snapshots，
            # miss 时 fallback 到运行时 aresolve（与 implementation 二元组签名兼容）
            resolved, resolved_model = await self._resolve_from_snapshot_or_runtime(
                context=context,
                project=project,
                config_model=model_cfg,
                use_custom_api=use_custom_api,
                api_base_url=api_base_url,
                api_key=api_key_cfg,
                provider_type=provider_type_cfg,
                provider_credential_id=config.get("provider_credential_id", ""),
            )

            # 工具桥接（contract + 分歧 B 覆盖 contract：None -> [] 不走全量注册表）
            hook_tool_names = self.get_enabled_tools(context)
            tool_names: list[str] = (
                hook_tool_names if hook_tool_names is not None else []
            )
            tools = build_langchain_tools(
                tool_names,
                injected_values={
                    "space_id": str(project.id) if project else "",
                    "session_id": session_id,
                },
            )

            # 3. Build and run LangChainAgentRunner（contract）
            timeout_minutes = config.get("timeout_minutes")
            timeout_seconds: float = (
                float(timeout_minutes * 60) if timeout_minutes else 600.0
            )

            # 凭证级能力解析：用户在凭证模型条目配置的 context_length 等
            # 优先于静态 fixture；无凭证/未配置时 resolver 内部回退 fixture。
            credential = None
            if resolved.credential_id is not None:
                from services.provider_config import _fetch_credential_by_id

                credential = await _fetch_credential_by_id(resolved.credential_id)
            capabilities = ModelCapabilities.resolve_for_credential(
                credential, str(resolved.provider_type), resolved_model
            )

            runner_config = LangChainRunnerConfig(
                resolved=resolved,
                model=resolved_model,
                session_id=session_id,
                max_turns=max_iterations,
                timeout_seconds=timeout_seconds,
                capabilities=capabilities,
                tools=tools,
                max_thinking_tokens=config.get("max_thinking_tokens"),
                max_output_tokens=config.get("max_output_tokens"),
                agent_session=agent_session,
            )
            runner = LangChainAgentRunner(runner_config)

            # 消费完整 stream 以获取结果（workflow 节点不需要 SSE 流式输出）
            # contract / 严禁 A：纯字符串双包装，禁 ChatPromptTemplate
            messages: list[BaseMessage] = [
                SystemMessage(content=enhanced_prompt),
                HumanMessage(content=user_prompt),
            ]
            async for _event in runner.stream(messages):
                pass

            result = runner.result
            if result is None:
                return NodeResult(
                    status="failed",
                    error="LangChainAgentRunner returned no result",
                    next_handle="error",
                )

            # 4. Result mapping
            if result.status == "suspended":
                logger.info(
                    "agent_node_suspended",
                    session_id=session_id,
                    suspension=result.metadata.get("suspension"),
                )
                return NodeResult(
                    status="waiting_event",
                    output={
                        "session_id": session_id,
                        "suspension": result.metadata.get("suspension"),
                        "partial_output": result.output,
                    },
                )

            if result.status == "completed":
                logger.info(
                    "agent_node_completed",
                    session_id=session_id,
                )
                return NodeResult(
                    status="completed",
                    output=self.map_output(result),
                    next_handle="default",
                )

            # error or other non-complete status
            error_detail = result.error or ""
            logger.warning(
                "agent_node_incomplete",
                session_id=session_id,
                status=result.status,
                error=error_detail,
            )
            error_msg = f"Agent execution incomplete: {result.status}"
            if error_detail:
                error_msg += f"\n{error_detail}"
            return NodeResult(
                status="failed",
                error=error_msg,
                next_handle="error",
            )

        except ContextWindowExceededError as e:
            # implementation contract contract：SSE ERROR 事件结构化 payload。
            # 解析 langchain_runner.py `_check_context_window` strict_error 消息格式：
            #   context too long: {N} tokens > budget {B} (max_input={I}, max_output={O}, buffer={F})
            # regex 不匹配时 fallback 到 0 值，保证 error_code / recommended_actions 仍写入。
            msg = str(e)
            m = re.match(
                r"context too long: (\d+) tokens > budget (\d+) "
                r"\(max_input=(\d+), max_output=(\d+), buffer=(\d+)\)",
                msg,
            )
            if m is not None:
                estimated = int(m.group(1))
                budget = int(m.group(2))
                # max_input / max_output / buffer 解析但暂不外暴露（contract：前端不做本地估算，max_tokens=budget）
                _ = (int(m.group(3)), int(m.group(4)), int(m.group(5)))
                exceeded = max(0, estimated - budget)
            else:
                estimated = 0
                budget = 0
                exceeded = 0
            model_name = context.node_config.get("model", "") if isinstance(context.node_config, dict) else ""
            return NodeResult(
                status="failed",
                error=msg,
                output={
                    "error_code": "context_window_exceeded",
                    "detail": msg,
                    "estimated_tokens": estimated,
                    "max_tokens": budget,
                    "exceeded_by": exceeded,
                    "model": model_name,
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
                next_handle="error",
            )
        except ValueError as e:
            msg = str(e)
            if "exceeds model limit" in msg:
                code = "max_tokens_exceeds_model_limit"
            elif "未配置" in msg and "凭证" in msg:
                code = "provider_credential_missing"
            else:
                code = "internal_error"
            return NodeResult(
                status="failed",
                error=msg,
                output={"error_code": code},
                next_handle="error",
            )
        except asyncio.CancelledError:
            return NodeResult(
                status="failed",
                error="Agent execution cancelled",
                output={"error_code": "execution_cancelled"},
                next_handle="error",
            )
        except Exception as e:
            logger.exception("agent_node_error", error=str(e))
            return NodeResult(
                status="failed",
                error=str(e),
                output={"error_code": "internal_error"},
                next_handle="error",
            )

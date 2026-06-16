"""AIPlanResearchNode —— 方案编排工作流入口节点（ENTRY-01，DOMAIN §6/§14/§17B）。

工作流入口：从节点配置/上游输入取需求建 ``PlanSession``（entrypoint=workflow），注入真实
adapters（路由/召回/调研/融合/澄清）构造 ``PlanOrchestrationEngine``，驱动 ``engine.advance``
推进「拆分→路由→召回→澄清→并行调研→融合」流水线；在 clarifying（pending clarification）/
researching（容器 fan-out 等待）处复用既有工作流 ``waiting_event`` 挂起、由 ask_user_question
卡片回路 / 容器回调 resume 续推；终态 ``done`` 输出 canonical ``MergedPlan`` 引用
（``PlanSession.current_plan_version``）、``failed`` 输出 ``NodeResult`` failed。

设计：继承 ``AIAgentBaseNode`` 复用 provider/挂起 plumbing，但 **覆盖 execute** 走 engine 推进
（不走 LangChain agent loop）。节点 config_schema + ports 即 SSOT，经 ``/api/node-types/``
自动渲染（UI reuse-first，无新 Vue 组件）。

**async ORM 防裸 lazy-FK**（规避 Phase 38 CR-01 类）：用 ``*_id`` / ``afirst`` / ``aget`` /
``aexists`` 标量，绝不裸访问同步 lazy-FK。
"""

from __future__ import annotations

from typing import Any, ClassVar

import structlog

from workflows.nodes.ai.base_agent import AIAgentBaseNode
from workflows.nodes.base import (
    ExecutionContext,
    NodePort,
    NodeResult,
    PortType,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger(__name__)

# 驱动循环最大步数（防 advance 不前进死循环，T-41-03-02）
_MAX_ADVANCE_STEPS = 20


@register_node
class AIPlanResearchNode(AIAgentBaseNode):
    """AI 方案编排调研入口节点（建 PlanSession + 注入真实 adapters 驱动 engine 端到端）。"""

    node_type: ClassVar[str] = "ai_plan_research"
    display_name: ClassVar[str] = "AI 方案编排调研"
    description: ClassVar[str] = "从需求建 PlanSession 驱动编排（拆分→路由→召回→澄清→调研→融合）产出主方案"
    icon: ClassVar[str] = "git-merge"

    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            **AIAgentBaseNode.config_schema["properties"],
            "requirement_text": {
                "type": "string",
                "title": "需求描述",
                "description": "方案编排需求文本，支持模板变量 {{nodes.ID.field}}；可由上游输入提供",
                "default": "",
            },
            "include_repos": {
                "type": "array",
                "title": "包含的仓库",
                "description": "限定路由/调研候选仓库 ID 列表（空则按 work_item 所属 project / 全库）",
                "items": {"type": "string"},
                "default": [],
            },
            "work_item_id": {
                "type": "string",
                "title": "关联工作项（可选锚）",
                "description": "关联的 WorkItem ID（INV-2：chat/自然语言需求允许为空）",
                "default": "",
            },
        },
        "required": [],
    }

    inputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="需求输入",
            port_type=PortType.OBJECT,
            required=False,
            description="上游节点输出（需求/锚），可在模板中通过 {{nodes.ID.field}} 引用",
        ),
    ]

    outputs: ClassVar[list[NodePort]] = [
        NodePort(
            name="default",
            label="主方案引用",
            port_type=PortType.OBJECT,
            description="canonical MergedPlan 引用（plan_version_id / session_id / status）",
            schema={
                "type": "object",
                "properties": {
                    "plan_version_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
        ),
        NodePort(
            name="error",
            label="错误",
            port_type=PortType.OBJECT,
            description="失败时的错误信息",
        ),
    ]

    # ===== 抽象 hook（execute 已覆盖，不走 LangChain loop；提供占位实现） =====

    def get_system_prompt(self, context: ExecutionContext) -> str:
        """execute 覆盖为 engine 驱动，不走 agent loop——占位空 prompt。"""
        return ""

    def get_user_prompt(self, context: ExecutionContext) -> str:
        """execute 覆盖为 engine 驱动，不走 agent loop——占位空 prompt。"""
        return ""

    # ===== execute：engine 驱动 =====

    async def execute(self, context: ExecutionContext) -> NodeResult:
        """建/恢复 PlanSession → 注入真实 adapters 驱动 engine.advance → 终态/挂起映射。"""
        from delivery.models import PlanSession, PlanSessionStatus

        log = logger.bind(execution_id=context.execution_id, node_id=context.node_id)

        # 1. 建/恢复 session（resume 幂等：从节点持久化输出取 session_id 重取）
        session = await self._resolve_session(context)
        if session is None:
            session = await self._create_session(context, log)
            if session is None:
                return NodeResult(
                    status="failed",
                    error="缺少需求文本（requirement_text）",
                    output={"error_code": "missing_requirement"},
                    next_handle="error",
                )

        # 2. 注入真实 adapters 构造 engine（可被测试 override）
        engine = self._build_engine(context, session)

        # 3. 驱动循环：advance + 重读 status，遇挂起条件 break 返回 waiting_event
        terminal = {PlanSessionStatus.DONE, PlanSessionStatus.FAILED}
        steps = 0
        while session.status not in terminal:
            steps += 1
            if steps > _MAX_ADVANCE_STEPS:
                log.warning("plan_research_advance_step_limit", session_id=str(session.id))
                await engine.session_service.transition(
                    session,
                    "fail",
                    error={"reason": "advance_step_limit", "steps": steps},
                )
                session = await PlanSession.objects.aget(id=session.id)
                break

            await engine.advance(session)
            session = await PlanSession.objects.aget(id=session.id)

            suspend = await self._maybe_suspend(session)
            if suspend is not None:
                log.info(
                    "plan_research_suspended",
                    session_id=str(session.id),
                    kind=suspend.output.get("kind"),
                )
                return suspend

        # 4. 终态映射
        return self._map_terminal(session)

    # ===== session 建/恢复 =====

    async def _resolve_session(self, context: ExecutionContext) -> Any:
        """resume：从节点持久化 output_data 取 session_id 重取 PlanSession（无则 None）。"""
        from delivery.models import PlanSession

        node_execution = getattr(context, "node_execution", None)
        if node_execution is None:
            return None
        output_data = getattr(node_execution, "output_data", None)
        if not isinstance(output_data, dict):
            return None
        session_id = output_data.get("session_id")
        if not session_id:
            return None
        return await PlanSession.objects.filter(id=session_id).afirst()

    async def _create_session(self, context: ExecutionContext, log: Any) -> Any:
        """首次：解析需求 + include_repos + work_item 锚 + created_by，经 service 建 session。"""
        from delivery.services import PlanSessionService

        config = context.node_config or {}
        requirement_text = context.render_template(config.get("requirement_text", "") or "")
        if not requirement_text:
            requirement_text = self._requirement_from_input(context)
        if not requirement_text:
            return None

        include_repos = config.get("include_repos", []) or []
        work_item = await self._resolve_work_item(context)
        created_by = await self._get_user(context)

        session = await PlanSessionService().create_session(
            entrypoint="workflow",
            work_item=work_item,
            decomposition={
                "requirement_text": requirement_text,
                "include_repos": include_repos,
            },
            created_by=created_by,
        )
        log.info("plan_research_session_created", session_id=str(session.id))
        return session

    @staticmethod
    def _requirement_from_input(context: ExecutionContext) -> str:
        """从上游输入回退取需求文本（default.requirement_text / requirement_text / text）。"""
        data = context.input_data if isinstance(context.input_data, dict) else {}
        for key in ("requirement_text", "text", "requirement"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        default = data.get("default")
        if isinstance(default, dict):
            for key in ("requirement_text", "text", "requirement"):
                value = default.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return ""

    async def _resolve_work_item(self, context: ExecutionContext) -> Any:
        """解析 work_item 锚（可空，INV-2）；by id 不裸 lazy-FK。"""
        work_item_id = (context.node_config or {}).get("work_item_id", "") or ""
        if not work_item_id:
            return None
        from delivery.models import WorkItem

        return await WorkItem.objects.filter(id=work_item_id).afirst()

    # ===== engine 构造（测试可 override） =====

    def _build_engine(self, context: ExecutionContext, session: Any) -> Any:
        """注入真实 adapters 构造 PlanOrchestrationEngine（生产默认；测试可 monkeypatch override）。"""
        from delivery.services import PlanSessionService
        from services.plan_orchestration import (
            ArchitectMergeAdapter,
            ClarifyAdapter,
            DeliveryKnowledgeRecallAdapter,
            PlanOrchestrationEngine,
            RepoRouterV2Adapter,
            ResearchDispatchAdapter,
        )

        # CR-02：把本节点 NodeExecution id 透传给调研 dispatch——每个调研 SubAgentSession
        # 据此关联 node_execution，容器完成回调经既有 _schedule_workflow_resume 重新驱动
        # 本挂起节点（researching→merging→done），打通 researching 段 waiting_event 的
        # resume 通路（mirror AICodingNode node_execution_id 注入）。
        node_execution = getattr(context, "node_execution", None)
        node_execution_id = str(node_execution.id) if node_execution is not None else ""

        return PlanOrchestrationEngine(
            session_service=PlanSessionService(),
            router=RepoRouterV2Adapter(),
            recall=DeliveryKnowledgeRecallAdapter(),
            research=ResearchDispatchAdapter(node_execution_id=node_execution_id),
            merge=ArchitectMergeAdapter(),
            clarify=ClarifyAdapter(),
        )

    # ===== 挂起判定 =====

    async def _maybe_suspend(self, session: Any) -> NodeResult | None:
        """clarifying（pending clarification）/ researching（在途调研）处返回 waiting_event。"""
        from delivery.models import Clarification, PlanSessionStatus
        from services.plan_orchestration import aall_research_tasks_terminal

        if session.status == PlanSessionStatus.CLARIFYING:
            pending = await (
                Clarification.objects.filter(
                    session_id=session.id, answered_at__isnull=True
                )
                .values("id", "question")
                .afirst()
            )
            if pending is not None:
                return NodeResult(
                    status="waiting_event",
                    output={
                        "session_id": str(session.id),
                        "kind": "clarification",
                        "suspension": {
                            "type": "ask_user_question",
                            "clarification_id": str(pending["id"]),
                            "question": pending["question"],
                        },
                    },
                )

        if session.status == PlanSessionStatus.RESEARCHING:
            terminal = await aall_research_tasks_terminal(session.id)
            if not terminal:
                return NodeResult(
                    status="waiting_event",
                    output={
                        "session_id": str(session.id),
                        "kind": "research",
                        "_resume_from_callback": True,
                    },
                )
        return None

    # ===== 终态映射 =====

    def _map_terminal(self, session: Any) -> NodeResult:
        """done → completed（canonical plan_version_id）；failed → failed（error_code）。"""
        from delivery.models import PlanSessionStatus

        if session.status == PlanSessionStatus.DONE:
            return NodeResult(
                status="completed",
                output={
                    "session_id": str(session.id),
                    "plan_version_id": (
                        str(session.current_plan_version)
                        if session.current_plan_version
                        else None
                    ),
                    "status": "done",
                },
                next_handle="default",
            )
        error = session.error if isinstance(session.error, dict) else {}
        return NodeResult(
            status="failed",
            error=str(error.get("message") or error.get("reason") or "plan session failed"),
            output={
                "session_id": str(session.id),
                "error_code": "plan_session_failed",
                "error": error,
            },
            next_handle="error",
        )

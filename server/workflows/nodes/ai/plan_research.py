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

**D2 产物迁移（点3）**：经典路径 ``ai_plan_generation`` 产出顶层平铺的 ``TechnicalPlan``
JSON；本编排路径产出 canonical ``PlanVersion``（``PlanSession.current_plan_version``）。为让
下游 ``human_approval(mode=plan_feishu)`` 与 ``ai_coding`` 无改造即可消费，``done`` 终态在
``default`` 输出端口同时携带：
- 引用三元组 ``session_id`` / ``plan_version_id`` / ``status``（供回溯与 wave 接线）；
- ``plan``：``PlanVersion.content``（§7 MergedPlan，含 ``execution_plan`` 等），并把
  ``plan_version_id`` 注入其中——下游 ``ai_coding`` 据 ``plan.plan_version_id`` 解析 canonical
  ``PlanVersion`` 进入 wave 模式（多仓多 agent fan-out）。

**D2 上游输入 vs 驳回回流 二义性（点4，契约冻结，禁改）**：本节点的「续推已存在 session」
与「首次按需求建 session」是两条**物理隔离**的通道，不得混淆：
1. **续推通道（resume）= 本节点自身 ``NodeExecution.output_data["session_id"]``**。
   仅 clarifying / researching 挂起时由本节点写入；resume 时 ``_resolve_session`` 据此重取
   **同一** ``PlanSession`` 续推。resume **绝不读取 ``default`` 输入端口的需求**。
2. **首建通道（first-run）= 节点配置 ``requirement_text`` ∪ ``default`` 输入端口**。
   仅当续推通道为空（无 session_id）时才走 ``_create_session``。
3. **驳回回流（rejection）**：``human_approval(rejected)`` 经 ``reject_reason`` 显式字段沿
   ``rejected`` 出边回流；模板 ``plan_approval --rejected--> generate_plan`` 是**反馈环
   back-edge**，引擎按 back-edge 处理（已 COMPLETED 的生成节点不自动重跑），故驳回为
   「干净止于审批、不进编码」的 HITL 终止，**不死锁**。多轮方案修订由编排引擎自身的澄清/
   融合重试回路（session 内 suspend/resume）承担，**不**借模板 back-edge 把驳回反馈当成
   首次需求重新建 session（这正是点4 要消解的二义性）。

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
            description=(
                "canonical MergedPlan 引用（plan_version_id / session_id / status）+ "
                "内联 §7 MergedPlan content（plan，供下游审批/编码节点直接消费）"
            ),
            schema={
                "type": "object",
                "properties": {
                    "plan_version_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "status": {"type": "string"},
                    # D2 产物迁移：内联 PlanVersion.content（§7 MergedPlan），下游
                    # human_approval(plan_feishu) / ai_coding 经 get_input("plan") 直接消费。
                    "plan": {"type": "object"},
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
        from services.plan_orchestration import (
            adrive_plan_session_to_pause_or_terminal,
        )

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

        # 3. 复用 43-02 共享续驱 helper（不造两套循环）：advance 至「重挂起短路点」
        #    （clarifying-未答 / researching-在途）或终态 {DONE, FAILED}；step 上限由 helper
        #    内部经 transition(fail) fail-soft 退出。行为等价于原内联循环。
        session = await adrive_plan_session_to_pause_or_terminal(
            engine, session, max_steps=_MAX_ADVANCE_STEPS
        )

        # 4. 入口私有挂起 marker 映射（保留）：helper 短路返回后再判一次，clarifying-pending /
        #    researching-在途 处返回工作流 waiting_event marker。
        suspend = await self._maybe_suspend(session)
        if suspend is not None:
            log.info(
                "plan_research_suspended",
                session_id=str(session.id),
                kind=suspend.output.get("kind"),
            )
            return suspend

        # 5. 终态映射
        return await self._map_terminal(session)

    # ===== session 建/恢复 =====

    async def _resolve_session(self, context: ExecutionContext) -> Any:
        """续推通道（点4 契约）：仅从**本节点自身** ``NodeExecution.output_data["session_id"]``
        重取 ``PlanSession`` 续推（clarifying / researching 挂起时写入）；无则 None。

        **绝不读取 ``default`` 输入端口**——续推与首建物理隔离，杜绝把驳回反馈/上游输入
        当成续推钥匙的二义性。session_id 存在即续推同一 session，``requirement_text`` /
        上游输入在 resume 路径被完全忽略（见 ``execute`` 的 resolve-先于-create 短路）。
        """
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
        """首建通道（点4 契约）：解析需求 + include_repos + work_item 锚 + created_by，经共享
        helper 建 session。

        **仅当续推通道（_resolve_session）为空时**才被调用——首次需求来源限定为节点配置
        ``requirement_text`` 与 ``default`` 输入端口回退，绝不与续推 session_id 混用。
        """
        from services.plan_orchestration import start_orchestration

        config = context.node_config or {}
        requirement_text = context.render_template(config.get("requirement_text", "") or "")
        if not requirement_text:
            requirement_text = self._requirement_from_input(context)
        if not requirement_text:
            return None

        include_repos = self._resolve_include_repos(context)
        work_item = await self._resolve_work_item(context)
        created_by = await self._get_user(context)

        # 复用两入口共用的薄 helper（底层 engine 复用、不造两套）；entrypoint 仍为 workflow、
        # decomposition 形态不变 → 行为零变更。
        session = await start_orchestration(
            entrypoint="workflow",
            requirement_text=requirement_text,
            work_item=work_item,
            created_by=created_by,
            include_repos=include_repos,
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

    @staticmethod
    def _resolve_include_repos(context: ExecutionContext) -> list[str]:
        """解析候选仓 ID 列表（支持模板变量 {{...}}，逐项渲染 + 去空白/空项）。"""
        raw = (context.node_config or {}).get("include_repos", []) or []
        if not isinstance(raw, list):
            return []
        resolved: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                continue
            rendered = context.render_template(item).strip()
            if rendered:
                resolved.append(rendered)
        return resolved

    async def _resolve_work_item(self, context: ExecutionContext) -> Any:
        """解析 work_item 锚（可空，INV-2）；支持模板变量渲染，by id 不裸 lazy-FK。"""
        raw = (context.node_config or {}).get("work_item_id", "") or ""
        work_item_id = context.render_template(raw).strip() if raw else ""
        if not work_item_id:
            return None
        from delivery.models import WorkItem

        return await WorkItem.objects.filter(id=work_item_id).afirst()

    # ===== engine 构造（测试可 override） =====

    def _build_engine(self, context: ExecutionContext, session: Any) -> Any:
        """经共享 helper 注入真实 adapters 构造 engine（生产默认；测试可 monkeypatch override）。"""
        from services.plan_orchestration import build_orchestration_engine

        # CR-02：把本节点 NodeExecution id 透传给调研 dispatch——每个调研 SubAgentSession
        # 据此关联 node_execution，容器完成回调经既有 _schedule_workflow_resume 重新驱动
        # 本挂起节点（researching→merging→done），打通 researching 段 waiting_event 的
        # resume 通路（mirror AICodingNode node_execution_id 注入）。chat 入口不传（走既有
        # deep_analysis resume），故仅工作流入口在此透传 node_execution_id。
        node_execution = getattr(context, "node_execution", None)
        node_execution_id = str(node_execution.id) if node_execution is not None else ""

        return build_orchestration_engine(node_execution_id=node_execution_id)

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

    async def _map_terminal(self, session: Any) -> NodeResult:
        """done → completed（canonical plan_version_id + 内联 §7 MergedPlan content）；
        failed → failed（error_code）。

        D2 产物迁移（点3）：done 终态加载 ``PlanVersion.content`` 内联为 ``plan``，并把
        ``plan_version_id`` 注入其中——下游 ``human_approval(plan_feishu)`` 经 ``plan.summary``
        / ``plan.execution_plan`` 落审批文档；``ai_coding`` 经 ``plan.plan_version_id`` 解析
        canonical ``PlanVersion`` 进入 wave 模式（多仓多 agent fan-out）。
        """
        from delivery.models import PlanSessionStatus, PlanVersion

        if session.status == PlanSessionStatus.DONE:
            pv_id = (
                str(session.current_plan_version) if session.current_plan_version else None
            )
            plan_content: dict[str, Any] = {}
            if pv_id:
                pv = await PlanVersion.objects.filter(id=pv_id).afirst()
                if pv is not None and isinstance(pv.content, dict):
                    # 注入 plan_version_id 供下游 ai_coding 解析 canonical PlanVersion 进 wave 模式
                    plan_content = {**pv.content, "plan_version_id": pv_id}
            return NodeResult(
                status="completed",
                output={
                    "session_id": str(session.id),
                    "plan_version_id": pv_id,
                    "status": "done",
                    "plan": plan_content,
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

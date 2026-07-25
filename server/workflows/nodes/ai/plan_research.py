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
    description: ClassVar[str] = (
        "从需求建 PlanSession 驱动编排（拆分→路由→召回→澄清→调研→融合）产出主方案"
    )
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
        # SLOT-02：澄清回流「插槽端口」声明（凸点，shape=clarification_answer）——供编辑器
        # 形状磁吸（Phase 93）+ WorkflowGraphValidator 契约兼容识别（92-01）。**仅端口声明**：
        # execute 运行时不读取本端口（resume 续推钥匙仍是节点自身 output_data.session_id，
        # 见类 docstring 点4 契约 + Pitfall 5）。default 端口逐字保留、shape 恒空（通配）。
        NodePort(
            name="resume",
            label="澄清答复",
            port_type=PortType.OBJECT,
            required=False,
            shape="clarification_answer",
            description="回流澄清答案续推（凸点）",
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
                    "artifact_version_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "status": {"type": "string"},
                    # D2 产物迁移：内联 PlanVersion.content（§7 MergedPlan），下游
                    # human_approval(plan_feishu) / ai_coding 经 get_input("plan") 直接消费。
                    "plan": {"type": "object"},
                    # UNIFY-06：done 出口干净结构化 markdown（render_merged_plan_markdown
                    # 结果，不 dump LLM 原文），供模板 {{nodes.X.plan_markdown}} 引用推群；
                    # 声明该字段以规避 Pitfall 1 field_not_found（technical_plan_generation
                    # 模板引用依赖此 schema 声明）。
                    "plan_markdown": {"type": "string"},
                },
            },
        ),
        # SLOT-02：澄清请求「插槽端口」声明（凹槽，shape=clarification_request）——需澄清时
        # 在编辑器侧吐出澄清请求供形状磁吸（Phase 93）+ validator 契约识别（92-01）。**仅端口
        # 声明**：execute / _map_terminal / _maybe_suspend 不经本 handle 路由（NodeResult.next_handle
        # 仍只走 default/error；91 发卡逻辑在 _maybe_suspend/_send_clarify_card，不依赖 clarify
        # handle，见 Pitfall 5 / A4）。default/error 生产端口逐字保留、shape 恒空（保「空契约=通配」
        # 零回归，不拦截既有 plan→coding 边）。
        NodePort(
            name="clarify",
            label="澄清请求",
            port_type=PortType.OBJECT,
            shape="clarification_request",
            description="需澄清时吐出澄清请求（凹槽）",
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
        from services.process_runtime import (
            adrive_convergence_session_to_pause_or_terminal,
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
        session = await adrive_convergence_session_to_pause_or_terminal(
            engine, session, max_steps=_MAX_ADVANCE_STEPS
        )

        # 4. 入口私有挂起 marker 映射（保留）：helper 短路返回后再判一次，clarifying-pending /
        #    researching-在途 处返回工作流 waiting_event marker。
        suspend = await self._maybe_suspend(session, context)
        if suspend is not None:
            log.info(
                "plan_research_suspended",
                session_id=str(session.id),
                kind=suspend.output.get("kind"),
            )
            return suspend

        # 5. 终态映射
        result = await self._map_terminal(session)

        # 6. INGEST-01（14-04）：方案产出成功 → 投递统一摄取（只投 ID，零取材）。
        #    Chassis v2 删除 ai_plan_generation 时漏搬了生成侧接线：审批侧
        #    （scheduler.approve_node）已把本节点列为方案生成源，normalizer
        #    （knowledge/sources/workflow_plan.py）也统一读 output_data["plan"]，
        #    唯独 workflow_plan_generated 无人投递。此处补回，两侧重新对称。
        if result.status == "completed":
            await self._schedule_plan_ingestion(context)

        return result

    @staticmethod
    async def _schedule_plan_ingestion(context: ExecutionContext) -> None:
        """投递 workflow_plan_generated（aschedule_ingestion 内部吞异常，不包 try/except）。"""
        from knowledge import ingestion  # lazy import 防循环

        execution = context.workflow_execution
        triggered_by_id = getattr(execution, "triggered_by_id", None) if execution else None
        await ingestion.aschedule_ingestion(
            ingestion.IngestionRequest(
                "workflow_plan",
                f"{context.execution_id}:{context.node_id}",
                "workflow_plan_generated",
            ),
            initiated_by_user_id=str(triggered_by_id) if triggered_by_id else None,
        )

    # ===== session 建/恢复 =====

    async def _resolve_session(self, context: ExecutionContext) -> Any:
        """续推通道（点4 契约）：仅从**本节点自身** ``NodeExecution.output_data["session_id"]``
        重取 ``PlanSession`` 续推（clarifying / researching 挂起时写入）；无则 None。

        **绝不读取 ``default`` 输入端口**——续推与首建物理隔离，杜绝把驳回反馈/上游输入
        当成续推钥匙的二义性。session_id 存在即续推同一 session，``requirement_text`` /
        上游输入在 resume 路径被完全忽略（见 ``execute`` 的 resolve-先于-create 短路）。
        """
        from delivery.models import ConvergenceSession as PlanSession

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
        from services.process_runtime import start_orchestration

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
        from services.process_runtime import build_orchestration_engine

        # CR-02：把本节点 NodeExecution id 透传给调研 dispatch——每个调研 SubAgentSession
        # 据此关联 node_execution，容器完成回调经既有 _schedule_workflow_resume 重新驱动
        # 本挂起节点（researching→merging→done），打通 researching 段 waiting_event 的
        # resume 通路（mirror AICodingNode node_execution_id 注入）。chat 入口不传（走既有
        # deep_analysis resume），故仅工作流入口在此透传 node_execution_id。
        node_execution = getattr(context, "node_execution", None)
        node_execution_id = str(node_execution.id) if node_execution is not None else ""

        return build_orchestration_engine(node_execution_id=node_execution_id)

    # ===== 挂起判定 =====

    async def _maybe_suspend(self, session: Any, context: ExecutionContext) -> NodeResult | None:
        """clarifying（pending clarification）/ researching（在途调研）处返回 waiting_event。

        CLARIFY-05：工作流入口（有 ``workflow_execution`` / ``node_execution``）在 CLARIFYING
        挂起时发飞书澄清交互卡到项目群 + 建 ``WorkflowEventSubscription(PlanClarifyCallback)``
        超时兜底（mirror ``plan_deepen``）；chat 入口（无 execution）不发卡（走 91-04 会话出口面）。
        """
        from datetime import timedelta

        from django.utils import timezone

        from delivery.models import Clarification, ConvergenceSessionStatus
        from delivery.services.clarification_service import ClarificationService
        from services.process_runtime import aall_research_tasks_terminal
        from workflows.models.execution import WorkflowEventSubscription

        if session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION:
            # WR-03：存在性判定收口 `ahas_pending`（结构化子题轮不误判：容器 answered_at 仍空
            # 但子题已答 / 反之）；取问题内容仍用显式查询（分工：判存在用谓词、取内容用查询）。
            if not await ClarificationService().ahas_pending(session.id):
                pending = None
            else:
                pending = await (
                    Clarification.objects.filter(session_id=session.id, answered_at__isnull=True)
                    .order_by("round_no", "created_at")
                    .values("id", "question")
                    .afirst()
                )
            if pending is not None:
                clarification_id = str(pending["id"])
                # CLARIFY-05：仅工作流入口发卡 + 订阅（chat 入口走 91-04 会话出口面）。
                if context.workflow_execution and context.node_execution:
                    await self._send_clarify_card(session, context, clarification_id)
                    await WorkflowEventSubscription.objects.acreate(
                        workflow_execution=context.workflow_execution,
                        node_execution=context.node_execution,
                        event_type="PlanClarifyCallback",
                        project_key=context.workflow_context.get("project_key", ""),
                        timeout_at=timezone.now() + timedelta(minutes=60),
                        timeout_action="fail",
                    )
                return NodeResult(
                    status="waiting_event",
                    output={
                        "session_id": str(session.id),
                        "kind": "clarification",
                        "suspension": {
                            "type": "ask_user_question",
                            "clarification_id": clarification_id,
                            "question": pending["question"],
                        },
                    },
                )

        if session.status == ConvergenceSessionStatus.WAITING_EVENT:
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

    # ===== CLARIFY-05 发卡（工作流入口，mirror plan_deepen._send_clarify_card） =====

    async def _send_clarify_card(
        self, session: Any, context: ExecutionContext, clarification_id: str
    ) -> None:
        """发澄清交互卡到项目群（best-effort，绝不反噬挂起）。

        取 pending 轮子题（按 ``order``，与回调侧 91-03 枚举顺序一致）→ 复用
        ``build_clarification_card``（携 ``clarification_id``）→ 解析项目群（mirror
        ``plan_deepen._asend_card``）→ ``FeishuIMService.send_card``。卡片正文经
        ``redact_secrets_in_text`` 脱敏（T-91-02-02）；触发用户带 ``initiated_by_user_id``
        （T-91-02-03）；全程 try/except 失败仅 log（T-91-02-05）。
        """
        from delivery.models import Clarification
        from feishu.cards.chat_question_card import build_clarification_card
        from initiatives.services.project_service import ProjectService
        from services.feishu_im import FeishuIMService
        from workflows.nodes.integrations.board_split_review import (
            _aresolve_project,
            _resolve_space,
        )

        log = logger.bind(
            execution_id=context.execution_id,
            node_id=context.node_id,
            component="plan_research",
            category="caller",
        )
        try:
            questions = await self._acollect_round_questions(clarification_id)
            if not questions:
                return
            round_meta = await (
                Clarification.objects.filter(id=clarification_id).values("round_no").afirst()
            )
            space = await _resolve_space(context)
            if space is None:
                return
            project = await _aresolve_project(space)
            if project is None:
                return
            initiated_by_user_id = self._resolve_initiator(context)
            chat_id = await ProjectService().resolve_or_create_group(
                project=project,
                member_ids=[],
                initiated_by_user_id=initiated_by_user_id,
            )
            if not chat_id:
                return
            card = build_clarification_card(
                questions,
                execution_id=context.execution_id,
                node_id=context.node_id,
                clarification_id=clarification_id,
                round_no=(round_meta or {}).get("round_no") or 1,
            )
            im_service = await FeishuIMService.create(space)
            await im_service.send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)
        except Exception:  # noqa: BLE001 — 发卡 best-effort，绝不反噬挂起
            log.warning("plan_research_clarify_card_failed", session_id=str(session.id))

    @staticmethod
    async def _acollect_round_questions(clarification_id: str) -> list[dict[str, Any]]:
        """取该轮**整轮**子题（按 ``order``），组装发卡用 questions，正文脱敏。

        WARNING #3 不变量：整轮按 ``order`` 取（**不按 answered_at 过滤**），与回调侧
        ``plan_clarify_callback._acollect_round_questions`` 枚举顺序逐字一致——索引 ``i`` ↔
        第 ``i`` 个子题固定不随「同一轮部分已答后重发」漂移，杜绝 ``q{i}`` ↔ question_id 错位。
        """
        from common.logging import redact_secrets_in_text
        from delivery.models import ClarificationQuestion

        questions: list[dict[str, Any]] = []
        async for q in (
            ClarificationQuestion.objects.filter(clarification_id=clarification_id)
            .order_by("order")
            .values("question", "qtype", "options", "recommended")
        ):
            questions.append(
                {
                    "question": redact_secrets_in_text(str(q.get("question") or "")),
                    "type": q.get("qtype") or "single",
                    "options": q.get("options") or [],
                    "recommended": q.get("recommended") or [],
                }
            )
        return questions

    @staticmethod
    def _resolve_initiator(context: ExecutionContext) -> str:
        """取工作流触发用户 id（缺记 system，观测约束：后台/外部触发带 initiated_by_user_id）。"""
        execution = context.workflow_execution
        if execution is not None:
            triggered_by_id = getattr(execution, "triggered_by_id", None)
            if triggered_by_id:
                return str(triggered_by_id)
        return "system"

    # ===== 终态映射 =====

    async def _map_terminal(self, session: Any) -> NodeResult:
        """done → completed（canonical plan_version_id + 内联 §7 MergedPlan content）；
        failed → failed（error_code）。

        D2 产物迁移（点3）：done 终态加载 ``PlanVersion.content`` 内联为 ``plan``，并把
        ``plan_version_id`` 注入其中——下游 ``human_approval(plan_feishu)`` 经 ``plan.summary``
        / ``plan.execution_plan`` 落审批文档；``ai_coding`` 经 ``plan.plan_version_id`` 解析
        canonical ``PlanVersion`` 进入 wave 模式（多仓多 agent fan-out）。
        """
        from delivery.models import ArtifactVersion, ConvergenceSessionStatus
        from services.process_runtime import render_merged_plan_markdown

        if session.status == ConvergenceSessionStatus.DONE:
            av_id = (
                str(session.current_artifact_version_id)
                if session.current_artifact_version_id
                else None
            )
            plan_content: dict[str, Any] = {}
            # done 出口干净结构化 markdown（仅消费 technical_plan ArtifactVersion content）；
            # content 缺失/非 dict 时为空串。
            plan_markdown = ""
            if av_id:
                av = await ArtifactVersion.objects.filter(id=av_id).afirst()
                if av is not None and isinstance(av.content, dict):
                    # 注入 artifact_version_id 供下游 ai_coding 解析产物进 wave 模式
                    plan_content = {**av.content, "artifact_version_id": av_id}
                    plan_markdown = render_merged_plan_markdown(av.content)
            return NodeResult(
                status="completed",
                output={
                    "session_id": str(session.id),
                    "artifact_version_id": av_id,
                    "status": "done",
                    "plan": plan_content,
                    "plan_markdown": plan_markdown,
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

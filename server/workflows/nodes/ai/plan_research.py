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

from typing import Any, ClassVar, Final

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

# 澄清卡送达失败原因受控闭集（RELY-02）。事件 payload 只带这几个枚举值，绝不带上游
# 响应体或异常原文——排障原文只进系统日志（已脱敏），不进可外读的事件 payload。
_DELIVERY_FAILURE_REASONS: Final[frozenset[str]] = frozenset(
    {"no_questions", "no_space", "no_project", "no_chat_id", "send_failed"}
)

# ── 蓝图分档用的状态字面量（同步点 2 / G1）─────────────────────────────────────
#
# 用字面量而非 ``BlueprintStatus.*``：本模块所有 delivery 模型 import 都在函数内（lazy），
# 模块级常量拿不到那个枚举（与 ``blueprint_resume`` 同口径）。等值由
# ``tests/workflows/test_plan_research_blueprint_seam.py`` 的枚举对齐断言锁死。
_BLUEPRINT_STATUS_NEEDS_CLARIFICATION: Final[str] = "needs_clarification"
_BLUEPRINT_STATUS_PENDING_REVIEW: Final[str] = "pending_review"
_BLUEPRINT_STATUS_FAILED: Final[str] = "failed"

# ⭐ 「已过人审」的状态集：只有落在这里面的蓝图才允许沿 default 出边把载荷交给下游
# ``ai_coding``（RELY-01）。``pending_review`` **刻意不在集合内** —— 那正是「等人审」。
_BLUEPRINT_REVIEWED_STATUSES: Final[frozenset[str]] = frozenset(
    {"confirmed", "implementing", "implemented"}
)

# 蓝图挂起的**超时兜底**订阅事件类型（⛔ 不是唤醒通路，唤醒走作答链重入）。取独立值
# 确保既有 ``PlanClarifyCallback`` 消费者必不命中它。
_BLUEPRINT_GATE_EVENT_TYPE: Final[str] = "BlueprintGateCallback"

# ⭐ 蓝图节点输出的**判别键取值**（同步点 2 收尾，前端触点 `NodeDataTab.vue` 消费）。
#
# 蓝图与 v0 旧链的节点输出**共用同一个 node_type**（``ai_plan_research``），键集又高度
# 相似（都有 ``session_id`` / ``plan`` / ``plan_markdown``）⇒ 执行抽屉此前把蓝图输出当
# v0 渲染，看不出这是一份需要人审的结构化蓝图。本键让判别变成**结构性**的：调用方拿它
# 与 ``blueprint/v1`` 严格比较即可，口径与 ``delivery/artifacts/builtin_types.py`` 逐字相同。
#
# ⛔ 只在**蓝图分支**写这个键 —— v0 四个分支一字未动，输出逐字节不变。
# 字面量而非 import：本模块 delivery / process_runtime 的 import 全在函数内（lazy）；
# 等值由 ``tests/workflows/test_plan_research_blueprint_seam.py`` 的常量对齐断言锁死。
_BLUEPRINT_SCHEMA_VERSION: Final[str] = "blueprint/v1"


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
        log = logger.bind(execution_id=context.execution_id, node_id=context.node_id)

        # 1. 建/恢复 session（resume 幂等：从节点持久化输出取 session_id 重取）
        session = await self._resolve_session(context)
        if session is None:
            session = await self._create_session(context, log)
            # 116-03：蓝图分支推不出 meta.project_id ⇒ _create_session 直接回一个失败
            # NodeResult（⛔ 不建 session、不建 artifact），此处如实透出走 error 出边。
            if isinstance(session, NodeResult):
                return session
            if session is None:
                return NodeResult(
                    status="failed",
                    error="缺少需求文本（requirement_text）",
                    output={"error_code": "missing_requirement"},
                    next_handle="error",
                )
            # 31u 首驱入队：**仅对本次新建的蓝图会话**跳过内联 adrive——首驱在请求 /
            # 引擎线程内联跑，进程被杀即丢推进（116 队列化收尾）。resume 路径（上方
            # _resolve_session 命中）与旧链 start_orchestration 分支逐字不动。
            # 入队失败降级为 None → 继续走下方内联驱动，保证不比现状差。
            enqueued = await self._amaybe_enqueue_blueprint_first_drive(session, context, log)
            if enqueued is not None:
                return enqueued

        # 2. 注入真实 adapters 构造 engine + 取该会话对应的 driver（可被测试 override）
        engine, adrive = self._build_engine(context, session)

        # 3. 复用 43-02 共享续驱 helper（不造两套循环）：advance 至「重挂起短路点」
        #    （clarifying-未答 / researching-在途）或终态 {DONE, FAILED}；step 上限由 helper
        #    内部经 transition(fail) fail-soft 退出。行为等价于原内联循环。
        #    ⭐ driver 与 engine 一起来自分派器（116-03）：只换 engine 不换 driver 会把健康的
        #    蓝图会话推到 max_steps 落 advance_step_limit FAILED（116-01 已实测背书）。
        session = await adrive(engine, session, max_steps=_MAX_ADVANCE_STEPS)

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

        # 5. 终态映射。⭐ 蓝图会话走独立分档（同步点 2）：蓝图的 DONE 语义是「等人审」，
        #    ``_map_terminal`` 把它当 completed 就等于让编码代理拿着**未经人审**的蓝图去
        #    建分支写代码，正面违反 RELY-01（T-116-18）。⛔ 分流写在这里而不是插进
        #    ``_map_terminal``，旧链那条路径因此逐字不变。
        from services.process_runtime.blueprint_observation import is_blueprint_session

        if is_blueprint_session(session):
            result = await self._amap_terminal_blueprint(session, context)
        else:
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

        返回值**三态**（116-03）：``ConvergenceSession``（建成）/ ``None``（缺需求，由
        ``execute`` 映射成既有的 ``missing_requirement`` 失败）/ ``NodeResult``（蓝图分支
        推不出 ``meta.project_id``，如实回错且**不建 session、不建 artifact**）。
        """
        from services.process_runtime import start_orchestration
        from services.process_runtime.blueprint_entry_switch import (
            aresolve_entry_process_type,
        )

        config = context.node_config or {}
        requirement_text = context.render_template(config.get("requirement_text", "") or "")
        if not requirement_text:
            requirement_text = self._requirement_from_input(context)
        if not requirement_text:
            return None

        include_repos = self._resolve_include_repos(context)
        work_item = await self._resolve_work_item(context)
        created_by = await self._get_user(context)

        # 116-03：按 per-entry 运行时开关分派该建哪条 process。
        # ⛔ 实参必须是**字面量常量**，绝不写 session.entrypoint —— MCP 入口记的 entrypoint
        # 实测就是 "workflow"（既有约定），反推会让「只打开 workflow 键」把 MCP 一起切走。
        if await aresolve_entry_process_type("workflow") == "technical_blueprint":
            return await self._acreate_blueprint_session(
                context=context,
                log=log,
                requirement_text=requirement_text,
                include_repos=include_repos,
                work_item=work_item,
                created_by=created_by,
            )

        # 复用两入口共用的薄 helper（底层 engine 复用、不造两套）；entrypoint 仍为 workflow、
        # decomposition 形态不变 → 行为零变更。
        session = await start_orchestration(
            entrypoint="workflow",
            requirement_text=requirement_text,
            work_item=work_item,
            created_by=created_by,
            include_repos=include_repos,
            entry_key="workflow",
        )
        log.info("plan_research_session_created", session_id=str(session.id))
        return session

    async def _acreate_blueprint_session(
        self,
        *,
        context: ExecutionContext,
        log: Any,
        requirement_text: str,
        include_repos: list[str],
        work_item: Any,
        created_by: Any,
    ) -> Any:
        """workflow 入口的蓝图路径：先定 ``meta.project_id``，再建 ``technical_blueprint`` 会话。

        ⭐ **``project_id`` 推不出即拒绝发起**：它是全链范围闸 / 图谱 space 归属 / 导出可用性
        的唯一来源，写错即三条防线同时失效**且不报错**。故推导失败时回一个 ``error`` 出边的
        失败 ``NodeResult``（⛔ 不建 session、不建 artifact），detail 取 intake 的中性文案。

        推导链：工作流关联 ``Space`` → ``blueprint_intake.aresolve_project_id``（内部过
        ``board_split_review._aresolve_project``）。⛔ 本节点不自己写第二份 Space→Project 换算。
        """
        from services.process_runtime.blueprint_intake import (
            BlueprintIntakeRejected,
            aresolve_project_id,
        )
        from services.process_runtime.entrypoint import start_blueprint_orchestration
        from workflows.nodes.integrations.board_split_review import _resolve_space

        space = await _resolve_space(context)
        try:
            project_id = await aresolve_project_id(entry="workflow", space=space)
        except BlueprintIntakeRejected as exc:
            log.warning(
                "plan_research_blueprint_rejected",
                category="caller",
                component="plan_research",
                reason=exc.reason,
            )
            return NodeResult(
                status="failed",
                error=exc.detail,
                output={"error_code": "blueprint_project_unresolved"},
                next_handle="error",
            )

        session = await start_blueprint_orchestration(
            entrypoint="workflow",
            requirement_text=requirement_text,
            work_item=work_item,
            created_by=created_by,
            include_repos=include_repos,
            project_id=project_id,
            entry_key="workflow",
        )
        log.info(
            "plan_research_blueprint_session_created",
            category="caller",
            component="plan_research",
            session_id=str(session.id),
        )
        return session

    async def _amaybe_enqueue_blueprint_first_drive(
        self, session: Any, context: ExecutionContext, log: Any
    ) -> NodeResult | None:
        """蓝图首驱入队（31u）：新建蓝图会话的首次驱动 defer 给 durable worker。

        仅 workflow 入口的**新建蓝图会话**走本分支（调用点已限定在 ``_create_session``
        成功之后）。两条明确排除（⛔ 不迁）：

        - **chat 入口**（``plan_research_tools.py``）：用户在等流式同步反馈，首驱入队
          会把对话变成无内容的空等；
        - **旧链 technical_plan**（上方 ``start_orchestration`` 分支）：调用方主动续驱、
          entry_key 退役观察中，且 ``durable_blueprint_resume`` 任务体对非 blueprint
          process 本就 no-op——没有可复用的队列化任务。

        入队与回灌闭环：defer 既有 ``durable_blueprint_resume``（复用 QUEUE_BLUEPRINT、
        ``lock=blueprint-resume-{session_id}``、⛔ 无 ``idempotency_key``——与
        ``aresume_after_gate_action`` 的入队形参逐字同构），本节点返回 ``waiting_event``
        且 ``output_data["session_id"]`` 即接通续推钥匙（``_resolve_session``）与任务体
        回灌（``_aresume_workflow_node_if_any`` 按 ``output_data__session_id`` +
        WAITING_EVENT 反查重入；节点重入后自己重新驱动 / 判挂起，本输出随后被正确的
        suspension 载荷覆盖）。

        ⚠️ **已知竞态与三层兜底**（⛔ 不为此发明新调度机制）：worker 驱完时引擎可能
        尚未把本 NodeExecution 持久化为 WAITING_EVENT ⇒ 那一次回灌 miss。兜底三层：
        ① 用户作答 / 确认门动作链（``aresume_after_gate_action``）重入；
        ② ``arecover_stalled_blueprint_sessions`` 15 分钟保险丝（对每条扫描候选重跑
        两个回灌 hook）；③ 下方超时订阅到期出口（``check_timeouts`` 兜底，没有它，
        回灌全 miss 的极端情形会无声永久挂起）。

        Returns:
            ``NodeResult(waiting_event)``（已入队）或 ``None``（非蓝图会话 / 入队失败
            降级——调用方继续内联 ``adrive``，保证不比现状差）。
        """
        from services.process_runtime.blueprint_observation import is_blueprint_session

        if not is_blueprint_session(session):
            return None

        initiated_by_user_id = self._resolve_initiator(context)
        try:
            from durable.queues import QUEUE_BLUEPRINT
            from durable.service import DurableTaskService

            job_id = await DurableTaskService.defer(
                "durable_blueprint_resume",
                {"session_id": str(session.id)},
                queue=QUEUE_BLUEPRINT,
                lock=f"blueprint-resume-{session.id}",
                initiated_by_user_id=initiated_by_user_id,
            )
        except Exception:  # noqa: BLE001 — 入队失败降级为内联驱动（不比现状差）
            log.warning(
                "plan_research_first_drive_enqueue_failed",
                category="caller",
                component="plan_research",
                initiated_by_user_id=initiated_by_user_id,
                session_id=str(session.id),
            )
            return None

        logger.info(
            "plan_research_first_drive_enqueued",
            category="caller",
            component="plan_research",
            initiated_by_user_id=initiated_by_user_id,
            session_id=str(session.id),
            job_id=str(job_id),
        )
        # 超时兜底订阅（上述第 ③ 层）：与澄清挂起同一配置键 / 同一到期出口。
        await self._asubscribe_blueprint_timeout(context, kind="clarification")
        return NodeResult(
            status="waiting_event",
            output={
                "session_id": str(session.id),
                # "clarification"/"research" 之外的新受控值：驱动尚未开始，只是已受理。
                "kind": "enqueued",
                "schema_version": _BLUEPRINT_SCHEMA_VERSION,
            },
        )

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
        """经分派器按 ``session.process_type`` 取 ``(engine, driver)`` 二元组（116-03）。

        ⭐ **返回二元组而不是单个 engine 是硬要求**（116-01 契约）：旧 driver 的
        ``waiting_clarification`` 短路判据是 ``ClarificationService.ahas_pending``，对蓝图
        会话恒 False ⇒ 只换 engine 不换 driver，健康的蓝图会话会被推到 ``max_steps`` 落
        ``advance_step_limit`` FAILED。测试可 monkeypatch override（须同样返回二元组）。
        """
        from services.process_runtime.entrypoint import build_engine_for_session

        # CR-02：把本节点 NodeExecution id 透传给调研 dispatch——每个调研 SubAgentSession
        # 据此关联 node_execution，容器完成回调经既有 _schedule_workflow_resume 重新驱动
        # 本挂起节点（researching→merging→done），打通 researching 段 waiting_event 的
        # resume 通路（mirror AICodingNode node_execution_id 注入）。chat 入口不传（走既有
        # deep_analysis resume），故仅工作流入口在此透传 node_execution_id。
        node_execution = getattr(context, "node_execution", None)
        node_execution_id = str(node_execution.id) if node_execution is not None else ""

        return build_engine_for_session(session, node_execution_id=node_execution_id)

    # ===== 挂起判定 =====

    async def _maybe_suspend(self, session: Any, context: ExecutionContext) -> NodeResult | None:
        """clarifying（pending clarification）/ researching（在途调研）处返回 waiting_event。

        CLARIFY-05：工作流入口（有 ``workflow_execution`` / ``node_execution``）在 CLARIFYING
        挂起时发飞书澄清交互卡到项目群 + 建 ``WorkflowEventSubscription(PlanClarifyCallback)``
        超时兜底（mirror ``plan_deepen``）；chat 入口（无 execution）不发卡（走 91-04 会话出口面）。

        ⭐ **蓝图会话先分流到蓝图版判据**（同步点 2，审计 §4.1 的 G1）：下面两个分支里
        ``waiting_clarification`` 那条是**旧链**判据，对蓝图会话**恒 False 且不抛异常**
        ——         ``ClarificationService.ahas_pending`` 查的是 ``Clarification`` 行，而蓝图链从不
        写它（全仓该模型的唯一写入点在 ``clarification_service.py``），
        蓝图侧写的是 ``BlueprintThread``。⇒ 一条正在等用户回答规格门提问的**健康**会话会
        穿过这里返回 ``None``，落进 :meth:`_map_terminal` 的非 DONE 分支拿到
        ``status="failed"`` / ``error_code="plan_session_failed"`` / ``next_handle="error"``：
        **每一次规格门提问与每一次确认硬门都把工作流判死**。
        ⛔ 分流写成早返回而不是往下面两个分支里插条件 —— 开关关闭时旧链必须逐字不变。
        """
        from datetime import timedelta

        from django.conf import settings
        from django.utils import timezone

        from delivery.models import Clarification, ConvergenceSessionStatus
        from delivery.services.clarification_service import ClarificationService
        from services.process_runtime import aall_research_tasks_terminal
        from services.process_runtime.blueprint_observation import is_blueprint_session
        from workflows.models.execution import WorkflowEventSubscription

        if is_blueprint_session(session):
            return await self._amaybe_suspend_blueprint(session, context)

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
                    # D-4 单一超时口径：订阅超时与澄清超时读**同一个**配置键，两侧同时到期。
                    # 早先这里写死 60 分钟，而澄清侧按 24 小时判超时——第 60 分钟工作流已被
                    # check_timeouts 标 TIMEOUT，会话却仍停在 waiting_clarification，中间是
                    # 23 小时的矛盾态窗口（无声卡死的另一半成因）。
                    # 生产已有的活跃订阅行携带旧 timeout_at，本改动只影响新建订阅；存量行由
                    # 澄清超时扫描器的「workflow 已 TIMEOUT + 会话仍 waiting_clarification →
                    # 立即出口」纵深条件兜住。
                    timeout_hours = getattr(settings, "CLARIFICATION_TIMEOUT_HOURS", 24)
                    await WorkflowEventSubscription.objects.acreate(
                        workflow_execution=context.workflow_execution,
                        node_execution=context.node_execution,
                        event_type="PlanClarifyCallback",
                        project_key=context.workflow_context.get("project_key", ""),
                        timeout_at=timezone.now() + timedelta(hours=timeout_hours),
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

    # ===== 蓝图挂起判据（同步点 2 / G1；形状照 chat 的 _maybe_suspend_blueprint） =====

    async def _amaybe_suspend_blueprint(
        self,
        session: Any,
        context: ExecutionContext | None,
        *,
        force_clarification: bool = False,
    ) -> NodeResult | None:
        """蓝图会话的挂起判定（判据与 ``blueprint_resume`` 的 pause 短路**同源**）。

        两档，与 chat 的 ``plan_research_tools._maybe_suspend_blueprint`` 逐档对齐：

        1. ``waiting_clarification`` 且存在 **open + blocking** 的 ``BlueprintThread``
           （⭐ **不按 ``kind`` 过滤** —— ``ai_clarification`` 与 ``repo_confirmation``
           两类都算；只认一类会让确认门挂起的会话被判死）⇒ ``waiting_event`` 挂起。
        2. ``waiting_event`` 且仍有在途调研 ⇒ ``waiting_event`` 挂起。这一档旧链判据
           （``aall_research_tasks_terminal``）对蓝图**本来就有效**（蓝图确实建
           ``RepoResearchTask``），故逐字复用、⛔ 不另写一套。

        ``force_clarification``：终态映射的 ``needs_clarification`` 档复用第 1 档
        （同一份实现，⛔ 不复制第二份线程查询），此时会话 ``status`` 已不是
        ``waiting_clarification``。

        ⛔ **不发旧链澄清卡**：``build_clarification_card`` 携带的是 ``clarification_id``，
        回调侧 ``PlanClarifyCallback`` 按它查 ``Clarification`` 行 —— 对蓝图线程发那张卡，
        用户点了也答不进去（回调查无此行）。蓝图线程的作答面是蓝图确认门 / 审查
        REST 端点与 MCP 工具，那条链走 ``aresume_after_gate_action`` 回来重入本节点。
        """
        from delivery.models import ConvergenceSessionStatus
        from services.process_runtime import aall_research_tasks_terminal
        from services.process_runtime.blueprint_observation import ablueprint_observation

        if force_clarification or session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION:
            observation = await ablueprint_observation(session)
            if observation.is_blocked:
                thread = observation.first_thread
                await self._asubscribe_blueprint_timeout(context, kind="clarification")
                return NodeResult(
                    status="waiting_event",
                    output={
                        "session_id": str(session.id),
                        "kind": "clarification",
                        "schema_version": _BLUEPRINT_SCHEMA_VERSION,
                        "artifact_id": observation.artifact_id,
                        # ⛔ INV-6：响应/输出体键名不得出现字面 blueprint_status。
                        "current_status": observation.current_status,
                        "pending_clarifications": observation.threads,
                        "suspension": {
                            "type": "ask_user_question",
                            # 键位与旧链分支逐字一致（消费方零改动）：thread_id 占
                            # clarification_id 那一位，另以显式 thread_id 键并列。
                            "clarification_id": thread.get("thread_id", ""),
                            "thread_id": thread.get("thread_id", ""),
                            "question": thread.get("question", ""),
                        },
                    },
                )

        if session.status == ConvergenceSessionStatus.WAITING_EVENT:
            if not await aall_research_tasks_terminal(session.id):
                return NodeResult(
                    status="waiting_event",
                    output={
                        "session_id": str(session.id),
                        "kind": "research",
                        # 这一档的判据虽与旧链同源，输出仍要如实标明是蓝图会话 ——
                        # 否则「调研在途」的抽屉画面在两条链上完全无法区分。
                        "schema_version": _BLUEPRINT_SCHEMA_VERSION,
                        "_resume_from_callback": True,
                    },
                )
        return None

    async def _asubscribe_blueprint_timeout(
        self, context: ExecutionContext | None, *, kind: str
    ) -> None:
        """建蓝图挂起的**超时兜底**订阅（``BlueprintGateCallback``，best-effort）。

        ⭐ 这条订阅**不是唤醒通路**（唤醒走作答链的 ``aresume_after_gate_action`` 重入），
        它只提供 ``check_timeouts`` 的到期兜底：没有它，一条等不到人回答 / 等不到人审的
        蓝图工作流会**无声地永久挂着**（没有任何可查询的失败信号）。事件类型取独立值
        ⇒ 既有 ``PlanClarifyCallback`` 回调消费者必不命中它（那个回调按
        ``clarification_id`` 查 ``Clarification`` 行，对蓝图线程恒查无）。

        chat 入口（无 ``workflow_execution`` / ``node_execution``）不建订阅。整段吞异常：
        观测/兜底 best-effort，⛔ 绝不反噬节点挂起本身。
        """
        if context is None or not (context.workflow_execution and context.node_execution):
            return
        try:
            from datetime import timedelta

            from django.conf import settings
            from django.utils import timezone

            from workflows.models.execution import WorkflowEventSubscription

            hours = (
                getattr(settings, "CLARIFICATION_TIMEOUT_HOURS", 24)
                if kind == "clarification"
                else getattr(settings, "BLUEPRINT_REVIEW_TIMEOUT_HOURS", 72)
            )
            await WorkflowEventSubscription.objects.acreate(
                workflow_execution=context.workflow_execution,
                node_execution=context.node_execution,
                event_type=_BLUEPRINT_GATE_EVENT_TYPE,
                project_key=context.workflow_context.get("project_key", ""),
                timeout_at=timezone.now() + timedelta(hours=hours),
                timeout_action="fail",
            )
        except Exception:  # noqa: BLE001 — 超时兜底 best-effort，绝不反噬挂起语义
            logger.warning(
                "plan_research_blueprint_timeout_subscribe_failed",
                category="sampling",
                component="plan_research",
                execution_id=context.execution_id,
                node_id=context.node_id,
                kind=kind,
            )

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

        RELY-02「澄清必达」：5 条失败路径（无子题 / 无空间 / 无项目 / 无群 / 发送抛）**一条
        都不静默 return**——各经 ``_amark_delivery_failed`` 记结构化日志 + emit 送达失败事件 +
        把该轮标 ``delivery_failed``，供澄清超时扫描据此立即出口。静默返回正是「无声卡死」的
        确切成因之一。
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
                await self._amark_delivery_failed(
                    session, context, clarification_id, "no_questions"
                )
                return
            round_meta = await (
                Clarification.objects.filter(id=clarification_id).values("round_no").afirst()
            )
            round_no = (round_meta or {}).get("round_no")
            space = await _resolve_space(context)
            if space is None:
                await self._amark_delivery_failed(
                    session, context, clarification_id, "no_space", round_no=round_no
                )
                return
            project = await _aresolve_project(space)
            if project is None:
                await self._amark_delivery_failed(
                    session, context, clarification_id, "no_project", round_no=round_no
                )
                return
            initiated_by_user_id = self._resolve_initiator(context)
            chat_id = await ProjectService().resolve_or_create_group(
                project=project,
                member_ids=[],
                initiated_by_user_id=initiated_by_user_id,
            )
            if not chat_id:
                await self._amark_delivery_failed(
                    session, context, clarification_id, "no_chat_id", round_no=round_no
                )
                return
            card = build_clarification_card(
                questions,
                execution_id=context.execution_id,
                node_id=context.node_id,
                clarification_id=clarification_id,
                round_no=round_no or 1,
            )
            im_service = await FeishuIMService.create(space)
            await im_service.send_card(receive_id=chat_id, receive_id_type="chat_id", card=card)
        except Exception:  # noqa: BLE001 — 发卡 best-effort，绝不反噬挂起
            log.warning("plan_research_clarify_card_failed", session_id=str(session.id))
            await self._amark_delivery_failed(session, context, clarification_id, "send_failed")

    async def _amark_delivery_failed(
        self,
        session: Any,
        context: ExecutionContext,
        clarification_id: str,
        reason: str,
        *,
        round_no: int | None = None,
    ) -> None:
        """澄清卡送达失败留痕：结构化日志 + 事件 + 该轮 ``container_status`` 标记。

        三件事一次做齐，缺一条就还是「无声卡死」：
        1. warning 级结构化日志（带触发用户，缺则 ``system``）——排障入口；
        2. 经 ``ConvergenceSessionService._emit_event`` 落会话事件（事件唯一写入入口，
           后续时间线复用同一事件源）；payload 只含受控枚举 ``reason``，不含异常原文；
        3. 把该轮 ``container_status`` 标 ``delivery_failed``——**只写这一列，绝不写
           ``answered_at``**（写了该轮会被误判为已答，从此永久失去出口）。

        整体 best-effort：留痕自身失败一律吞掉，绝不反噬发卡与节点挂起语义。
        """
        try:
            from delivery.models import Clarification
            from delivery.services.convergence_session_service import ConvergenceSessionService
            from delivery.services.event_taxonomy import EVENT_CLARIFICATION_DELIVERY_FAILED

            safe_reason = reason if reason in _DELIVERY_FAILURE_REASONS else "unknown"
            logger.warning(
                "clarification_delivery_failed",
                clarification_id=clarification_id,
                reason=safe_reason,
                channel="feishu",
                session_id=str(getattr(session, "id", "")),
                execution_id=context.execution_id,
                node_id=context.node_id,
                initiated_by_user_id=self._resolve_initiator(context),
                category="caller",
                component="plan_research",
            )
            if round_no is None:
                meta = await (
                    Clarification.objects.filter(id=clarification_id).values("round_no").afirst()
                )
                round_no = (meta or {}).get("round_no")
            await Clarification.objects.filter(id=clarification_id).aupdate(
                container_status="delivery_failed"
            )
            await ConvergenceSessionService()._emit_event(
                EVENT_CLARIFICATION_DELIVERY_FAILED,
                session,
                {
                    "clarification_id": clarification_id,
                    "round_no": round_no,
                    "channel": "feishu",
                    "reason": safe_reason,
                },
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬发卡/挂起
            pass

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

    # ⭐ 蓝图会话**不走本函数**（同步点 2）：分档在 :meth:`execute` 里按 ``process_type``
    # 分流到 :meth:`_amap_terminal_blueprint`。分流放在调用点而不是本函数开头，是因为
    # 蓝图分档需要 ``context``（建人审/澄清的超时兜底订阅），而本函数的两参签名被既有
    # 测试按替身覆盖 —— 改签名会打断那些替身。本函数因此**逐字未改**。
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

    async def _amap_terminal_blueprint(
        self, session: Any, context: ExecutionContext | None
    ) -> NodeResult:
        """蓝图会话的终态映射：按**蓝图状态**分档（⛔ 不按 ``session.status``）。

        =========================  ==================================================
        蓝图状态                    NodeResult
        =========================  ==================================================
        ``needs_clarification``    ``waiting_event``（挂起等人回答，⛔ 不是失败）
        ``pending_review``         ⭐ ``waiting_event``（**挂起等人终审**，⛔ 不是完成）
        ``confirmed`` / 实施中/完成  ``completed`` + 派生的 execution_plan 载荷
        ``failed``                 ``failed``
        其余中间态                   ``failed``（``blueprint_unreviewed``）
        =========================  ==================================================

        ⭐ **``pending_review`` 挂起而不是完成**是本次改动的要害（RELY-01）：蓝图的
        ``DONE`` 语义是「等人审」（``review_passed → STAGE_DONE`` 把 ``blueprint_status``
        置成 ``pending_review``），报 ``completed`` 会沿 ``default`` 出边把**未经人审**的
        蓝图直接交给下游 ``ai_coding`` 建分支写代码。人审动作（approve / reject）经
        ``aresume_after_gate_action`` 重入本节点：届时状态已是 ``confirmed`` ⇒ 走
        ``completed`` 那一档，闭环。

        ⭐ **``completed`` 那一档喂下游的是派生后的 technical_plan 形状**：下游
        ``ai_coding`` / ``human_approval`` 读 ``plan.execution_plan``，而 blueprint/v1
        **没有**这个顶层必填键（它是「确认后确定性派生」的可选段，见
        ``blueprint_schema`` ``:741``）。直接内联 blueprint/v1 就是在工作流侧复刻 MCP 那条
        「结构合法而语义为空」的静默降级（审计 §4.1 的 G3）。故经
        ``blueprint_execution.derive_execution_plan`` 派生后再内联，
        原始 blueprint content 以 ``blueprint_content`` 键并列保留（不丢信息）。

        ⭐ **其余中间态如实报失败**（⛔ 与 chat 那档「不报失败」刻意不同，判断依据是
        下游不同）：chat 只把结果讲给对话里的人看，工作流的 ``completed`` 会把载荷**交给
        编码代理**。会话到终态而蓝图仍停在 ``researching`` / ``drafting`` 是可诊断异常，
        此时既不能放行（未经人审）也不能装作还在跑（没有人会再推进它）⇒ 走 ``error``
        出边如实报错，产物仍在库里可人工续推。
        """
        from delivery.models import ArtifactVersion, ConvergenceSessionStatus
        from services.process_runtime.blueprint_execution import derive_execution_plan
        from services.process_runtime.blueprint_observation import (
            ablueprint_observation,
            blueprint_status_message,
            render_observed_blueprint,
        )

        observation = await ablueprint_observation(session, with_threads=False)
        current_status = observation.current_status

        if current_status == _BLUEPRINT_STATUS_NEEDS_CLARIFICATION:
            suspend = await self._amaybe_suspend_blueprint(
                session, context, force_clarification=True
            )
            if suspend is not None:
                return suspend

        if (
            current_status == _BLUEPRINT_STATUS_FAILED
            or session.status == ConvergenceSessionStatus.FAILED
        ):
            error = session.error if isinstance(session.error, dict) else {}
            return NodeResult(
                status="failed",
                error=str(
                    error.get("message") or error.get("reason") or "blueprint session failed"
                ),
                output={
                    "session_id": str(session.id),
                    "schema_version": _BLUEPRINT_SCHEMA_VERSION,
                    "artifact_id": observation.artifact_id,
                    "current_status": current_status,
                    "error_code": "blueprint_session_failed",
                    "error": error,
                },
                next_handle="error",
            )

        if current_status == _BLUEPRINT_STATUS_PENDING_REVIEW:
            await self._asubscribe_blueprint_timeout(context, kind="human_review")
            return NodeResult(
                status="waiting_event",
                output={
                    "session_id": str(session.id),
                    "kind": "human_review",
                    "schema_version": _BLUEPRINT_SCHEMA_VERSION,
                    "artifact_id": observation.artifact_id,
                    "current_status": current_status,
                    "suspension": {
                        "type": "await_human_review",
                        "artifact_id": observation.artifact_id,
                        "message": blueprint_status_message(current_status),
                    },
                },
            )

        if current_status in _BLUEPRINT_REVIEWED_STATUSES:
            av_id = (
                str(session.current_artifact_version_id)
                if session.current_artifact_version_id
                else None
            )
            blueprint_content: dict[str, Any] = {}
            plan_content: dict[str, Any] = {}
            plan_markdown = ""
            if av_id:
                av = await ArtifactVersion.objects.filter(id=av_id).afirst()
                if av is not None and isinstance(av.content, dict):
                    blueprint_content = av.content
                    meta = av.content.get("meta")
                    meta = meta if isinstance(meta, dict) else {}
                    plan_content = {
                        "title": str(meta.get("title") or ""),
                        "execution_plan": derive_execution_plan(av.content),
                        "artifact_version_id": av_id,
                    }
                    plan_markdown = render_observed_blueprint(av.content, current_status)
            return NodeResult(
                status="completed",
                output={
                    "session_id": str(session.id),
                    "schema_version": _BLUEPRINT_SCHEMA_VERSION,
                    "artifact_version_id": av_id,
                    "artifact_id": observation.artifact_id,
                    "status": "done",
                    "current_status": current_status,
                    "plan": plan_content,
                    "plan_markdown": plan_markdown,
                    # 原始 blueprint/v1 content 并列保留（不丢信息、可追踪）。
                    "blueprint_content": blueprint_content,
                },
                next_handle="default",
            )

        return NodeResult(
            status="failed",
            error=(
                "技术蓝图未走完人审前的产出流程（当前状态："
                f"{current_status or '未进入状态机'}），已中止后续编码。"
            ),
            output={
                "session_id": str(session.id),
                "schema_version": _BLUEPRINT_SCHEMA_VERSION,
                "artifact_id": observation.artifact_id,
                "current_status": current_status,
                "error_code": "blueprint_unreviewed",
            },
            next_handle="error",
        )

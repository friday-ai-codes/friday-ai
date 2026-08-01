"""start_plan_research chat agent 工具 —— Chat 入口薄封装（ENTRY-02）。

给对话加一层**薄入口**：LLM 识别「做多仓技术方案 / 跨仓方案编排」意图时调本工具，经共享
helper（``start_orchestration`` + ``build_orchestration_engine``）建 ``entrypoint=chat`` 的
``PlanSession`` 并驱动**与工作流节点完全相同的** ``PlanOrchestrationEngine``——不并行造两套
编排（SC-1）。

薄封装铁律：本工具**绝不写新编排逻辑**，只做：① 建 session（INV-2：自然语言需求
``work_item=None`` 显式可追溯，entrypoint=chat 标记）；② 复用同一 engine 驱动 advance；
③ 终态 / 挂起映射。澄清 / 调研挂起复用 chat 既有 HITL（``ask_clarification`` interrupt /
``deep_analysis`` fire-and-forget marker），**不重实现**；engine 状态全持久化 → 跨轮次 / 容器
回调由既有 chat 机制 resume（真实 LLM/容器端到端 resume E2E 沿用既有 deferred）。

**async ORM 防裸 lazy-FK**（规避 Phase 38 CR-01 类）：用 ``*_id`` 标量 / ``.values()`` /
``afirst`` / ``aget``，绝不裸访问同步 lazy-FK。所有 delivery/engine import 用函数内 lazy
import 规避 chat→delivery 循环（对齐 coding_tools）。
"""

from __future__ import annotations

from typing import Any, Final

import structlog

from agents.tools.base import ToolResult, tool

logger = structlog.get_logger(__name__)

# 驱动循环最大步数（防 advance 不前进死循环，T-42-03；mirror 工作流节点 _MAX_ADVANCE_STEPS）
_MAX_ADVANCE_STEPS = 20

# plan 编排澄清挂起的**独立渲染 marker**（UNIFY-05 单一来源收口，T-94-05-MARKER）。
#
# **仅前端渲染信号**——区别 chat 单题 ``ask_clarification``（见 agents/tools/clarification.py
# 的 ``CLARIFICATION_PENDING_MARKER``）。挂起 / 续推的**权威唯一**以 ``delivery.Clarification`` +
# ``PlanSession`` 为准，收答唯一经 91-04 专路由 ``POST /conversations/{id}/plan-clarification/answer/``
# → ``aanswer_round_and_resume``。
#
# 取独立值（``!= "ask_clarification"``）确保 chat graph ``_extract_pending_clarification`` 的双条件
# （``tc.name == "ask_clarification"`` AND ``payload.marker == "ask_clarification"``）**必不命中**本工具
# 输出 → plan 澄清绝不写 ``ConversationIntentTrace``、不靠 chat graph interrupt 收答（物理隔离）。
PLAN_CLARIFICATION_RENDER_MARKER: Final[str] = "plan_clarification"


@tool(
    name="start_plan_research",
    description=(
        "发起多仓 / 跨仓技术方案编排（方案调研）。当对话中识别用户想「做一个跨多个仓库的"
        "技术方案 / 跨仓方案编排 / 多仓协同改造方案」意图时调用。\n"
        "本工具复用与工作流入口完全相同的方案编排引擎："
        "拆分→路由→召回→澄清→并行调研→融合，产出 canonical 跨仓主方案（MergedPlan）。\n"
        "若需要澄清会暂停并向用户提问；若需要深入调研会启动远程容器并立即返回"
        "（调研在途；调研完成后将自动融合并返回 canonical 主方案）。"
    ),
    category="PROJECT",
    parameters={
        "type": "object",
        "properties": {
            "requirement_text": {
                "type": "string",
                "description": "自然语言需求文本（用户想实现的跨仓需求描述）。",
            },
            "include_repos": {
                "type": "array",
                "items": {"type": "string"},
                "description": ("可选：限定候选仓库 UUID 列表（不传则按召回 / 路由自动选取）。"),
            },
            "space_id": {
                "type": "string",
                "description": "空间 UUID (auto-injected)",
            },
            "conversation_id": {
                "type": "string",
                "description": "会话 UUID (auto-injected)",
            },
        },
        "required": ["requirement_text", "space_id", "conversation_id"],
    },
)
async def start_plan_research(
    requirement_text: str,
    space_id: str,
    conversation_id: str,
    include_repos: list[str] | None = None,
) -> ToolResult:
    """Chat 入口薄封装：建 entrypoint=chat session + 复用同一 engine 驱动方案编排到终态 / 挂起。"""
    # 0. 空需求 fail-closed 守护（与工作流节点 _create_session missing_requirement 对称）：
    #    requirement_text 属半可信输入（chat LLM → 工具，见 threat model），空 / 纯空白即拒绝，
    #    不建 session、不驱动 engine——避免浪费一次编排并落语义空洞的 PlanSession（WR-02）。
    if not requirement_text or not requirement_text.strip():
        logger.warning(
            "start_plan_research_missing_requirement",
            space_id=space_id,
            conversation_id=conversation_id,
        )
        return ToolResult(
            success=False,
            error="缺少需求文本（requirement_text）",
        )

    from services.process_runtime import start_orchestration
    from services.process_runtime.blueprint_entry_switch import aresolve_entry_process_type
    from services.process_runtime.blueprint_resume import BLUEPRINT_PROCESS_TYPE
    from services.process_runtime.entrypoint import build_engine_for_session

    logger.info(
        "start_plan_research_requested",
        space_id=space_id,
        conversation_id=conversation_id,
        include_repos_count=len(include_repos or []),
    )

    # 1. 解析 created_by（召回 stage 权限 actor）：从 Conversation.created_by 取用户对象；
    #    解析失败 / 为空 → None（recall stage 对 None actor fail-closed 返回空召回，文档化降级）。
    created_by = await _resolve_actor(conversation_id)

    # 2. include_repos best-effort 过滤到属于 space 的仓库 UUID（与工作流节点对称，不做新路由）。
    filtered_repos = await _filter_repos_in_space(space_id, include_repos)

    # 116-03：按 per-entry 运行时开关分派该建哪条 process。⛔ 实参必须是**字面量常量**，
    # 绝不写 session.entrypoint —— 反推会让「只打开 workflow 键」把 MCP 一起切走。
    if await aresolve_entry_process_type("chat") == BLUEPRINT_PROCESS_TYPE:
        return await _astart_blueprint_plan_research(
            requirement_text=requirement_text,
            conversation_id=conversation_id,
            created_by=created_by,
            include_repos=filtered_repos,
        )

    # 3. 建 session：work_item=None 即 INV-2 自然语言需求显式标记（entrypoint=chat 可追溯）。
    #    conversation_id 软引用会话，供会话列表反查「该会话是否产出 SDD spec」（has_sdd_spec 徽标）。
    session = await start_orchestration(
        entrypoint="chat",
        requirement_text=requirement_text,
        work_item=None,
        created_by=created_by,
        include_repos=filtered_repos,
        conversation_id=conversation_id or None,
        entry_key="chat",
    )

    # 4. 构建 engine + driver：与工作流节点同一 build_engine_for_session（engine 与 driver
    #    一起按 session.process_type 分派，116-03）。无 node_execution_id —— chat resume 走
    #    既有 deep_analysis / clarification 机制，不依赖 node_execution。
    engine, adrive = build_engine_for_session(session)

    # 5. 复用 43-02 共享续驱 helper（与工作流节点 / 回调消费者同源，不造两套循环）：
    #    advance 至「重挂起短路点」（clarifying-未答 / researching-在途）或终态 {DONE, FAILED}；
    #    step 上限由 helper 内部经 transition(fail) fail-soft 退出。行为等价于原内联循环。
    session = await adrive(engine, session, max_steps=_MAX_ADVANCE_STEPS)

    # 6. 入口私有挂起 marker 映射（保留）：helper 短路返回后再判一次，clarifying-pending /
    #    researching-在途 处复用 chat 既有 HITL 返回挂起 marker（+ register_blocking_task）。
    suspend = await _maybe_suspend(session, conversation_id)
    if suspend is not None:
        logger.info(
            "start_plan_research_suspended",
            session_id=str(session.id),
            status=session.status,
        )
        return suspend

    # 7. 终态映射
    return _map_terminal(session)


async def _astart_blueprint_plan_research(
    *,
    requirement_text: str,
    conversation_id: str,
    created_by: Any,
    include_repos: list[str],
) -> ToolResult:
    """chat 入口的蓝图路径：先定 ``meta.project_id``，再建 ``technical_blueprint`` 会话并续驱。

    ⭐ **``project_id`` 推不出即拒绝发起**（⛔ 不建 session、不建 artifact）：它是全链范围闸 /
    图谱 space 归属 / 导出可用性的唯一来源，写错即三条防线同时失效**且不报错**。推导链是
    「会话显式绑定的项目 → 否则会话所属空间过 ``_aresolve_project``」，收口在
    ``blueprint_intake.aresolve_project_id``（⛔ 四个入口不各写一份）。

    ⛔ **绝不透传 ``skip_clarification`` / ``force_confirm``**：蓝图链没有 ``clarify`` dep。
    """
    from services.process_runtime.blueprint_intake import (
        BlueprintIntakeRejected,
        aresolve_project_id,
    )
    from services.process_runtime.entrypoint import (
        build_engine_for_session,
        start_blueprint_orchestration,
    )

    conversation = await _aresolve_conversation(conversation_id)
    try:
        project_id = await aresolve_project_id(entry="chat", conversation=conversation)
    except BlueprintIntakeRejected as exc:
        logger.warning(
            "start_plan_research_blueprint_rejected",
            category="caller",
            component="plan_research_tools",
            conversation_id=conversation_id,
            reason=exc.reason,
        )
        return ToolResult(success=False, error=exc.detail)

    session = await start_blueprint_orchestration(
        entrypoint="chat",
        requirement_text=requirement_text,
        work_item=None,
        created_by=created_by,
        include_repos=include_repos,
        conversation_id=conversation_id or None,
        project_id=project_id,
        entry_key="chat",
    )
    logger.info(
        "start_plan_research_blueprint_started",
        category="caller",
        component="plan_research_tools",
        session_id=str(session.id),
        conversation_id=conversation_id,
    )

    # engine 与 driver 一起来自分派器（⛔ 只换 engine 不换 driver 会落 advance_step_limit）。
    engine, adrive = build_engine_for_session(session)
    session = await adrive(engine, session, max_steps=_MAX_ADVANCE_STEPS)

    suspend = await _maybe_suspend(session, conversation_id)
    if suspend is not None:
        return suspend
    return await _map_terminal_blueprint(session, conversation_id)


async def _aresolve_conversation(conversation_id: str) -> Any:
    """按 id 取 ``Conversation`` 对象（``aresolve_project_id`` 的 chat 权威上下文）。

    取不到返 ``None`` —— 推导链随之落空并抛 ``BlueprintIntakeRejected``（fail-closed：
    ⛔ 宁可拒绝发起，也不落一份 ``meta.project_id`` 为空的蓝图）。
    """
    if not conversation_id:
        return None
    from chat.models import Conversation

    return await Conversation.objects.filter(id=conversation_id).afirst()


async def _resolve_actor(conversation_id: str) -> Any:
    """从 ``Conversation.created_by`` 解析发起用户（async 安全，不裸 lazy-FK）。

    取 ``created_by`` 标量再按 id 取 User 对象；conversation 不存在 / created_by 为空 → None
    （None actor 下召回 stage fail-closed 返回空召回，文档化降级，不报错）。
    """
    if not conversation_id:
        return None
    from chat.models import Conversation

    row = await Conversation.objects.filter(id=conversation_id).values("created_by").afirst()
    if not row or not row.get("created_by"):
        return None
    from accounts.models import User

    return await User.objects.filter(id=row["created_by"]).afirst()


async def _filter_repos_in_space(space_id: str, include_repos: list[str] | None) -> list[str]:
    """include_repos best-effort 过滤到属于 space 的仓库 UUID（透传，不做新路由）。

    非法 UUID / 查询异常一律降级为空列表（best-effort，不阻断编排发起）。
    """
    if not include_repos:
        return []
    from repositories.models import Repository

    try:
        kept = [
            str(rid)
            async for rid in Repository.objects.filter(
                id__in=include_repos, spaces__id=space_id, is_deleted=False
            ).values_list("id", flat=True)
        ]
    except Exception:  # noqa: BLE001 — best-effort 过滤，非法 UUID 等降级为空
        logger.warning("start_plan_research_repo_filter_failed", space_id=space_id)
        return []

    # IN-01：区分「未传 include_repos」（上面已 return []）与「显式传了但全部不属于该 space /
    # 含非法 UUID」——后者用户的显式限定意图被静默丢弃、回退全空间自动路由。记一条醒目日志
    # （requested vs kept 计数）便于排查，避免「以为限定生效」的困惑。
    if not kept:
        logger.warning(
            "start_plan_research_include_repos_all_filtered",
            space_id=space_id,
            requested=len(include_repos),
            kept=0,
        )
    return kept


async def _maybe_suspend_blueprint(
    session: Any, conversation_id: str, *, force_clarification: bool = False
) -> ToolResult | None:
    """蓝图会话的挂起判定（判据与 ``blueprint_resume`` 的 pause 短路**同源**，⛔ 不自造第二套）。

    两档：

    1. ``waiting_clarification`` 且存在 **open + blocking** 的 ``BlueprintThread``（
       ⭐ **不传 ``kind``** —— ``ai_clarification`` 与 ``repo_confirmation`` 两类都算，与
       ``adrive_blueprint_session_to_pause_or_terminal`` 的短路判据逐字同源）⇒ 挂起 marker。
       ⭐ 复用**既有的** :data:`PLAN_CLARIFICATION_RENDER_MARKER`：前端按 ``marker`` 分派渲染，
       新造第二个 marker 会让蓝图澄清在对话里**什么都不渲染**。
    2. ``waiting_event`` 且仍有在途调研 ⇒ 既有 blocking task marker（蓝图确实建
       ``RepoResearchTask``，这条判据对蓝图**有效**）。⭐ ``task_id`` 与 ``params.session_id``
       都用 ``str(session.id)`` —— 那是 barrier 回灌 key 对齐的另一半。

    ``force_clarification``：终态映射的 ``needs_clarification`` 档复用第 1 档（同一份实现，
    ⛔ 不复制第二份线程查询），此时会话 ``status`` 已不是 ``waiting_clarification``。
    """
    from common.logging import redact_secrets_in_text
    from delivery.models import (
        ArtifactVersion,
        BlueprintThread,
        BlueprintThreadMessage,
        ConvergenceSessionStatus,
        ThreadStatus,
    )
    from services.process_runtime import aall_research_tasks_terminal

    if force_clarification or session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION:
        version_id = getattr(session, "current_artifact_version_id", None)
        artifact_id = None
        if version_id:
            row = await ArtifactVersion.objects.filter(id=version_id).values("artifact_id").afirst()
            artifact_id = (row or {}).get("artifact_id")
        if artifact_id:
            # ⚠️ BlueprintThread.Meta 无 ordering ⇒ 必须显式排序，否则「首题」随数据库
            # 返回顺序漂移，用户每次刷新看到的问题都可能不同。
            thread = await (
                BlueprintThread.objects.filter(
                    artifact_id=artifact_id, status=ThreadStatus.OPEN, blocking=True
                )
                .order_by("created_at")
                .values("id")
                .afirst()
            )
            if thread is not None:
                message = await (
                    BlueprintThreadMessage.objects.filter(thread_id=thread["id"])
                    .order_by("created_at")
                    .values("body")
                    .afirst()
                )
                return ToolResult(
                    success=True,
                    output={
                        # 键集与旧链分支逐字一致，只有两处差异（chat 前端消费方据此渲染）：
                        # ① clarification_id 位放 thread_id；② 追加 artifact_id 供深链到查看器。
                        "clarification_id": str(thread["id"]),
                        "pending": True,
                        "marker": PLAN_CLARIFICATION_RENDER_MARKER,
                        # 半可信 LLM 产出进对话，脱敏不可绕过（T-116-25）。
                        "question": redact_secrets_in_text(str((message or {}).get("body") or "")),
                        "options": [],
                        "allow_freeform": True,
                        "session_id": str(session.id),
                        "artifact_id": str(artifact_id),
                    },
                )

    if session.status == ConvergenceSessionStatus.WAITING_EVENT:
        if not await aall_research_tasks_terminal(session.id):
            from agents.tools.blocking_task_registry import register_blocking_task

            blocking_info: dict[str, Any] = {
                "task_id": str(session.id),
                "task_type": "plan_research",
                "params": {"session_id": str(session.id)},
            }
            await register_blocking_task(conversation_id, blocking_info)
            return ToolResult(
                success=True,
                output={
                    "__blocking_task__": True,
                    "task_type": "plan_research",
                    "task_id": str(session.id),
                    "session_id": str(session.id),
                    "params": {"session_id": str(session.id)},
                    "placeholder": (
                        f"已发起技术蓝图编排调研（session={session.id}，状态={session.status}）；"
                        "深入调研容器运行中，调研完成后将自动融合并返回蓝图。"
                    ),
                },
            )
    return None


async def _maybe_suspend(session: Any, conversation_id: str) -> ToolResult | None:
    """clarifying（pending）/ researching（在途）处复用 chat 既有 HITL 返回挂起 marker。

    ⭐ **蓝图会话走蓝图版判据**（116-03，§A.5 断链二）：下面两个分支都是**旧链**判据，对蓝图
    会话**全部失效且不抛异常** —— ``ClarificationService.ahas_pending`` 对蓝图恒 False（蓝图
    用 ``BlueprintThread``），``aall_research_tasks_terminal`` 在蓝图卡在 ``spec_gate`` 时零
    task 返 True。⇒ 一条正在等用户回答澄清的**健康**会话会穿过这里返回 None，落到终态映射拿到
    ``success=False, error="plan session failed"``：**用户看到「方案编排失败」，其实系统在等他
    回答问题**（T-116-23）。故先按 ``process_type`` 分流。
    """
    from delivery.models import Clarification, ConvergenceSessionStatus
    from services.process_runtime.blueprint_resume import BLUEPRINT_PROCESS_TYPE

    if str(getattr(session, "process_type", "")) == BLUEPRINT_PROCESS_TYPE:
        return await _maybe_suspend_blueprint(session, conversation_id)

    from delivery.services.clarification_service import ClarificationService
    from services.process_runtime import aall_research_tasks_terminal

    if session.status == ConvergenceSessionStatus.WAITING_CLARIFICATION:
        # WR-03：存在性判定收口 `ahas_pending`（结构化子题轮不误判）；取内容仍用显式查询。
        if not await ClarificationService().ahas_pending(session.id):
            pending = None
        else:
            pending = await (
                Clarification.objects.filter(session_id=session.id, answered_at__isnull=True)
                .values("id", "question")
                .afirst()
            )
        if pending is not None:
            # UNIFY-05：用**独立 plan 澄清渲染 marker**（不复用 chat 单题 ask_clarification）。
            # marker 仅作前端渲染信号——前端据 session_id + clarification_id 走 plan 多题卡
            # （pending_plan_clarification runtime 驱动），不走 chat 单题卡；挂起/续推权威唯一在
            # delivery.Clarification + PlanSession，收答经 91-04 专路由 → aanswer_round_and_resume。
            # 新 marker != "ask_clarification" → chat graph _extract_pending_clarification 双条件
            # （name + marker）必不命中 → 物理隔离，plan 澄清绝不写 ConversationIntentTrace。
            return ToolResult(
                success=True,
                output={
                    "clarification_id": str(pending["id"]),
                    "pending": True,
                    "marker": PLAN_CLARIFICATION_RENDER_MARKER,
                    "question": pending["question"],
                    "options": [],
                    "allow_freeform": True,
                    "session_id": str(session.id),
                },
            )

    if session.status == ConvergenceSessionStatus.WAITING_EVENT:
        if not await aall_research_tasks_terminal(session.id):
            # 复用 chat 既有 deep_analysis fire-and-forget marker（容器完成后既有机制 resume）
            from agents.tools.blocking_task_registry import register_blocking_task

            blocking_info: dict[str, Any] = {
                "task_id": str(session.id),
                "task_type": "plan_research",
                "params": {"session_id": str(session.id)},
            }
            await register_blocking_task(conversation_id, blocking_info)
            return ToolResult(
                success=True,
                output={
                    "__blocking_task__": True,
                    "task_type": "plan_research",
                    "task_id": str(session.id),
                    "session_id": str(session.id),
                    "params": {"session_id": str(session.id)},
                    # WR-01：如实表述当前能力——43-03 已接通 chat 入口「调研完成 → 容器回调
                    # 续驱 engine + barrier 回灌融合」自动回流通路，故如实陈述：已发起 + 调研
                    # 在途 + 调研完成后自动融合回流。
                    "placeholder": (
                        f"已发起跨仓方案编排调研（session={session.id}，状态={session.status}）；"
                        "深入调研容器运行中，调研完成后将自动融合并返回 canonical 主方案。"
                    ),
                },
            )
    return None


async def _map_terminal_blueprint(session: Any, conversation_id: str) -> ToolResult:
    """蓝图会话的终态映射：按**蓝图状态**分档（⛔ 不按 ``session.status``）。

    现状（旧链 :func:`_map_terminal`）是 ``status != DONE ⇒ success=False``，而蓝图的
    ``DONE`` 语义是「**等人审**」、``needs_clarification`` 语义是「**等用户回答**」——两者都被
    报成「方案编排失败」（T-116-23）。分档：

    ==========================  ============================================
    蓝图状态                     返回
    ==========================  ============================================
    ``needs_clarification``     ⭐ **挂起 marker**（⛔ 不是失败）
    ``pending_review``          成功 + 「已产出，等待人工终审」
    ``confirmed`` / 实施中/完成   成功 + 对应文案
    ``failed``                  失败（取 ``session.error`` 消息）
    其余中间态                    成功 + 「仍在进行中」
    ==========================  ============================================

    ⭐ **其余中间态一律不报失败**：会话到终态但蓝图状态还停在 ``researching`` / ``drafting``
    属于**可诊断的异常**，报「失败」只会让用户误以为方案没了（产物其实在库里、可继续推进）。
    ⛔ 响应体键名不得出现字面 ``blueprint_status``（INV-6 源码扫描扫全 ``server/``）⇒ 用
    ``current_status``（114-05 立的既有解法）。
    """
    from delivery.models import ArtifactVersion, ConvergenceSessionStatus

    version_id = getattr(session, "current_artifact_version_id", None)
    artifact_id = ""
    current_status = ""
    if version_id:
        row = await (
            ArtifactVersion.objects.filter(id=version_id)
            .values("artifact_id", "artifact__blueprint_status")
            .afirst()
        )
        artifact_id = str((row or {}).get("artifact_id") or "")
        current_status = str((row or {}).get("artifact__blueprint_status") or "")

    if current_status == "needs_clarification":
        suspend = await _maybe_suspend_blueprint(session, conversation_id, force_clarification=True)
        if suspend is not None:
            return suspend

    if current_status == "failed" or session.status == ConvergenceSessionStatus.FAILED:
        error = session.error if isinstance(session.error, dict) else {}
        return ToolResult(
            success=False,
            error=str(error.get("message") or error.get("reason") or "blueprint session failed"),
        )

    message = _BLUEPRINT_STATUS_MESSAGES.get(current_status, "技术蓝图编排仍在进行中。")
    return ToolResult(
        success=True,
        output={
            "session_id": str(session.id),
            "artifact_id": artifact_id,
            "current_status": current_status,
            "message": message,
        },
    )


# 蓝图状态 → 对话文案（⛔ 键名不是响应体字段名，不触 INV-6 的字典键形态扫描）。
_BLUEPRINT_STATUS_MESSAGES: Final[dict[str, str]] = {
    "pending_review": "技术蓝图已产出，等待人工终审。",
    "confirmed": "技术蓝图已确认，可进入实施。",
    "implementing": "技术蓝图已确认并在实施中。",
    "implemented": "技术蓝图已实施完成。",
}


def _map_terminal(session: Any) -> ToolResult:
    """done → success + artifact_version_id；failed → 失败（取 session.error 消息）。"""
    from delivery.models import ConvergenceSessionStatus

    if session.status == ConvergenceSessionStatus.DONE:
        return ToolResult(
            success=True,
            output={
                "session_id": str(session.id),
                "artifact_version_id": (
                    str(session.current_artifact_version_id)
                    if session.current_artifact_version_id
                    else None
                ),
                "status": "done",
                "message": "跨仓方案编排已完成，已产出技术方案产物（ArtifactVersion）。",
            },
        )
    error = session.error if isinstance(session.error, dict) else {}
    return ToolResult(
        success=False,
        error=str(error.get("message") or error.get("reason") or "plan session failed"),
        # 110-HI-01：其余四个出口（WAITING_CLARIFICATION / __blocking_task__ / DONE）都在
        # output 顶层带 session_id，只有失败这条结构上不带 —— 前端气泡因此绑不到自己那次
        # 编排，会回退到 store 的全局活跃会话。metadata 经 _normalize_tool_result 并进出网
        # 体，让失败气泡也能钉回它自己那次编排（不含任何自由文本）。
        metadata={"session_id": str(session.id)},
    )


__all__ = ["PLAN_CLARIFICATION_RENDER_MARKER", "start_plan_research"]

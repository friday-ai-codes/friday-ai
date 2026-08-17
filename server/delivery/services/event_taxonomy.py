"""§15 事件 taxonomy 稳定常量集 + 统一信封 helper（EVENT-01，DOMAIN §15）。

把 §15 事件词表沉淀为**稳定常量**，各 emit 点统一引用常量（消除字符串字面量漂移），
并提供统一信封 ``{event, session_id, work_item_id?, ts, payload}`` 构造 helper——
PlanSessionEvent 持久化与未来 v0.11 对外 adapter 复用同一 shape（INV-5：progress/trace，
非模型私有 CoT）。

常量集说明：
- ``ALL_EVENTS``：**本 phase（v0.7）编排实际产出**的 §15 事件全集——供守护测试断言
  「所有 emit 点引用值 ∈ ALL_EVENTS」与「每个事件名至少被一个 emit 点产出」（覆盖性反查）。
- ``RESERVED_EVENTS``：§15 表已定义但**非本 phase 编排产出**的事件——``work_item.syncing``
  由 WorkItem 同步链路产出（§1，非编排）、``coding.wave.*`` 属 v0.8 OUT OF SCOPE。常量预留
  便于 v0.8/v0.11 扩展，但不计入 ``ALL_EVENTS`` 覆盖集。
"""

from __future__ import annotations

from typing import Any, Final

from django.utils import timezone

__all__ = [
    "EVENT_WORK_ITEM_SYNCING",
    "EVENT_KNOWLEDGE_RECALLING",
    "EVENT_REPO_ROUTING",
    "EVENT_REPO_RESEARCH_STARTED",
    "EVENT_REPO_RESEARCH_COMPLETED",
    "EVENT_REPO_RESEARCH_FAILED",
    "EVENT_CLARIFICATION_ASKED",
    "EVENT_CLARIFICATION_ANSWERED",
    "EVENT_CLARIFICATION_TIMED_OUT",
    "EVENT_CLARIFICATION_DELIVERY_FAILED",
    "EVENT_FEATURE_CLASSIFIED",
    "EVENT_PLAN_MERGE_STARTED",
    "EVENT_PLAN_MERGE_COMPLETED",
    "EVENT_PLAN_VALIDATION_FAILED",
    "EVENT_PROCESS_SESSION_FAILED",
    "EVENT_SPEC_DRAFTED",
    "EVENT_CODING_WAVE_STARTED",
    "EVENT_CODING_WAVE_COMPLETED",
    "EVENT_BLUEPRINT_STATUS_TRANSITIONED",
    "EVENT_BLUEPRINT_STAGE_STARTED",
    "EVENT_BLUEPRINT_STAGE_COMPLETED",
    "EVENT_BLUEPRINT_STAGE_FAILED",
    "EVENT_BLUEPRINT_SPEC_GATE_SCORED",
    "EVENT_BLUEPRINT_SPEC_GATE_CLARIFICATION_ASKED",
    "EVENT_BLUEPRINT_SPEC_GATE_LOCKED",
    "EVENT_BLUEPRINT_ROUTE_SCORED",
    "EVENT_BLUEPRINT_REPO_RESEARCH_STARTED",
    "EVENT_BLUEPRINT_REPO_RESEARCH_COMPLETED",
    "EVENT_BLUEPRINT_REPO_RESEARCH_FAILED",
    "EVENT_BLUEPRINT_REROUTE_TRIGGERED",
    "EVENT_BLUEPRINT_CONFIRMATION_OPENED",
    "EVENT_BLUEPRINT_CONFIRMATION_ACTION",
    "EVENT_BLUEPRINT_CONFIRMATION_LOCKED",
    "EVENT_BLUEPRINT_CONTEXT_ENTRY_APPENDED",
    "EVENT_BLUEPRINT_CONTEXT_WAITER_REGISTERED",
    "EVENT_BLUEPRINT_CONTEXT_WAITER_SATISFIED",
    "EVENT_BLUEPRINT_ROUTE_RECALLED",
    "EVENT_BLUEPRINT_ROUTE_PLAN_DRAFTED",
    "EVENT_BLUEPRINT_RETRIEVAL_COMPLETED",
    "EVENT_BLUEPRINT_REPO_PLAN_REPO_STARTED",
    "EVENT_BLUEPRINT_REPO_PLAN_REPO_COMPLETED",
    "EVENT_BLUEPRINT_REPO_PLAN_REPO_FAILED",
    "EVENT_BLUEPRINT_REPO_PLAN_WAVE_ADVANCED",
    "EVENT_BLUEPRINT_REVIEW_STARTED",
    "EVENT_BLUEPRINT_REVIEW_COMPLETED",
    "EVENT_BLUEPRINT_REVIEW_FAILED",
    "EVENT_BLUEPRINT_STAGE_RERUN_REQUESTED",
    "BLUEPRINT_EVENTS",
    "ALL_EVENTS",
    "RESERVED_EVENTS",
    "build_envelope",
]

# ---- §15 taxonomy 稳定常量（逐字对齐 DOMAIN §15 表） ----

# WorkItem 同步链路产出（§1，非编排）——常量预留，不计入 ALL_EVENTS
EVENT_WORK_ITEM_SYNCING: Final[str] = "work_item.syncing"

# 编排各 stage 产出（本 phase v0.7 实际 emit）
EVENT_KNOWLEDGE_RECALLING: Final[str] = "knowledge.recalling"
EVENT_REPO_ROUTING: Final[str] = "repo.routing"
EVENT_REPO_RESEARCH_STARTED: Final[str] = "repo.research.started"
EVENT_REPO_RESEARCH_COMPLETED: Final[str] = "repo.research.completed"
EVENT_REPO_RESEARCH_FAILED: Final[str] = "repo.research.failed"
EVENT_CLARIFICATION_ASKED: Final[str] = "clarification.asked"
EVENT_CLARIFICATION_ANSWERED: Final[str] = "clarification.answered"
# feature list 入口专属：功能点新增/改造分类完成（payload {summary, evidence_hits}）。
# 非 feature list 入口的 classify stage 走 pass-through，不产出本事件。
EVENT_FEATURE_CLASSIFIED: Final[str] = "technical_plan.feature.classified"
# technical_plan process 产出（P2：plan.* → technical_plan.* 通用/process 前缀）
EVENT_PLAN_MERGE_STARTED: Final[str] = "technical_plan.merge.started"
EVENT_PLAN_MERGE_COMPLETED: Final[str] = "technical_plan.merge.completed"
EVENT_PLAN_VALIDATION_FAILED: Final[str] = "technical_plan.validation.failed"
# 通用收敛会话失败（process 前缀，所有 process_type 共用）
EVENT_PROCESS_SESSION_FAILED: Final[str] = "process.session.failed"

# v0.9 SDD spec 产出，payload {spec_id, repository_id, plan_version_id}
# （producer = Plan 03 spec_generation.py，融合通过后逐 SDD 仓 best-effort emit）
EVENT_SPEC_DRAFTED: Final[str] = "spec.drafted"

# ---- v0.19 澄清韧性（RELY-02）：两者本里程碑内均有真实 emit 点，故计入 ALL_EVENTS ----
# 澄清轮超时出口。producer = delivery/management/commands/expire_pending_clarifications.py，
# payload {clarification_id, round_no, exit_action, waited_seconds, unclarified_points}，
# 其中 exit_action ∈ {"resumed_with_assumptions", "failed_no_answer"}。
# 为何不复用 clarification.answered：时间线必须能区分「用户答了」与「超时放行」，
# 混用会让时间线撒谎（正是本里程碑要消灭的行为）。
EVENT_CLARIFICATION_TIMED_OUT: Final[str] = "clarification.timed_out"
# 澄清卡送达失败。producer = workflows/nodes/ai/plan_research.py::_send_clarify_card，
# payload {clarification_id, round_no, channel, reason}，reason 为 5 值受控枚举
# （no_questions / no_space / no_project / no_chat_id / send_failed）——结构上不含上游
# 响应体或异常原文（T-107-02 信息泄漏面）。
EVENT_CLARIFICATION_DELIVERY_FAILED: Final[str] = "clarification.delivery_failed"

# v0.8 wave 编码产出——常量预留（OUT OF SCOPE 本 phase），不计入 ALL_EVENTS
EVENT_CODING_WAVE_STARTED: Final[str] = "coding.wave.started"
EVENT_CODING_WAVE_COMPLETED: Final[str] = "coding.wave.completed"

# 本 phase 编排实际产出的 §15 事件全集（守护测试基准）
ALL_EVENTS: Final[frozenset[str]] = frozenset(
    {
        EVENT_KNOWLEDGE_RECALLING,
        EVENT_REPO_ROUTING,
        EVENT_REPO_RESEARCH_STARTED,
        EVENT_REPO_RESEARCH_COMPLETED,
        EVENT_REPO_RESEARCH_FAILED,
        EVENT_CLARIFICATION_ASKED,
        EVENT_CLARIFICATION_ANSWERED,
        EVENT_CLARIFICATION_TIMED_OUT,
        EVENT_CLARIFICATION_DELIVERY_FAILED,
        EVENT_FEATURE_CLASSIFIED,
        EVENT_PLAN_MERGE_STARTED,
        EVENT_PLAN_MERGE_COMPLETED,
        EVENT_PLAN_VALIDATION_FAILED,
        EVENT_PROCESS_SESSION_FAILED,
        EVENT_SPEC_DRAFTED,
    }
)

# §15 表已定义但非本 phase 编排产出（v0.8/v0.11 扩展预留）
RESERVED_EVENTS: Final[frozenset[str]] = frozenset(
    {
        EVENT_WORK_ITEM_SYNCING,
        EVENT_CODING_WAVE_STARTED,
        EVENT_CODING_WAVE_COMPLETED,
    }
)

# ---- 蓝图（v0.20 Phase 111，DESIGN §4.2/§10） ----
# 蓝图生命周期/阶段事件。emit 点 = blueprint_lifecycle_service（111）与 112+ 编排阶段，
# 不在 ALL_EVENTS 守护测试的 producer 扫描清单内——故镜像 RESERVED_EVENTS 的
# 「已定义但不计入 ALL_EVENTS」先例，放独立 BLUEPRINT_EVENTS 集合（避免
# test_event_taxonomy_alignment 覆盖性反查误挂，RESEARCH P4）。

# 111 唯一实际 emit：蓝图状态转移（payload: artifact_id/from/to/initiated_by_user_id）
EVENT_BLUEPRINT_STATUS_TRANSITIONED: Final[str] = "blueprint.status.transitioned"
# 供 112+ 编排阶段消费（本相位仅定义常量）
EVENT_BLUEPRINT_STAGE_STARTED: Final[str] = "blueprint.stage.started"
EVENT_BLUEPRINT_STAGE_COMPLETED: Final[str] = "blueprint.stage.completed"
EVENT_BLUEPRINT_STAGE_FAILED: Final[str] = "blueprint.stage.failed"

# ---- 蓝图阶段 0/1（v0.20 Phase 112，DESIGN §5.4/§5.7） ----
# emit 点在 112-02/03/04/05；payload 只记标量与关联键——澄清正文、需求原文、召回内容
# 一律不进 payload（T-112-04）。供 115 前端时间线展开。

# emit: 112-02 规格门。payload: 四维分数/加权总分/threshold/passed
EVENT_BLUEPRINT_SPEC_GATE_SCORED: Final[str] = "blueprint.spec_gate.scored"
# emit: 112-02 超阈值开澄清线程。payload: thread_id/question_count（不含澄清正文）
EVENT_BLUEPRINT_SPEC_GATE_CLARIFICATION_ASKED: Final[str] = (
    "blueprint.spec_gate.clarification_asked"
)
# emit: 112-02 规格锁定。payload: resolved_thread_count/decision_log_count
EVENT_BLUEPRINT_SPEC_GATE_LOCKED: Final[str] = "blueprint.spec_gate.locked"
# emit: 112-03 双面路由。payload: candidate_count/router_version/各候选三分量 breakdown
EVENT_BLUEPRINT_ROUTE_SCORED: Final[str] = "blueprint.route.scored"
# emit: 112-04 逐仓容器调研。payload: repository_name/research_reason/routed_confidence/
# repository_id/task_id（人话键优先；缺 name 时前端走 Generic）
EVENT_BLUEPRINT_REPO_RESEARCH_STARTED: Final[str] = "blueprint.repo_research.started"
# emit: 112-04 调研回调。payload: repository_name/fitness_verdict(+verdict 兼容)/
# role_suggestion/findings_count/repository_id/task_id
EVENT_BLUEPRINT_REPO_RESEARCH_COMPLETED: Final[str] = "blueprint.repo_research.completed"
# emit: 112-04 调研失败。payload: repository_name/attempt/error(_kind|_detail)/
# repository_id/task_id（异常文本已脱敏截断）
EVENT_BLUEPRINT_REPO_RESEARCH_FAILED: Final[str] = "blueprint.repo_research.failed"
# emit: 112-04 有界重路由（≤2 轮）。payload: round/excluded_repository_ids/new_candidate_count
EVENT_BLUEPRINT_REROUTE_TRIGGERED: Final[str] = "blueprint.reroute.triggered"
# emit: 112-05 确认门开启。payload: thread_id/repository_count
EVENT_BLUEPRINT_CONFIRMATION_OPENED: Final[str] = "blueprint.confirmation.opened"
# emit: 112-05 用户动作。payload: action ∈ confirm|remove_repo|add_repo|
# reclassify_role|edit_responsibility + repository_id
EVENT_BLUEPRINT_CONFIRMATION_ACTION: Final[str] = "blueprint.confirmation.action"
# emit: 112-05 仓库集锁定。payload: locked_repository_count/decided_by
EVENT_BLUEPRINT_CONFIRMATION_LOCKED: Final[str] = "blueprint.confirmation.locked"

# ---- 蓝图上下文总线（v0.20 Phase 113，DESIGN §5.6） ----

# emit: 113-01 总线写入。payload: key/kind/seq/repository_id（**content 正文绝不进 payload**）
EVENT_BLUEPRINT_CONTEXT_ENTRY_APPENDED: Final[str] = "blueprint.context.entry_appended"
# emit: 113-01 waiter 登记。payload: from_repository_id/to_key/cycle_detected
# （供 115 时间线可视化「谁在等谁」）
EVENT_BLUEPRINT_CONTEXT_WAITER_REGISTERED: Final[str] = "blueprint.context.waiter_registered"
# emit: 113-01 waiter 命中/超时清理。payload: satisfied_count/redispatch_repository_ids/reason
EVENT_BLUEPRINT_CONTEXT_WAITER_SATISFIED: Final[str] = "blueprint.context.waiter_satisfied"

# ---- 蓝图阶段活动流（v0.21 Phase 118，LIVE-02/04/05） ----
#
# 为什么要这一组：改动前蓝图页只有「阶段级」事件，用户看到的是一个笼统的「生成中」——
# 路由到底召回了多少仓、凭什么给出 79.87% 的适配度、分仓阶段每个仓跑到哪了，全都不可见。
# 这一组补的正是「agent 此刻在做什么」这一层。
#
# ⭐ **载荷纪律不变（INV-5）**：只放**标量、枚举、计数、id 与引用 id**，前端据它们用 i18n
# 组装叙事文案（既有 `progressTextOf` 就是这个模式）。⛔ 模型推理原文 / 澄清题面 / 方案正文
# 一律不进 payload —— 那些正文本来就在蓝图 content 与线程里，查看器已能渲染，复制一份到
# 事件流只会带来脱敏风险与体积膨胀。
# ⭐ **高频步骤按采样类记录**（`category="sampling"`），逐条 tool call 不上事件流。

# emit: 118 路由召回完成（打分之前）。payload: candidate_count/router_candidate_count/
# charter_supplement_count/scope_repository_count/router_version/intent/duration_ms
EVENT_BLUEPRINT_ROUTE_RECALLED: Final[str] = "blueprint.route.recalled"
# emit: 118 初步仓库路由方案（打分之后、确认门之前）。payload: repository_count/
# router_version + repositories[] 每项 {repository_id, repository_name, role_suggestion,
#  confidence, total, matched_node_path_count, matched_domain_count,
#  violated_boundary_count, citation_ids[], pinned_branch}
# ⇒ 前端据此展示「仓 1 建议承接哪些能力、适配度多少、证据指向哪」。
# ⭐ `router_version == "project_binding"`（`repo_binding_pin.PINNED_ROUTER_VERSION`）时是
# **固定路由**：候选来自项目手动绑定，自动打分整段没跑 ⇒ total 恒 1.0、章程/历史分量与
# 各项证据计数恒 0。前端**必须**据此标注「固定路由」，否则那张全 0 的证据表看起来像 bug。
EVENT_BLUEPRINT_ROUTE_PLAN_DRAFTED: Final[str] = "blueprint.route.plan_drafted"
# emit: 118 检索/召回留痕上屏（RetrievalTrace 的标量镜像）。payload: scope/hit_count/
# top_score/duration_ms/tier —— ⛔ 召回**正文**不进 payload（正文归 RetrievalTrace 表）
EVENT_BLUEPRINT_RETRIEVAL_COMPLETED: Final[str] = "blueprint.retrieval.completed"
# emit: 118 分仓方案逐仓起止（阶段 2 每仓可见）。payload: repository_id/repository_name/wave
EVENT_BLUEPRINT_REPO_PLAN_REPO_STARTED: Final[str] = "blueprint.repo_plan.repo_started"
# 同上 + item_count/api_count/duration_ms
EVENT_BLUEPRINT_REPO_PLAN_REPO_COMPLETED: Final[str] = "blueprint.repo_plan.repo_completed"
# emit: quick-260806 补齐 started/completed/failed 三元（派发漏斗按 mode 分流 + 回调失败分支）。
# payload: repository_id/task_id/error（error 是机器可读 reason，⛔ 校验详情正文不进 payload）。
# ⚠️ 后缀是 `_failed` 不是 `.failed`——与 `repo_started`/`repo_completed` 同款约定，
# 前端 `buildStageTimeline` 的 `.failed` 后缀判据不会把「单仓失败」误判成「分仓阶段失败」。
EVENT_BLUEPRINT_REPO_PLAN_REPO_FAILED: Final[str] = "blueprint.repo_plan.repo_failed"
# emit: 118 波次推进。payload: wave/total_waves/repository_count
EVENT_BLUEPRINT_REPO_PLAN_WAVE_ADVANCED: Final[str] = "blueprint.repo_plan.wave_advanced"

# ---- 蓝图 AI 对抗审查（v0.20 Phase 114-03，FLOW-07） ----
# 114-03 追加：AI 对抗审查生命周期（payload 只含 findings **计数与分级分布**，正文绝不进 payload）。
EVENT_BLUEPRINT_REVIEW_STARTED: Final[str] = "blueprint.review.started"
EVENT_BLUEPRINT_REVIEW_COMPLETED: Final[str] = "blueprint.review.completed"
EVENT_BLUEPRINT_REVIEW_FAILED: Final[str] = "blueprint.review.failed"

# ---- 蓝图节点重跑（quick 260806）----
# emit: blueprint_stage_rerun 服务。payload 只记标量：stage / run_label /
# instruction_len / initiated_by_user_id —— **操作员指令正文不进 payload**。
EVENT_BLUEPRINT_STAGE_RERUN_REQUESTED: Final[str] = "blueprint.stage.rerun_requested"

# 蓝图事件独立集合（不进 ALL_EVENTS，见上方注释）
BLUEPRINT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        EVENT_BLUEPRINT_STATUS_TRANSITIONED,
        EVENT_BLUEPRINT_STAGE_STARTED,
        EVENT_BLUEPRINT_STAGE_COMPLETED,
        EVENT_BLUEPRINT_STAGE_FAILED,
        EVENT_BLUEPRINT_SPEC_GATE_SCORED,
        EVENT_BLUEPRINT_SPEC_GATE_CLARIFICATION_ASKED,
        EVENT_BLUEPRINT_SPEC_GATE_LOCKED,
        EVENT_BLUEPRINT_ROUTE_SCORED,
        EVENT_BLUEPRINT_REPO_RESEARCH_STARTED,
        EVENT_BLUEPRINT_REPO_RESEARCH_COMPLETED,
        EVENT_BLUEPRINT_REPO_RESEARCH_FAILED,
        EVENT_BLUEPRINT_REROUTE_TRIGGERED,
        EVENT_BLUEPRINT_CONFIRMATION_OPENED,
        EVENT_BLUEPRINT_CONFIRMATION_ACTION,
        EVENT_BLUEPRINT_CONFIRMATION_LOCKED,
        EVENT_BLUEPRINT_CONTEXT_ENTRY_APPENDED,
        EVENT_BLUEPRINT_CONTEXT_WAITER_REGISTERED,
        EVENT_BLUEPRINT_CONTEXT_WAITER_SATISFIED,
        # 118 活动流（LIVE-02/04/05）
        EVENT_BLUEPRINT_ROUTE_RECALLED,
        EVENT_BLUEPRINT_ROUTE_PLAN_DRAFTED,
        EVENT_BLUEPRINT_RETRIEVAL_COMPLETED,
        EVENT_BLUEPRINT_REPO_PLAN_REPO_STARTED,
        EVENT_BLUEPRINT_REPO_PLAN_REPO_COMPLETED,
        EVENT_BLUEPRINT_REPO_PLAN_REPO_FAILED,
        EVENT_BLUEPRINT_REPO_PLAN_WAVE_ADVANCED,
        EVENT_BLUEPRINT_REVIEW_STARTED,
        EVENT_BLUEPRINT_REVIEW_COMPLETED,
        EVENT_BLUEPRINT_REVIEW_FAILED,
        # 节点重跑（quick 260806）
        EVENT_BLUEPRINT_STAGE_RERUN_REQUESTED,
    }
)


def build_envelope(event: str, session: Any, payload: dict | None = None) -> dict:
    """构造 §15 统一信封 ``{event, session_id, work_item_id?, ts, payload}``。

    PlanSessionEvent 持久化（字段拆解到列）与 v0.11 对外 adapter 复用同一 shape。
    async 安全：用 ``session.work_item_id`` 标量（不访问 lazy-FK ``session.work_item``，
    规避 Phase 38 CR-01 类）。``ts`` 取 ISO8601 串（信封可 JSON 序列化外暴露）。
    """
    work_item_id = getattr(session, "work_item_id", None)
    return {
        "event": event,
        "session_id": str(session.id),
        "work_item_id": str(work_item_id) if work_item_id else None,
        "ts": timezone.now().isoformat(),
        "payload": payload or {},
    }

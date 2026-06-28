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
    "EVENT_PLAN_MERGE_STARTED",
    "EVENT_PLAN_MERGE_COMPLETED",
    "EVENT_PLAN_VALIDATION_FAILED",
    "EVENT_PROCESS_SESSION_FAILED",
    "EVENT_SPEC_DRAFTED",
    "EVENT_CODING_WAVE_STARTED",
    "EVENT_CODING_WAVE_COMPLETED",
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
# technical_plan process 产出（P2：plan.* → technical_plan.* 通用/process 前缀）
EVENT_PLAN_MERGE_STARTED: Final[str] = "technical_plan.merge.started"
EVENT_PLAN_MERGE_COMPLETED: Final[str] = "technical_plan.merge.completed"
EVENT_PLAN_VALIDATION_FAILED: Final[str] = "technical_plan.validation.failed"
# 通用收敛会话失败（process 前缀，所有 process_type 共用）
EVENT_PROCESS_SESSION_FAILED: Final[str] = "process.session.failed"

# v0.9 SDD spec 产出，payload {spec_id, repository_id, plan_version_id}
# （producer = Plan 03 spec_generation.py，融合通过后逐 SDD 仓 best-effort emit）
EVENT_SPEC_DRAFTED: Final[str] = "spec.drafted"

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

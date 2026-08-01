"""112 阶段事件常量守护测试（PLAN 112-01 Task 3，DESIGN §5.4/§5.7）。

守三件事（纯常量断言，无 DB、无 IO）：

1. 112 新增 11 个 ``blueprint_*`` 阶段事件常量全部在 ``BLUEPRINT_EVENTS`` 内——
   02/03/04/05 只消费不再改 event_taxonomy.py；
2. 蓝图事件（112 的 11 + 113 的 3 + 既有 4）**一个都不在** ``ALL_EVENTS``——111 决策：blueprint
   事件不进 ALL_EVENTS，否则 ``test_event_taxonomy_alignment`` 的覆盖性反查会误挂；
3. 既有 4 个常量字面值冻结（并行纪律 3：既有事件契约一字不动）。
"""

from __future__ import annotations

from delivery.services.event_taxonomy import (
    ALL_EVENTS,
    BLUEPRINT_EVENTS,
    EVENT_BLUEPRINT_CONFIRMATION_ACTION,
    EVENT_BLUEPRINT_CONFIRMATION_LOCKED,
    EVENT_BLUEPRINT_CONFIRMATION_OPENED,
    EVENT_BLUEPRINT_CONTEXT_ENTRY_APPENDED,
    EVENT_BLUEPRINT_CONTEXT_WAITER_REGISTERED,
    EVENT_BLUEPRINT_CONTEXT_WAITER_SATISFIED,
    EVENT_BLUEPRINT_REPO_RESEARCH_COMPLETED,
    EVENT_BLUEPRINT_REPO_RESEARCH_FAILED,
    EVENT_BLUEPRINT_REPO_RESEARCH_STARTED,
    EVENT_BLUEPRINT_REROUTE_TRIGGERED,
    EVENT_BLUEPRINT_REVIEW_COMPLETED,
    EVENT_BLUEPRINT_REVIEW_FAILED,
    EVENT_BLUEPRINT_REVIEW_STARTED,
    EVENT_BLUEPRINT_ROUTE_SCORED,
    EVENT_BLUEPRINT_SPEC_GATE_CLARIFICATION_ASKED,
    EVENT_BLUEPRINT_SPEC_GATE_LOCKED,
    EVENT_BLUEPRINT_SPEC_GATE_SCORED,
    EVENT_BLUEPRINT_STAGE_COMPLETED,
    EVENT_BLUEPRINT_STAGE_FAILED,
    EVENT_BLUEPRINT_STAGE_STARTED,
    EVENT_BLUEPRINT_STATUS_TRANSITIONED,
)

# 112 新增（emit 点在 02/03/04/05）
_NEW_112_EVENTS = {
    EVENT_BLUEPRINT_SPEC_GATE_SCORED: "blueprint.spec_gate.scored",
    EVENT_BLUEPRINT_SPEC_GATE_CLARIFICATION_ASKED: "blueprint.spec_gate.clarification_asked",
    EVENT_BLUEPRINT_SPEC_GATE_LOCKED: "blueprint.spec_gate.locked",
    EVENT_BLUEPRINT_ROUTE_SCORED: "blueprint.route.scored",
    EVENT_BLUEPRINT_REPO_RESEARCH_STARTED: "blueprint.repo_research.started",
    EVENT_BLUEPRINT_REPO_RESEARCH_COMPLETED: "blueprint.repo_research.completed",
    EVENT_BLUEPRINT_REPO_RESEARCH_FAILED: "blueprint.repo_research.failed",
    EVENT_BLUEPRINT_REROUTE_TRIGGERED: "blueprint.reroute.triggered",
    EVENT_BLUEPRINT_CONFIRMATION_OPENED: "blueprint.confirmation.opened",
    EVENT_BLUEPRINT_CONFIRMATION_ACTION: "blueprint.confirmation.action",
    EVENT_BLUEPRINT_CONFIRMATION_LOCKED: "blueprint.confirmation.locked",
}

# 113 新增（emit 点在 113-01 BlueprintContextService；本文件只作集合形状快照）
_NEW_113_EVENTS = {
    EVENT_BLUEPRINT_CONTEXT_ENTRY_APPENDED: "blueprint.context.entry_appended",
    EVENT_BLUEPRINT_CONTEXT_WAITER_REGISTERED: "blueprint.context.waiter_registered",
    EVENT_BLUEPRINT_CONTEXT_WAITER_SATISFIED: "blueprint.context.waiter_satisfied",
}

# 114-03 新增（emit 点在 BlueprintReviewAdapter；本文件只作集合形状快照）
_NEW_114_EVENTS = {
    EVENT_BLUEPRINT_REVIEW_STARTED: "blueprint.review.started",
    EVENT_BLUEPRINT_REVIEW_COMPLETED: "blueprint.review.completed",
    EVENT_BLUEPRINT_REVIEW_FAILED: "blueprint.review.failed",
}

# 111 既有（冻结快照）
_EXISTING_111_EVENTS = {
    EVENT_BLUEPRINT_STATUS_TRANSITIONED: "blueprint.status.transitioned",
    EVENT_BLUEPRINT_STAGE_STARTED: "blueprint.stage.started",
    EVENT_BLUEPRINT_STAGE_COMPLETED: "blueprint.stage.completed",
    EVENT_BLUEPRINT_STAGE_FAILED: "blueprint.stage.failed",
}


def test_new_112_events_literal_values() -> None:
    """11 个新常量字面值即契约（115 前端时间线按此匹配）。"""
    for actual, expected in _NEW_112_EVENTS.items():
        assert actual == expected


def test_new_112_events_in_blueprint_events() -> None:
    """11 个新常量全部 ∈ BLUEPRINT_EVENTS（02–05 直接消费）。"""
    for event in _NEW_112_EVENTS:
        assert event in BLUEPRINT_EVENTS


def test_blueprint_events_not_in_all_events() -> None:
    """112 的 11 + 113 的 3 + 114 的 3 + 既有 4 均不在 ALL_EVENTS（不污染覆盖性反查）。"""
    assert BLUEPRINT_EVENTS.isdisjoint(ALL_EVENTS)
    for event in (
        list(_NEW_112_EVENTS)
        + list(_NEW_113_EVENTS)
        + list(_NEW_114_EVENTS)
        + list(_EXISTING_111_EVENTS)
    ):
        assert event not in ALL_EVENTS


def test_existing_blueprint_events_frozen() -> None:
    """111 的 4 个常量字面值未被改名（并行纪律 3）。"""
    for actual, expected in _EXISTING_111_EVENTS.items():
        assert actual == expected
        assert actual in BLUEPRINT_EVENTS


def test_blueprint_events_shape() -> None:
    """集合恰好 21 个（111 的 4 + 112 的 11 + 113 的 3 + 114-03 的 3）、全 blueprint. 前缀、无重复。"""
    assert len(BLUEPRINT_EVENTS) == 21
    assert all(event.startswith("blueprint.") for event in BLUEPRINT_EVENTS)
    declared = (
        list(_NEW_112_EVENTS)
        + list(_NEW_113_EVENTS)
        + list(_NEW_114_EVENTS)
        + list(_EXISTING_111_EVENTS)
    )
    assert len(declared) == len(set(declared)) == 21

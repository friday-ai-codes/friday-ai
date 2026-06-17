"""PlanSessionEvent 持久化 + §15 信封 + best-effort 测试（EVENT-01，41-01 Task 2）。

覆盖：``_emit_event`` 持久化为 §15 信封行（work_item=None 与有 work_item 两情形）/
DB 写失败被吞不抛（best-effort）/ ``ALL_EVENTS`` 等于 §15 v0.7 编排事件名全集（逐一对账）。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from delivery.models import (
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionEvent,
    PlanSessionStatus,
    WorkItem,
    WorkItemOrigin,
)
from delivery.services import ALL_EVENTS
from delivery.services.plan_session_service import PlanSessionService


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_emit_event_persists_envelope_without_work_item() -> None:
    """无 work_item 的 session → 持久化一行 §15 信封，work_item=None。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.ROUTING
    )
    await PlanSessionService()._emit_event("repo.routing", session, {"candidates": []})

    rows = [e async for e in PlanSessionEvent.objects.filter(session_id=session.id)]
    assert len(rows) == 1
    row = rows[0]
    assert row.event == "repo.routing"
    assert row.payload == {"candidates": []}
    assert row.work_item is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_emit_event_persists_envelope_with_work_item() -> None:
    """有 work_item 的 session → 信封 work_item 与 session.work_item_id 一致。"""
    work_item = await WorkItem.objects.acreate(
        feishu_project_key="pk-evt",
        work_item_type="story",
        work_item_id=900001,
        origin=WorkItemOrigin.MANUAL,
        title="事件信封测试",
    )
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.RECALLING,
        work_item=work_item,
    )
    await PlanSessionService()._emit_event(
        "knowledge.recalling", session, {"query": "q", "hits": 0}
    )

    row = await PlanSessionEvent.objects.aget(session_id=session.id)
    assert row.event == "knowledge.recalling"
    assert row.payload == {"query": "q", "hits": 0}
    assert row.work_item == work_item.id


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_emit_event_best_effort_swallows_db_error() -> None:
    """DB 写失败（mock 注入）→ _emit_event 不抛、不冒泡（best-effort，T-41-01-02）。"""
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT, status=PlanSessionStatus.ROUTING
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    with patch.object(PlanSessionEvent.objects, "create", side_effect=_boom):
        # 绝不抛出（断言无异常冒泡）
        await PlanSessionService()._emit_event("repo.routing", session, {"x": 1})

    # 失败被吞 → 无行落库
    assert await PlanSessionEvent.objects.filter(session_id=session.id).acount() == 0


def test_all_events_equals_v07_orchestration_set() -> None:
    """ALL_EVENTS 逐一对账编排产出事件全集：v0.7 §15 基线 + v0.9 新增 spec.drafted（Phase 49）。

    （仍无 work_item.syncing / coding.wave.*——后者非 PlanSessionEvent 信封事件。）
    """
    assert ALL_EVENTS == frozenset(
        {
            "knowledge.recalling",
            "repo.routing",
            "repo.research.started",
            "repo.research.completed",
            "repo.research.failed",
            "clarification.asked",
            "clarification.answered",
            "plan.merge.started",
            "plan.merge.completed",
            "plan.validation.failed",
            "plan.session.failed",
            # v0.9 Phase 49：SDD 仓融合后产 spec draft 事件
            "spec.drafted",
        }
    )

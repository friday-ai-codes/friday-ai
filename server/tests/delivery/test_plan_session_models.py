"""PlanSession 模型测试（ORCH-02，DOMAIN §6/§12.7）。

覆盖默认态 / work_item SET_NULL / current_plan_version 软引用 / JSON 默认值。
"""

from __future__ import annotations

import uuid

import pytest

from delivery.models import (
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
    WorkItem,
    WorkItemOrigin,
)


@pytest.mark.django_db
def test_create_default_status_and_nullable_work_item() -> None:
    """可建 PlanSession：默认 status=decomposing、work_item=None 合法。"""
    session = PlanSession.objects.create(entrypoint=PlanSessionEntrypoint.CHAT)
    assert session.status == PlanSessionStatus.DECOMPOSING
    assert session.work_item is None
    assert session.decomposition == {}
    assert session.error == {}
    assert session.current_plan_version is None


@pytest.mark.django_db
def test_work_item_set_null_on_delete() -> None:
    """删 WorkItem 后 session.work_item_id 置 None，session 存活（SET_NULL，INV-2）。"""
    work_item = WorkItem.objects.create(
        feishu_project_key="pk",
        work_item_type="story",
        work_item_id=1001,
        origin=WorkItemOrigin.MANUAL,
    )
    session = PlanSession.objects.create(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        work_item=work_item,
    )
    work_item.delete()
    session.refresh_from_db()
    assert session.work_item_id is None
    assert PlanSession.objects.filter(id=session.id).exists()


@pytest.mark.django_db
def test_current_plan_version_soft_ref_and_json_defaults() -> None:
    """current_plan_version 可存 uuid4 软引用；decomposition/error 接受 JSON。"""
    pv_id = uuid.uuid4()
    session = PlanSession.objects.create(
        entrypoint=PlanSessionEntrypoint.CHAT,
        current_plan_version=pv_id,
        decomposition={"segments": ["frontend", "backend"]},
        error={"stage": "merging", "message": "boom"},
    )
    session.refresh_from_db()
    assert session.current_plan_version == pv_id
    assert session.decomposition == {"segments": ["frontend", "backend"]}
    assert session.error == {"stage": "merging", "message": "boom"}


@pytest.mark.django_db
def test_str_contains_entrypoint_and_status() -> None:
    session = PlanSession.objects.create(entrypoint=PlanSessionEntrypoint.WORKFLOW)
    rendered = str(session)
    assert "workflow" in rendered
    assert "decomposing" in rendered

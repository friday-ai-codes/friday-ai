"""canonical 方案模型守护测试（PLAN-01，DOMAIN §5.1 / §12.7）。

覆盖：INV-2 null work_item + 默认 draft / work_item SET_NULL / 版本链 unique_together /
PlanExternalRef unique + CASCADE / chat-mcp 软链字段为 UUIDField 非 relation。
"""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError, transaction

from delivery.models import (
    PlanExternalRef,
    PlanVersion,
    TechnicalPlan,
    TechnicalPlanOrigin,
    TechnicalPlanStatus,
    WorkItem,
    WorkItemOrigin,
)


@pytest.mark.django_db
def test_inv2_nullable_work_item_and_default_status() -> None:
    """INV-2：origin=chat 可建 work_item=None 方案；status 默认 draft。"""
    plan = TechnicalPlan.objects.create(origin=TechnicalPlanOrigin.CHAT)
    assert plan.work_item_id is None
    assert plan.origin == TechnicalPlanOrigin.CHAT
    assert plan.status == TechnicalPlanStatus.DRAFT
    assert plan.current_version_id is None


@pytest.mark.django_db
def test_work_item_set_null_on_delete() -> None:
    """删 WorkItem → plan.work_item_id 置 None、plan 存活（SET_NULL，INV-2）。"""
    work_item = WorkItem.objects.create(
        feishu_project_key="pk",
        work_item_type="story",
        work_item_id=2001,
        origin=WorkItemOrigin.MANUAL,
    )
    plan = TechnicalPlan.objects.create(
        origin=TechnicalPlanOrigin.WORKFLOW,
        work_item=work_item,
    )
    work_item.delete()
    plan.refresh_from_db()
    assert plan.work_item_id is None
    assert TechnicalPlan.objects.filter(id=plan.id).exists()


@pytest.mark.django_db
def test_version_chain_supersedes_and_unique_together() -> None:
    """版本链：v1 / v2(supersedes=v1)；同 (plan, version=1) 再 create → IntegrityError。"""
    plan = TechnicalPlan.objects.create(origin=TechnicalPlanOrigin.ORCHESTRATION)
    v1 = PlanVersion.objects.create(plan=plan, version=1, content={"a": 1})
    v2 = PlanVersion.objects.create(plan=plan, version=2, supersedes=v1, content={"a": 2})
    assert v2.supersedes_id == v1.id
    assert v2.superseded_by.count() == 0
    assert v1.superseded_by.first() == v2

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlanVersion.objects.create(plan=plan, version=1, content={"dup": True})


@pytest.mark.django_db
def test_plan_external_ref_unique_and_cascade() -> None:
    """PlanExternalRef.external_ref 唯一；删 canonical 级联删软链（CASCADE）。"""
    plan = TechnicalPlan.objects.create(origin=TechnicalPlanOrigin.WORKFLOW)
    ref = PlanExternalRef.objects.create(
        external_ref="workflow:exec-1:node-1",
        canonical=plan,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlanExternalRef.objects.create(
                external_ref="workflow:exec-1:node-1",
                canonical=plan,
            )

    plan.delete()
    assert not PlanExternalRef.objects.filter(id=ref.id).exists()


@pytest.mark.django_db
def test_soft_link_fields_are_uuid_non_relation() -> None:
    """chat/mcp 软链字段均为 UUIDField 且非关系字段（守护"软引用非硬 FK"）。"""
    from chat.models import CodingPlan
    from mcp_tools.models import McpWorkItemTechnicalPlan

    chat_field = CodingPlan._meta.get_field("canonical_plan_id")
    mcp_field = McpWorkItemTechnicalPlan._meta.get_field("canonical_plan_id")

    assert chat_field.get_internal_type() == "UUIDField"
    assert mcp_field.get_internal_type() == "UUIDField"
    assert chat_field.is_relation is False
    assert mcp_field.is_relation is False


@pytest.mark.django_db
def test_external_ref_accepts_distinct_refs() -> None:
    """不同 external_ref 可并存（unique 仅限同串）。"""
    plan = TechnicalPlan.objects.create(origin=TechnicalPlanOrigin.WORKFLOW)
    PlanExternalRef.objects.create(external_ref=f"workflow:{uuid.uuid4()}:n1", canonical=plan)
    PlanExternalRef.objects.create(external_ref=f"workflow:{uuid.uuid4()}:n2", canonical=plan)
    assert plan.external_refs.count() == 2

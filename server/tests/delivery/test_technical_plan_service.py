"""TechnicalPlanService 行为测试（PLAN-02，DOMAIN §5.2 / §5.4 / §13.2）。

覆盖 create_from（eager + INV-2 + 校验拦截）/ add_version（hash 复用 vs supersedes 链）/
archive（不级联）/ resolve（软链命中读 / lazy 建+回填 / PlanNotFound）/ link。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from delivery.models import (
    PlanVersion,
    TechnicalPlan,
    TechnicalPlanOrigin,
    TechnicalPlanStatus,
)
from delivery.services import (
    PlanContentInvalid,
    PlanNotFound,
    PlanRef,
    TechnicalPlanService,
)


def _valid_content(title: str = "标题") -> dict:
    """最小合法 content（满足 validate_technical_plan）。"""
    return {
        "title": title,
        "summary": "摘要",
        "execution_plan": [
            {
                "id": "t1",
                "name": "任务一",
                "repository_id": "repo-1",
                "repository_name": "repo",
                "branch_strategy": "feature",
            }
        ],
    }


async def _make_coding_plan(canonical_plan_id=None):
    from chat.models import CodingPlan, Conversation

    conv = await Conversation.objects.acreate()
    return await CodingPlan.objects.acreate(
        conversation=conv,
        tech_plan="一段技术方案文本",
        affected_files=[{"file_path": "a.py", "change_type": "modify"}],
        canonical_plan_id=canonical_plan_id,
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_from_eager_builds_plan_v1_current() -> None:
    svc = TechnicalPlanService()
    plan = await svc.create_from(
        origin=TechnicalPlanOrigin.ORCHESTRATION, payload={"content": _valid_content()}
    )
    assert plan.current_version_id is not None
    v1 = await PlanVersion.objects.aget(id=plan.current_version_id)
    assert v1.version == 1
    assert v1.content_hash != ""
    count = await sync_to_async(PlanVersion.objects.filter(plan=plan).count)()
    assert count == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_from_chat_nullable_work_item() -> None:
    """INV-2：origin=chat work_item=None 合法。"""
    svc = TechnicalPlanService()
    plan = await svc.create_from(
        origin=TechnicalPlanOrigin.CHAT, payload={"content": _valid_content()}, work_item=None
    )
    assert plan.work_item_id is None
    assert plan.origin == TechnicalPlanOrigin.CHAT


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_from_invalid_content_raises_no_write() -> None:
    svc = TechnicalPlanService()
    before = await sync_to_async(TechnicalPlan.objects.count)()
    with pytest.raises(PlanContentInvalid):
        await svc.create_from(
            origin=TechnicalPlanOrigin.CHAT, payload={"content": {"title": "缺字段"}}
        )
    after = await sync_to_async(TechnicalPlan.objects.count)()
    assert before == after


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_from_invalid_origin_raises() -> None:
    svc = TechnicalPlanService()
    with pytest.raises(ValueError):
        await svc.create_from(origin="bogus", payload={"content": _valid_content()})


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_add_version_same_hash_reuses_current() -> None:
    svc = TechnicalPlanService()
    content = _valid_content()
    plan = await svc.create_from(
        origin=TechnicalPlanOrigin.ORCHESTRATION, payload={"content": content}
    )
    v1_id = plan.current_version_id
    result = await svc.add_version(plan, content)
    assert result.id == v1_id
    count = await sync_to_async(PlanVersion.objects.filter(plan=plan).count)()
    assert count == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_add_version_diff_builds_supersedes_chain() -> None:
    svc = TechnicalPlanService()
    plan = await svc.create_from(
        origin=TechnicalPlanOrigin.ORCHESTRATION, payload={"content": _valid_content("v1")}
    )
    v1_id = plan.current_version_id
    v2 = await svc.add_version(plan, _valid_content("v2"))
    assert v2.version == 2
    assert v2.supersedes_id == v1_id
    reloaded = await TechnicalPlan.objects.aget(id=plan.id)
    assert reloaded.current_version_id == v2.id


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_archive_sets_status_no_cascade() -> None:
    svc = TechnicalPlanService()
    plan = await svc.create_from(
        origin=TechnicalPlanOrigin.CHAT, payload={"content": _valid_content()}
    )
    coding_plan = await _make_coding_plan()
    await svc.link(coding_plan, plan)

    archived = await svc.archive(plan)
    assert archived.status == TechnicalPlanStatus.ARCHIVED

    from chat.models import CodingPlan

    reloaded_cp = await CodingPlan.objects.aget(id=coding_plan.id)
    assert reloaded_cp.canonical_plan_id == plan.id
    pv_count = await sync_to_async(PlanVersion.objects.filter(plan=plan).count)()
    assert pv_count == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_resolve_chat_hit_reads_canonical_no_new() -> None:
    svc = TechnicalPlanService()
    canonical = await svc.create_from(
        origin=TechnicalPlanOrigin.CHAT, payload={"content": _valid_content()}
    )
    coding_plan = await _make_coding_plan(canonical_plan_id=canonical.id)
    before = await sync_to_async(TechnicalPlan.objects.count)()
    resolved = await svc.resolve(PlanRef.for_chat(coding_plan.id))
    after = await sync_to_async(TechnicalPlan.objects.count)()
    assert resolved.id == canonical.id
    assert before == after


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_resolve_chat_miss_lazy_creates_and_backfills() -> None:
    svc = TechnicalPlanService()
    coding_plan = await _make_coding_plan(canonical_plan_id=None)
    resolved = await svc.resolve(PlanRef.for_chat(coding_plan.id))
    assert resolved.origin == TechnicalPlanOrigin.CHAT

    from chat.models import CodingPlan

    reloaded = await CodingPlan.objects.aget(id=coding_plan.id)
    assert reloaded.canonical_plan_id == resolved.id


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_resolve_unknown_source_raises_not_found() -> None:
    import uuid

    svc = TechnicalPlanService()
    with pytest.raises(PlanNotFound):
        await svc.resolve(PlanRef.for_chat(uuid.uuid4()))


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_resolve_non_uuid_source_raises_not_found() -> None:
    """IN-01：非 UUID source_key 归一化为 PlanNotFound（不外泄 ValueError）。"""
    svc = TechnicalPlanService()
    with pytest.raises(PlanNotFound):
        await svc.resolve(PlanRef.for_chat("not-a-uuid"))
    with pytest.raises(PlanNotFound):
        await svc.resolve(PlanRef.for_mcp("also-not-a-uuid"))

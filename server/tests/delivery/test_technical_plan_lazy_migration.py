"""read-time lazy migration 测试（PLAN-03，DOMAIN §5.3 / §5.4）。

覆盖三路径 lazy 建 canonical + 回填软链 / 幂等再 resolve 不重建 / 冲突以 canonical 为准 /
归档不级联删旧表 / lazy 取材产物过 validate。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async

from delivery.models import (
    PlanVersion,
    TechnicalPlan,
    TechnicalPlanOrigin,
    TechnicalPlanStatus,
)
from delivery.services import PlanNotFound, PlanRef, TechnicalPlanService


async def _make_chat_plan(*, canonical_plan_id=None, repo_ids=None, affected=None):
    from chat.models import CodingPlan, Conversation

    conv = await Conversation.objects.acreate()
    return await CodingPlan.objects.acreate(
        conversation=conv,
        title="chat 方案",
        tech_plan="实现 X 功能并修改若干文件",
        affected_files=affected or [{"file_path": "a.py", "change_type": "add"}],
        recommended_repository_ids=repo_ids or [],
        canonical_plan_id=canonical_plan_id,
    )


async def _make_mcp_plan(*, plan_body=None, repository_tasks=None, canonical_plan_id=None):
    from interactions.models import InteractionRun
    from mcp_tools.models import McpWorkItemContext, McpWorkItemTechnicalPlan

    run = await InteractionRun.objects.acreate(source="test")
    ctx = await McpWorkItemContext.objects.acreate(
        run=run,
        feishu_project_key="pk",
        work_item_type="story",
        work_item_id=3001,
    )
    return await McpWorkItemTechnicalPlan.objects.acreate(
        run=run,
        context=ctx,
        feishu_project_key="pk",
        work_item_type="story",
        work_item_id=3001,
        title="mcp 方案标题",
        markdown="一段 markdown 方案说明",
        plan_body=plan_body or {},
        repository_tasks=repository_tasks or [],
        canonical_plan_id=canonical_plan_id,
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_lazy_chat_builds_canonical_and_backfills() -> None:
    svc = TechnicalPlanService()
    chat_plan = await _make_chat_plan(repo_ids=[str(uuid.uuid4()), str(uuid.uuid4())])
    canonical = await svc.resolve(PlanRef.for_chat(chat_plan.id))

    assert canonical.origin == TechnicalPlanOrigin.CHAT
    assert canonical.work_item_id is None

    from chat.models import CodingPlan

    reloaded = await CodingPlan.objects.aget(id=chat_plan.id)
    assert reloaded.canonical_plan_id == canonical.id
    # 取材忠实：每个推荐仓库一个 task（content 已过 validate 才能落库）
    v1 = await PlanVersion.objects.aget(id=canonical.current_version_id)
    assert len(v1.content["execution_plan"]) == 2


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_lazy_mcp_builds_canonical_and_backfills() -> None:
    svc = TechnicalPlanService()
    mcp_plan = await _make_mcp_plan(
        repository_tasks=[
            {"repository_id": "r1", "repository_name": "repo-a", "name": "改 A"},
            {"repository_id": "r2", "repository_name": "repo-b", "branch_strategy": "weird"},
        ]
    )
    canonical = await svc.resolve(PlanRef.for_mcp(mcp_plan.id))

    assert canonical.origin == TechnicalPlanOrigin.MCP

    from mcp_tools.models import McpWorkItemTechnicalPlan

    reloaded = await McpWorkItemTechnicalPlan.objects.aget(id=mcp_plan.id)
    assert reloaded.canonical_plan_id == canonical.id
    v1 = await PlanVersion.objects.aget(id=canonical.current_version_id)
    tasks = v1.content["execution_plan"]
    assert len(tasks) == 2
    # 非法 branch_strategy 归一化为 feature
    assert tasks[1]["branch_strategy"] == "feature"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_lazy_workflow_link_then_resolve_hit_else_not_found() -> None:
    svc = TechnicalPlanService()
    ref = PlanRef.for_workflow(uuid.uuid4(), "node-1")

    # 未 link → PlanNotFound
    with pytest.raises(PlanNotFound):
        await svc.resolve(ref)

    # eager：调用方先 create_from + link，再 resolve 命中
    canonical = await svc.create_from(
        origin=TechnicalPlanOrigin.WORKFLOW,
        payload={
            "content": {
                "title": "wf",
                "summary": "s",
                "execution_plan": [
                    {
                        "id": "w1",
                        "name": "t",
                        "repository_id": "r",
                        "repository_name": "repo",
                        "branch_strategy": "feature",
                    }
                ],
            }
        },
    )
    await svc.link(ref.source_key, canonical)
    resolved = await svc.resolve(ref)
    assert resolved.id == canonical.id


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_resolve_idempotent_no_rebuild() -> None:
    svc = TechnicalPlanService()
    chat_plan = await _make_chat_plan()
    first = await svc.resolve(PlanRef.for_chat(chat_plan.id))
    count_after_first = await sync_to_async(TechnicalPlan.objects.count)()
    second = await svc.resolve(PlanRef.for_chat(chat_plan.id))
    count_after_second = await sync_to_async(TechnicalPlan.objects.count)()

    assert first.id == second.id
    # 第二次 resolve 走软链命中分支，绝不新建（计数不增）
    assert count_after_first == count_after_second
    assert count_after_first >= 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_conflict_canonical_wins() -> None:
    svc = TechnicalPlanService()
    chat_plan = await _make_chat_plan()
    canonical = await svc.resolve(PlanRef.for_chat(chat_plan.id))

    # canonical 分叉：add_version 改 content（与旧记录不一致）
    await svc.add_version(
        canonical,
        {
            "title": "冲突新标题",
            "summary": "新摘要",
            "execution_plan": [
                {
                    "id": "n1",
                    "name": "新任务",
                    "repository_id": "r",
                    "repository_name": "repo",
                    "branch_strategy": "feature",
                }
            ],
        },
    )
    # 再 resolve 仍读 canonical 的最新 current_version（冲突以 canonical 为准）
    resolved = await svc.resolve(PlanRef.for_chat(chat_plan.id))
    cur = await PlanVersion.objects.aget(id=resolved.current_version_id)
    assert resolved.id == canonical.id
    assert cur.content["title"] == "冲突新标题"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_archive_no_cascade_keeps_old_record_and_link() -> None:
    svc = TechnicalPlanService()
    chat_plan = await _make_chat_plan()
    canonical = await svc.resolve(PlanRef.for_chat(chat_plan.id))

    await svc.archive(canonical)

    from chat.models import CodingPlan

    reloaded = await CodingPlan.objects.aget(id=chat_plan.id)
    assert reloaded.canonical_plan_id == canonical.id
    archived = await TechnicalPlan.objects.aget(id=canonical.id)
    assert archived.status == TechnicalPlanStatus.ARCHIVED
    pv_count = await sync_to_async(PlanVersion.objects.filter(plan=canonical).count)()
    assert pv_count >= 1

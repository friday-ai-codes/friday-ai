"""ProjectWorkItemLink 组合关系守护测试（COMPOSE-01/02）。

覆盖：attach get_or_create 幂等、board_derived + manual 并存、detach 幂等、story 与缺陷
统一复用 delivery.WorkItem 同表挂入不重复建模。async + sync_to_async ORM 写库需
transaction=True（与 delivery/Phase 77 范式一致）。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from delivery.services import WorkItemIdentity, WorkItemService
from initiatives.models import LinkProvenance, ProjectWorkItemLink
from initiatives.services import ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_space(key="link-key") -> Space:
    return Space.objects.create(name="S", feishu_project_key=key)


@sync_to_async
def _make_user(username="u") -> object:
    return User.objects.create_user(username=username, password="x")


async def _make_work_item(work_item_id: int, work_item_type: str = "story"):
    """经 WorkItemService（INV-6 单一入口）落 canonical WorkItem，不回源（fetch=False）。"""
    return await WorkItemService().upsert(
        WorkItemIdentity(
            feishu_project_key="wpk",
            work_item_type=work_item_type,
            work_item_id=work_item_id,
        ),
        source="feishu_webhook",
        fetch=False,
    )


async def _make_project():
    space = await _make_space()
    user = await _make_user()
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="link-board", created_by=user
    )
    return project


async def test_attach_idempotent() -> None:
    project = await _make_project()
    wi = await _make_work_item(101)
    _, c1 = await ProjectService().attach_work_item(project_id=project.id, work_item=wi)
    _, c2 = await ProjectService().attach_work_item(project_id=project.id, work_item=wi)
    assert c1 is True and c2 is False
    assert (
        await ProjectWorkItemLink.objects.filter(project=project, work_item=wi).acount()
        == 1
    )


async def test_board_derived_and_manual_coexist() -> None:
    project = await _make_project()
    wi_auto = await _make_work_item(201)
    wi_manual = await _make_work_item(202)
    await ProjectService().attach_work_item(
        project_id=project.id, work_item=wi_auto, provenance=LinkProvenance.BOARD_DERIVED
    )
    await ProjectService().attach_work_item(
        project_id=project.id, work_item=wi_manual, provenance=LinkProvenance.MANUAL
    )
    assert await ProjectWorkItemLink.objects.filter(project=project).acount() == 2
    auto = await ProjectWorkItemLink.objects.aget(project=project, work_item=wi_auto)
    assert auto.provenance == LinkProvenance.BOARD_DERIVED


async def test_detach_idempotent() -> None:
    project = await _make_project()
    wi = await _make_work_item(301)
    await ProjectService().attach_work_item(project_id=project.id, work_item=wi)
    removed = await ProjectService().detach_work_item(
        project_id=project.id, work_item_id=wi.id
    )
    assert removed is True
    # 再次移除：原本未关联 → False（幂等不抛）
    removed_again = await ProjectService().detach_work_item(
        project_id=project.id, work_item_id=wi.id
    )
    assert removed_again is False
    assert await ProjectWorkItemLink.objects.filter(project=project).acount() == 0


async def test_story_and_defect_both_link_without_remodeling() -> None:
    """COMPOSE-02：story 与缺陷统一复用 delivery.WorkItem，同表挂入不重复建模。"""
    project = await _make_project()
    story = await _make_work_item(401, work_item_type="story")
    defect = await _make_work_item(402, work_item_type="issue")
    await ProjectService().attach_work_item(project_id=project.id, work_item=story)
    await ProjectService().attach_work_item(project_id=project.id, work_item=defect)
    # 两者都经同一 ProjectWorkItemLink 挂入，无独立缺陷建模
    types = {
        link.work_item.work_item_type
        async for link in ProjectWorkItemLink.objects.filter(
            project=project
        ).select_related("work_item")
    }
    assert types == {"story", "issue"}
    assert await project.work_items.acount() == 2

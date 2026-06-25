"""MemoryService 守护测试（Phase 80，MEM-01~04）：

- append/edit（revision 历史保留）/supersede
- 成员校验 fail-closed（非成员拒绝）
- 草稿 create/confirm/reject（confirm 入库 active；reject 不入库）
- 脱敏（凭证不落明文）
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import (
    DraftStatus,
    ProjectMemory,
    ProjectMemoryRevision,
    ProjectMemoryStatus,
)
from initiatives.services import (
    MemoryPermissionError,
    MemoryService,
    ProjectService,
)
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@sync_to_async
def _make_user(username):
    return User.objects.create_user(username=username, password="x")


async def _make_project_with_member():
    space = await sync_to_async(Space.objects.create)(name="S")
    owner = await _make_user("owner")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="mem-k", created_by=owner
    )
    return project, owner


@sync_to_async
def _rev_count(memory_id):
    return ProjectMemoryRevision.objects.filter(memory_id=memory_id).count()


async def test_append_creates_active_memory_with_initial_revision():
    project, owner = await _make_project_with_member()
    memory = await MemoryService().append(
        project_id=project.id, content="决策：用 PG 连接池", contributor=owner
    )
    assert memory.status == ProjectMemoryStatus.ACTIVE
    assert await _rev_count(memory.id) == 1


async def test_edit_preserves_history_via_revisions():
    project, owner = await _make_project_with_member()
    memory = await MemoryService().append(
        project_id=project.id, content="v1 内容", contributor=owner
    )
    await MemoryService().edit(memory_id=memory.id, content="v2 内容", editor=owner)
    refreshed = await ProjectMemory.objects.aget(pk=memory.id)
    assert refreshed.content == "v2 内容"
    # 历史保留：初始 + 编辑各一条 revision（append-only，不就地丢历史）。
    assert await _rev_count(memory.id) == 2
    contents = await sync_to_async(
        lambda: list(
            ProjectMemoryRevision.objects.filter(memory_id=memory.id)
            .order_by("edited_at")
            .values_list("content", flat=True)
        )
    )()
    assert contents == ["v1 内容", "v2 内容"]


async def test_supersede_marks_status():
    project, owner = await _make_project_with_member()
    memory = await MemoryService().append(
        project_id=project.id, content="x", contributor=owner
    )
    await MemoryService().supersede(memory_id=memory.id, actor=owner)
    refreshed = await ProjectMemory.objects.aget(pk=memory.id)
    assert refreshed.status == ProjectMemoryStatus.SUPERSEDED


async def test_non_member_cannot_contribute_fail_closed():
    project, _owner = await _make_project_with_member()
    stranger = await _make_user("stranger")
    with pytest.raises(MemoryPermissionError):
        await MemoryService().append(
            project_id=project.id, content="偷写", contributor=stranger
        )
    # 非成员编辑同样拒绝。
    member_memory = await MemoryService().append(
        project_id=project.id, content="ok", contributor=_owner
    )
    with pytest.raises(MemoryPermissionError):
        await MemoryService().edit(
            memory_id=member_memory.id, content="篡改", editor=stranger
        )


async def test_redaction_applied_on_store():
    project, owner = await _make_project_with_member()
    memory = await MemoryService().append(
        project_id=project.id,
        content="token=sk-ant-abc123secretvalue1234567890 用于调用",
        contributor=owner,
    )
    refreshed = await ProjectMemory.objects.aget(pk=memory.id)
    assert "sk-ant-abc123secretvalue1234567890" not in refreshed.content
    assert "REDACTED" in refreshed.content


async def test_draft_create_confirm_enters_active_memory():
    project, owner = await _make_project_with_member()
    draft = await MemoryService().create_draft(
        project_id=project.id, content="候选记忆", proposed_by=owner
    )
    assert draft.status == DraftStatus.PENDING
    # 确认前无 active 记忆。
    assert await ProjectMemory.objects.filter(project_id=project.id).acount() == 0
    memory = await MemoryService().confirm_draft(draft_id=draft.id, confirmer=owner)
    assert memory.status == ProjectMemoryStatus.ACTIVE
    refreshed_draft = await sync_to_async(
        lambda: type(draft).objects.get(pk=draft.id)
    )()
    assert refreshed_draft.status == DraftStatus.CONFIRMED
    assert refreshed_draft.confirmed_memory_id == memory.id


async def test_draft_reject_does_not_create_memory():
    project, owner = await _make_project_with_member()
    draft = await MemoryService().create_draft(
        project_id=project.id, content="候选", proposed_by=owner
    )
    await MemoryService().reject_draft(draft_id=draft.id, actor=owner)
    refreshed = await sync_to_async(lambda: type(draft).objects.get(pk=draft.id))()
    assert refreshed.status == DraftStatus.REJECTED
    assert await ProjectMemory.objects.filter(project_id=project.id).acount() == 0


async def test_non_member_cannot_confirm_draft():
    project, owner = await _make_project_with_member()
    stranger = await _make_user("stranger2")
    draft = await MemoryService().create_draft(
        project_id=project.id, content="候选", proposed_by=owner
    )
    with pytest.raises(MemoryPermissionError):
        await MemoryService().confirm_draft(draft_id=draft.id, confirmer=stranger)

"""MemoryDistiller 守护测试（Phase 80，MEM-04）：

- LLM 提炼仅产 pending 草稿（绝不自动写 active）
- 脱敏入库
- 成员校验 fail-closed
- NONE 返回不产草稿
- call_source 受控为 memory_distill
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from agents.call_source import CallSource
from initiatives.models import DraftStatus, ProjectMemory, ProjectMemoryDraft
from initiatives.services import MemoryDistiller, MemoryPermissionError, ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

_DISTILL_PATH = "initiatives.services.memory_distill.MemoryDistiller._acall_llm"


@sync_to_async
def _make_user(username):
    return User.objects.create_user(username=username, password="x")


async def _make_project_with_member():
    space = await sync_to_async(Space.objects.create)(name="S")
    owner = await _make_user("owner")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="d-k", created_by=owner
    )
    return project, owner


async def test_distill_produces_pending_draft_only():
    project, owner = await _make_project_with_member()
    with patch(_DISTILL_PATH, new=AsyncMock(return_value="决策：缓存用 redis")):
        draft = await MemoryDistiller().distill_to_draft(
            project_id=project.id,
            conversation_text="user: 缓存怎么选\nassistant: 用 redis",
            proposed_by=owner,
        )
    assert draft is not None
    assert draft.status == DraftStatus.PENDING
    # 绝不自动写 active 记忆。
    assert await ProjectMemory.objects.filter(project_id=project.id).acount() == 0
    assert await ProjectMemoryDraft.objects.filter(project_id=project.id).acount() == 1


async def test_distill_redacts_secret_before_store():
    project, owner = await _make_project_with_member()
    leak = "记住 token=sk-ant-abcd1234secretvalue9876543210"
    with patch(_DISTILL_PATH, new=AsyncMock(return_value=leak)):
        draft = await MemoryDistiller().distill_to_draft(
            project_id=project.id,
            conversation_text="...",
            proposed_by=owner,
        )
    assert draft is not None
    assert "sk-ant-abcd1234secretvalue9876543210" not in draft.content
    assert "REDACTED" in draft.content


async def test_distill_none_candidate_no_draft():
    project, owner = await _make_project_with_member()
    with patch(_DISTILL_PATH, new=AsyncMock(return_value="NONE")):
        draft = await MemoryDistiller().distill_to_draft(
            project_id=project.id,
            conversation_text="闲聊",
            proposed_by=owner,
        )
    assert draft is None
    assert await ProjectMemoryDraft.objects.filter(project_id=project.id).acount() == 0


async def test_distill_non_member_fail_closed():
    project, _owner = await _make_project_with_member()
    stranger = await _make_user("stranger")
    with patch(_DISTILL_PATH, new=AsyncMock(return_value="x")):
        with pytest.raises(MemoryPermissionError):
            await MemoryDistiller().distill_to_draft(
                project_id=project.id,
                conversation_text="...",
                proposed_by=stranger,
            )


def test_memory_distill_call_source_in_enum():
    """memory_distill 已纳入受控 call_source 枚举（LOGGING-SPEC §4.1）。"""
    assert CallSource.normalize("memory_distill") == CallSource.MEMORY_DISTILL.value

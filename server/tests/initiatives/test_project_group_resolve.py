"""ProjectService.resolve_or_create_group 守护测试（Phase 87，BOARD-02，87-04）。

覆盖：
- 复用：project 已有 feishu_chat_id → 直接返回，不调 create_chat（断言 mock 未被调）。
- 新建：无群 → create_chat + ensure_bot_in_chat + writeback 持久化 chat_id。
- fail-soft：create_chat 抛 → 返回 ""（不冒泡）。

async + sync_to_async ORM 写库需 transaction=True（与 ProjectService 范式一致）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import Project
from initiatives.services import ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

_IM_CLS = "services.feishu_im.FeishuIMService"


@sync_to_async
def _make_space(key="grp-key") -> Space:
    return Space.objects.create(name="S", feishu_project_key=key)


@sync_to_async
def _make_project(space: Space, *, chat_id: str = "") -> Project:
    return Project.objects.create(
        space=space, name="P", feishu_project_key="board-1", feishu_chat_id=chat_id
    )


def _mock_service(*, create_chat_return=None, create_chat_exc=None) -> MagicMock:
    svc = MagicMock()
    if create_chat_exc is not None:
        svc.create_chat = AsyncMock(side_effect=create_chat_exc)
    else:
        svc.create_chat = AsyncMock(return_value=create_chat_return or {"chat_id": "oc_new"})
    svc.ensure_bot_in_chat = AsyncMock(
        return_value={"success": True, "already_member": False, "error": None}
    )
    return svc


async def test_reuse_existing_group_skips_create() -> None:
    space = await _make_space()
    project = await _make_project(space, chat_id="oc_existing")

    svc = _mock_service()
    with patch(f"{_IM_CLS}.create", AsyncMock(return_value=svc)) as mock_create:
        chat_id = await ProjectService().resolve_or_create_group(
            project=project, member_ids=["ou_a"]
        )

    assert chat_id == "oc_existing"
    mock_create.assert_not_awaited()
    svc.create_chat.assert_not_awaited()


async def test_create_new_group_writes_back_chat_id() -> None:
    space = await _make_space()
    project = await _make_project(space)

    svc = _mock_service(create_chat_return={"chat_id": "oc_new"})
    with patch(f"{_IM_CLS}.create", AsyncMock(return_value=svc)):
        chat_id = await ProjectService().resolve_or_create_group(
            project=project, member_ids=["ou_a", "ou_b"], initiated_by_user_id="u1"
        )

    assert chat_id == "oc_new"
    svc.create_chat.assert_awaited_once()
    svc.ensure_bot_in_chat.assert_awaited_once_with("oc_new")
    # writeback 持久化
    reloaded = await Project.objects.aget(pk=project.id)
    assert reloaded.feishu_chat_id == "oc_new"


async def test_create_chat_failure_returns_empty_failsoft() -> None:
    space = await _make_space()
    project = await _make_project(space)

    svc = _mock_service(create_chat_exc=RuntimeError("boom"))
    with patch(f"{_IM_CLS}.create", AsyncMock(return_value=svc)):
        chat_id = await ProjectService().resolve_or_create_group(
            project=project, member_ids=["ou_a"]
        )

    assert chat_id == ""
    reloaded = await Project.objects.aget(pk=project.id)
    assert reloaded.feishu_chat_id == ""


def test_resolve_or_create_group_reuses_in_memory_value() -> None:
    """非 DB 路径：传入已带 feishu_chat_id 的对象即复用（不触 ORM）。"""
    import asyncio

    project = SimpleNamespace(id="pid", name="P", feishu_chat_id="oc_mem")
    svc = _mock_service()
    with patch(f"{_IM_CLS}.create", AsyncMock(return_value=svc)) as mock_create:
        result = asyncio.run(
            ProjectService().resolve_or_create_group(project=project, member_ids=[])
        )
    assert result == "oc_mem"
    mock_create.assert_not_awaited()

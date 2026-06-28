"""ProjectDocService 守护测试（82-02 Task 2/3）。

覆盖：
- 三模型写入 + 幂等（upsert_doc / upsert_state_api / upsert_block_map / set_sync_status /
  remove_state_api）。
- ProjectService.set_folder_token 落字段 + 审计。
- provision happy（5 doc READY + folder_token 落 Project + 看板追加一次 + 互链 append）。
- provision broken（单文件 create_document 抛 → 对应 doc broken 持久化，其余继续，coro 不抛）。
- 看板描述 read-then-append 幂等（已含 marker 不再 update）。
- 静态守护：provision 编排串行（无 asyncio.gather）、脱敏 helper 在用、日志无 token/正文明文。

async + sync_to_async ORM 写库需 ``transaction=True``（与 delivery/Project 范式一致）。
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import (
    ApiStatus,
    DocSyncStatus,
    DocType,
    Project,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectStateApi,
)
from initiatives.services import ProjectDocService, ProjectService
from projects.models import Space
from services.feishu_doc import FeishuDocAPIError

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

_SERVICE_FILE = (
    Path(__file__).resolve().parents[2]
    / "initiatives"
    / "services"
    / "project_doc_service.py"
)


@sync_to_async
def _make_space(folder: str = "fldcnPARENT", key: str = "bk") -> Space:
    return Space.objects.create(
        name="S", feishu_project_key=key, feishu_doc_folder_token=folder
    )


@sync_to_async
def _make_user(username: str = "creator") -> object:
    return User.objects.create_user(username=username, password="x")


async def _make_project(space: Space, **kw: object) -> Project:
    """建项目并抑制真实后台 provision 派发（测试内显式调 coro 验证编排）。"""
    user = await _make_user(username=f"u-{kw.get('feishu_project_key', 'm')}")
    with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
        project, _ = await ProjectService().create(
            space=space, name="P", created_by=user, **kw
        )
    return project


def _make_doc_client() -> AsyncMock:
    client = AsyncMock()
    client.create_folder = AsyncMock(return_value="fldcnNEW")

    def _create_doc(*, title: str, folder_token: str, content: str) -> dict:
        return {"document_id": f"doc-{title[-4:]}", "url": "https://feishu.cn/docx/x"}

    client.create_document = AsyncMock(side_effect=_create_doc)
    client.append_markdown = AsyncMock(return_value={})
    return client


def _make_board_client(description: str = "") -> AsyncMock:
    board = AsyncMock()
    info = MagicMock()
    info.description = description
    board.get_work_item = AsyncMock(return_value=info)
    board.update_work_item_fields = AsyncMock(return_value=True)
    return board


# ---- 写入 + 幂等 ----


async def test_upsert_doc_idempotent_by_project_doc_type() -> None:
    space = await _make_space(key="d1")
    project = await _make_project(space, feishu_project_key="d1")
    svc = ProjectDocService()
    await svc.upsert_doc(project_id=project.id, doc_type=DocType.MEMORY)
    await svc.upsert_doc(
        project_id=project.id, doc_type=DocType.MEMORY, sync_status=DocSyncStatus.READY
    )
    count = await ProjectDoc.objects.filter(
        project_id=project.id, doc_type=DocType.MEMORY
    ).acount()
    assert count == 1
    doc = await ProjectDoc.objects.aget(project_id=project.id, doc_type=DocType.MEMORY)
    assert doc.sync_status == DocSyncStatus.READY


async def test_upsert_state_api_idempotent_and_audited() -> None:
    space = await _make_space(key="d2")
    project = await _make_project(space, feishu_project_key="d2")
    svc = ProjectDocService()
    api1, created1 = await svc.upsert_state_api(
        project_id=project.id, method="GET", path="/x", status=ApiStatus.PLANNED
    )
    api2, created2 = await svc.upsert_state_api(
        project_id=project.id, method="GET", path="/x"
    )
    assert created1 is True and created2 is False
    assert api1.id == api2.id
    assert await ProjectStateApi.objects.filter(project_id=project.id).acount() == 1
    assert await AuditEvent.objects.filter(
        action=taxonomy.ACTION_PROJECT_STATE_API_ADDED, target_id=str(api1.id)
    ).aexists()


async def test_remove_state_api_idempotent() -> None:
    space = await _make_space(key="d3")
    project = await _make_project(space, feishu_project_key="d3")
    svc = ProjectDocService()
    api, _ = await svc.upsert_state_api(project_id=project.id, method="POST", path="/y")
    removed = await svc.remove_state_api(project_id=project.id, api_id=api.id)
    assert removed is True
    again = await svc.remove_state_api(project_id=project.id, api_id=api.id)
    assert again is False
    assert await AuditEvent.objects.filter(
        action=taxonomy.ACTION_PROJECT_STATE_API_REMOVED
    ).aexists()


async def test_upsert_block_map_idempotent() -> None:
    space = await _make_space(key="d4")
    project = await _make_project(space, feishu_project_key="d4")
    svc = ProjectDocService()
    doc = await svc.upsert_doc(project_id=project.id, doc_type=DocType.STATE)
    await svc.upsert_block_map(doc_id=doc.id, feishu_block_id="blk1", db_ref="ref-a")
    await svc.upsert_block_map(doc_id=doc.id, feishu_block_id="blk1", db_ref="ref-b")
    count = await ProjectDocBlockMap.objects.filter(doc_id=doc.id).acount()
    assert count == 1
    block = await ProjectDocBlockMap.objects.aget(doc_id=doc.id, feishu_block_id="blk1")
    assert block.db_ref == "ref-b"


async def test_set_folder_token_persists_and_audits() -> None:
    space = await _make_space(key="d5")
    project = await _make_project(space, feishu_project_key="d5")
    await ProjectService().set_folder_token(project_id=project.id, token="fldcnZZZ")
    refreshed = await Project.objects.aget(pk=project.id)
    assert refreshed.feishu_folder_token == "fldcnZZZ"
    assert await AuditEvent.objects.filter(
        action=taxonomy.ACTION_PROJECT_WORKSPACE_PROVISIONED, target_id=str(project.id)
    ).aexists()


# ---- provision 编排 ----


async def test_provision_happy_path() -> None:
    space = await _make_space(key="p1")
    project = await _make_project(
        space, feishu_project_key="p1", feishu_board_id="12345"
    )
    client = _make_doc_client()
    board = _make_board_client(description="")
    with (
        patch.object(ProjectDocService, "_build_doc_client", AsyncMock(return_value=client)),
        patch.object(ProjectDocService, "_build_board_client", AsyncMock(return_value=board)),
    ):
        await ProjectDocService()._provision_workspace_coro(
            project.id, initiated_by_user_id="1"
        )

    ready = await ProjectDoc.objects.filter(
        project_id=project.id, sync_status=DocSyncStatus.READY
    ).acount()
    assert ready == 5
    refreshed = await Project.objects.aget(pk=project.id)
    assert refreshed.feishu_folder_token == "fldcnNEW"
    # 互链：每文档一次 append_markdown
    assert client.append_markdown.await_count == 5
    # 看板描述追加一次
    board.update_work_item_fields.assert_awaited_once()
    client.create_folder.assert_awaited_once()


async def test_provision_broken_path_marks_doc_and_continues() -> None:
    space = await _make_space(key="p2")
    project = await _make_project(space, feishu_project_key="p2")
    client = _make_doc_client()
    # 第二个文件（state）建文档抛错，其余成功
    client.create_document = AsyncMock(
        side_effect=[
            {"document_id": "doc-1", "url": "u"},
            FeishuDocAPIError("boom"),
            {"document_id": "doc-3", "url": "u"},
            {"document_id": "doc-4", "url": "u"},
            {"document_id": "doc-5", "url": "u"},
        ]
    )
    board = _make_board_client()
    with (
        patch.object(ProjectDocService, "_build_doc_client", AsyncMock(return_value=client)),
        patch.object(ProjectDocService, "_build_board_client", AsyncMock(return_value=board)),
    ):
        # coro 绝不抛（fail-soft）
        await ProjectDocService()._provision_workspace_coro(project.id)

    state_doc = await ProjectDoc.objects.aget(
        project_id=project.id, doc_type=DocType.STATE
    )
    assert state_doc.sync_status == DocSyncStatus.BROKEN
    ready = await ProjectDoc.objects.filter(
        project_id=project.id, sync_status=DocSyncStatus.READY
    ).acount()
    assert ready == 4
    # 非全就绪 → 不互链、不追加看板
    client.append_markdown.assert_not_awaited()
    board.update_work_item_fields.assert_not_awaited()


async def test_provision_no_feishu_creates_local_pending_docs() -> None:
    """#3：未配置飞书（无父文件夹）→ 建 5 个本地「待同步」(pending) 文档，不报 broken、不同步。"""
    space = await _make_space(folder="", key="p3")
    project = await _make_project(space, feishu_project_key="p3")
    await ProjectDocService()._provision_workspace_coro(project.id)
    pending = await ProjectDoc.objects.filter(
        project_id=project.id, sync_status=DocSyncStatus.PENDING
    ).acount()
    broken = await ProjectDoc.objects.filter(
        project_id=project.id, sync_status=DocSyncStatus.BROKEN
    ).acount()
    assert pending == 5
    assert broken == 0


async def test_provision_board_append_idempotent_when_marker_present() -> None:
    space = await _make_space(key="p4")
    project = await _make_project(
        space, feishu_project_key="p4", feishu_board_id="999"
    )
    client = _make_doc_client()
    # 看板描述已含 marker → 不再 update（幂等）
    board = _make_board_client(description="原有描述\n\n📁 项目工作区\n- ...")
    with (
        patch.object(ProjectDocService, "_build_doc_client", AsyncMock(return_value=client)),
        patch.object(ProjectDocService, "_build_board_client", AsyncMock(return_value=board)),
    ):
        await ProjectDocService()._provision_workspace_coro(project.id)
    board.get_work_item.assert_awaited_once()
    board.update_work_item_fields.assert_not_awaited()


# ---- 静态守护 ----


def test_provision_is_serial_no_gather() -> None:
    text = _SERVICE_FILE.read_text(encoding="utf-8")
    # 只禁真实调用 `asyncio.gather(`（注释里提及不算）。
    assert "asyncio.gather(" not in text, "provision 须串行（5QPS/不可并发），不得用 asyncio.gather"


def test_provision_redacts_upstream_text() -> None:
    text = _SERVICE_FILE.read_text(encoding="utf-8")
    assert "redact_secrets_in_text" in text, "飞书上游响应体/异常文本入日志前须脱敏"


def test_provision_logs_no_token_or_content_plaintext() -> None:
    """provision 路径日志只记 doc_id/doc_type/计数/sync_status，绝不记 token/正文明文。"""
    text = _SERVICE_FILE.read_text(encoding="utf-8")
    forbidden = re.compile(r"logger\.(?:info|warning)\([^)]*(?:content=|feishu_doc_token=|doc_token=)")
    assert not forbidden.search(text), "日志不得落飞书 token / 文档正文明文"

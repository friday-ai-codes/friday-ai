"""DocSyncService.pull 回拉流水线单测（83-02 / SYNC-01），respx mock 飞书回拉、不碰真机。

覆盖 must_haves：
- 回拉正文 → doc_sync_diff 分类 → 写收口（MEMORY 经 MemoryService / 其余经 ProjectDocService）
  → CAS 推进 last_synced_revision → 失效渲染缓存。
- 归因：initiated_by_user_id 落 MEMORY contributor（未映射 system → contributor None）。
- 编辑（非 MEMORY）→ capture_block_revision 留痕（never-drop）+ 推进 block_map 指纹。
- fail-soft：项目归档跳过（不回拉）；回拉 not-found 置 broken 不抛；doc 找不到跳过。

飞书事件/回拉真实形态（A1/A5）为 [ASSUMED]，本测试以构造 blocks 覆盖，真机校验记 83-UAT.md。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import (
    DocSyncStatus,
    DocType,
    Project,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectDocBlockRevision,
    ProjectMemory,
    ProjectStatus,
)
from initiatives.services.doc_sync_diff import block_content_hash
from initiatives.services.doc_sync_service import DocSyncService

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _set_system_feishu_creds() -> None:
    from system.models import SettingKeys, SystemSetting

    SystemSetting.objects.update_or_create(
        key=SettingKeys.FEISHU_APP_ID, defaults={"value": "cli_test", "is_encrypted": False}
    )
    SystemSetting.objects.update_or_create(
        key=SettingKeys.FEISHU_APP_SECRET,
        defaults={"value": "shh", "is_encrypted": False},
    )


def _text_block(block_id: str, content: str) -> dict[str, Any]:
    """构造一个飞书文本块（block_type=2），content 取自单 text_run。"""
    return {
        "block_id": block_id,
        "block_type": 2,
        "text": {"elements": [{"text_run": {"content": content}}]},
    }


def _mock_blocks(router: Any, items: list[dict[str, Any]]) -> Any:
    return router.get(url__regex=r".*/docx/v1/documents/[^/]+/blocks").respond(
        json={"code": 0, "data": {"items": items}}
    )


async def test_pull_adds_memory_and_advances_revision(
    respx_feishu, project_doc_factory
) -> None:
    """MEMORY 新增块 → 经 MemoryService 落 ProjectMemory + block_map；CAS 0→1 + 失效缓存。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY,
        feishu_document_id="doxMEM",
        last_synced_revision=0,
    )
    _mock_blocks(respx_feishu, [_text_block("b1", "hello world")])

    with patch(
        "initiatives.services.doc_sync_service.invalidate_doc_render"
    ) as inval:
        result = await DocSyncService().pull(file_token="doxMEM", event_id="e1")

    assert result["status"] == "ok"
    assert result["added"] == 1
    # MEMORY 条目经 MemoryService 落库（未映射归因 → contributor None）。
    memories = await sync_to_async(
        lambda: list(ProjectMemory.objects.filter(project_id=doc.project_id))
    )()
    assert len(memories) == 1
    assert memories[0].contributor_id is None
    # block_map 记新增块指纹 + db_ref 指向新建记忆。
    bm = await ProjectDocBlockMap.objects.aget(doc_id=doc.id, feishu_block_id="b1")
    assert bm.content_hash == block_content_hash("hello world")
    assert bm.db_ref == str(memories[0].id)
    # CAS 推进水位 + 落快照。
    refreshed = await ProjectDoc.objects.aget(pk=doc.id)
    assert refreshed.last_synced_revision == 1
    assert "hello world" in refreshed.last_synced_snapshot
    inval.assert_called_once_with(doc.id)


async def test_pull_attributes_memory_to_mapped_user(
    respx_feishu, project_doc_factory
) -> None:
    """initiated_by_user_id 命中 Friday 用户 → 新增记忆 contributor = 该用户。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY, feishu_document_id="doxMEM2"
    )
    user = await sync_to_async(
        lambda: get_user_model().objects.create_user(username="editor1", password="x")
    )()
    _mock_blocks(respx_feishu, [_text_block("b1", "attributed entry")])

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().pull(
            file_token="doxMEM2", event_id="e2", initiated_by_user_id=str(user.id)
        )

    assert result["status"] == "ok"
    memory = await ProjectMemory.objects.aget(project_id=doc.project_id)
    assert memory.contributor_id == user.id


async def test_pull_edited_non_memory_captures_revision(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """非 MEMORY 编辑块 → capture_block_revision 留痕（never-drop）+ 推进 block_map 指纹。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.STATE, feishu_document_id="doxSTATE"
    )
    # 预置映射：block_id b1 旧指纹（old content）。
    await block_map_factory(
        doc_id=doc.id, feishu_block_id="b1", content_hash=block_content_hash("old")
    )
    _mock_blocks(respx_feishu, [_text_block("b1", "new edited content")])

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().pull(file_token="doxSTATE", event_id="e3")

    assert result["status"] == "ok"
    assert result["edited"] == 1 and result["captured"] == 1
    # 飞书侧内容 capture 留痕（绝不静默丢）。
    rev = await ProjectDocBlockRevision.objects.aget(doc_id=doc.id, feishu_block_id="b1")
    assert rev.content == "new edited content"
    assert rev.source == "feishu"
    # block_map 指纹推进为飞书侧（飞书优先覆盖快照）。
    bm = await ProjectDocBlockMap.objects.aget(doc_id=doc.id, feishu_block_id="b1")
    assert bm.content_hash == block_content_hash("new edited content")


async def test_pull_skips_archived_project_without_fetch(
    respx_feishu, project_doc_factory
) -> None:
    """项目归档 → 入口 fail-soft 跳过，不回拉正文（route 未命中证明未外呼）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY, feishu_document_id="doxARCH"
    )
    await sync_to_async(
        lambda: Project.objects.filter(pk=doc.project_id).update(
            status=ProjectStatus.ARCHIVED
        )
    )()
    route = _mock_blocks(respx_feishu, [_text_block("b1", "x")])

    result = await DocSyncService().pull(file_token="doxARCH", event_id="e4")

    assert result == {"status": "skipped", "reason": "project_not_developing"}
    assert not route.called  # 归档不回拉正文


async def test_pull_marks_broken_on_document_not_found(
    respx_feishu, project_doc_factory
) -> None:
    """回拉 not-found → fail-soft 置 broken 不抛回主流程。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY, feishu_document_id="doxGONE"
    )
    # NOT_FOUND_CODES 含 1002 → get_document_content 抛 DocumentNotFoundError。
    respx_feishu.get(url__regex=r".*/docx/v1/documents/[^/]+/blocks").respond(
        json={"code": 1002, "msg": "not found"}
    )

    result = await DocSyncService().pull(file_token="doxGONE", event_id="e5")

    assert result == {"status": "failed", "reason": "document_not_found"}
    refreshed = await ProjectDoc.objects.aget(pk=doc.id)
    assert refreshed.sync_status == DocSyncStatus.BROKEN


async def test_pull_skips_when_doc_not_found() -> None:
    """file_token 无对应 ProjectDoc → 跳过（doc_not_found），不抛。"""
    result = await DocSyncService().pull(file_token="doxUNKNOWN", event_id="e6")
    assert result == {"status": "skipped", "reason": "doc_not_found"}

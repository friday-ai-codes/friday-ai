"""DocSyncService 同块三方合并 + capture-never-clobber 单测（83-04 / SYNC-04）。

respx mock 飞书回拉、不碰真机。覆盖 must_haves：
- 同块两侧都改且相交 → DB 取飞书侧 merged，落败系统侧落 ``ProjectDocBlockRevision``
  (source=system, reason=conflict_loser)，**绝不静默丢**；capture content 经 redact。
- 仅一侧改（系统侧未改）→ 自动并，不产 revision。
- MEMORY 非成员飞书编辑 → 不抛、active 不变、落 ProjectMemoryRevision 草稿留痕、归因
  system/unmapped（OQ-1 fail-soft）；前端非成员贡献仍 MEM-02 fail-closed。

飞书 block 形态（A5）/评论端点（A4）为 [ASSUMED]，本测试以构造 blocks + mock client 覆盖。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import (
    ApiStatus,
    DocSection,
    DocType,
    ProjectDocBlockRevision,
    ProjectMemory,
    ProjectMemoryRevision,
    ProjectStateApi,
)
from initiatives.services.doc_sync_diff import block_content_hash
from initiatives.services.doc_sync_service import DocSyncService
from initiatives.services.memory_service import MemoryPermissionError, MemoryService

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
    return {
        "block_id": block_id,
        "block_type": 2,
        "text": {"elements": [{"text_run": {"content": content}}]},
    }


def _mock_blocks(router: Any, items: list[dict[str, Any]]) -> Any:
    return router.get(url__regex=r".*/docx/v1/documents/[^/]+/blocks").respond(
        json={"code": 0, "data": {"items": items}}
    )


@sync_to_async
def _create_state_api(project_id: Any, method: str, path: str) -> Any:
    return ProjectStateApi.objects.create(
        project_id=project_id, method=method, path=path, status=ApiStatus.PLANNED
    )


# ---------------------------------------------------------------------------
# Task 1：非 MEMORY 同块三方合并 + capture-never-clobber（ProjectDocBlockRevision）
# ---------------------------------------------------------------------------


async def test_pull_conflict_captures_loser_feishu_wins(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """相交冲突（两侧都改）→ DB 取飞书侧 merged，落败系统侧落 ProjectDocBlockRevision。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.STATE, feishu_document_id="doxCONF")
    # 系统态 ours = 渲染的 API 行；base 指纹设为与 ours 不同 → 系统侧自上次同步也改过。
    api = await _create_state_api(doc.project_id, "GET", "/users")
    ours = "GET /users — planned"
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="b1",
        db_ref=str(api.id),
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("某个早期 base 内容"),
    )
    # theirs = 飞书侧用户改的内容（与 ours 相交冲突）。
    _mock_blocks(respx_feishu, [_text_block("b1", "用户在飞书改成这样")])

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().pull(file_token="doxCONF", event_id="c1")

    assert result["status"] == "ok"
    assert result["edited"] == 1 and result["captured"] == 1
    # 落败系统侧（ours）capture 留痕：绝不静默丢。
    rev = await ProjectDocBlockRevision.objects.aget(doc_id=doc.id, feishu_block_id="b1")
    assert rev.content == ours
    assert rev.source == "system"
    assert rev.reason == "conflict_loser"
    # 飞书侧 merged 即新态：block_map 指纹推进为飞书侧。
    from initiatives.models import ProjectDocBlockMap

    bm = await ProjectDocBlockMap.objects.aget(doc_id=doc.id, feishu_block_id="b1")
    assert bm.content_hash == block_content_hash("用户在飞书改成这样")


async def test_pull_disjoint_edit_auto_merges_no_revision(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """仅飞书改（系统侧未改，ours 指纹==base）→ 自动并，不产 revision。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.STATE, feishu_document_id="doxAUTO")
    api = await _create_state_api(doc.project_id, "POST", "/items")
    ours = "POST /items — planned"
    # base 指纹==ours 指纹 → 系统侧未改，只有飞书改。
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="b1",
        db_ref=str(api.id),
        section=DocSection.SYSTEM,
        content_hash=block_content_hash(ours),
    )
    _mock_blocks(respx_feishu, [_text_block("b1", "飞书侧唯一改动")])

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().pull(file_token="doxAUTO", event_id="c2")

    assert result["status"] == "ok"
    assert result["edited"] == 1 and result["captured"] == 0
    # 不相交自动并：无落败方留痕。
    has_rev = await ProjectDocBlockRevision.objects.filter(
        doc_id=doc.id, feishu_block_id="b1"
    ).aexists()
    assert not has_rev


async def test_pull_conflict_capture_content_redacted(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """capture content 入库前经 redact_secrets_in_text（落败方含密钥不留明文，T-83-04-INFO）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.STATE, feishu_document_id="doxRED")
    # ours 含一段疑似密钥 → 入库应被脱敏（与 ProjectDocService.capture_block_revision 一致）。
    secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd"
    api = await _create_state_api(doc.project_id, "GET", f"/k/{secret}")
    rendered = f"GET /k/{secret} — planned"
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="b1",
        db_ref=str(api.id),
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("base-diff"),
    )
    _mock_blocks(respx_feishu, [_text_block("b1", "飞书侧改动")])

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().pull(file_token="doxRED", event_id="c3")

    assert result["status"] == "ok"
    rev = await ProjectDocBlockRevision.objects.aget(doc_id=doc.id, feishu_block_id="b1")
    # 即便落败方文本含密钥，入库内容已脱敏（不含原始 secret），但仍非空（never-drop）。
    assert secret not in rev.content
    assert rev.content != rendered
    assert rev.content  # 留痕存在，绝不丢


# ---------------------------------------------------------------------------
# Task 1：MEMORY 非成员飞书编辑 fail-soft 归因（OQ-1，不进 active）
# ---------------------------------------------------------------------------


async def test_pull_memory_nonmember_edit_captures_not_active(
    respx_feishu, project_doc_factory, block_map_factory, project_memory_factory
) -> None:
    """MEMORY 非成员飞书编辑 → 不抛、active 不变、落 ProjectMemoryRevision 留痕（归因 system）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxNM")
    memory = await project_memory_factory(
        project_id=doc.project_id, content="active 原内容"
    )
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="b1",
        db_ref=str(memory.id),
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("base 内容"),
    )
    _mock_blocks(respx_feishu, [_text_block("b1", "非成员尝试改写")])

    # initiated_by_user_id=None → editor None → 非成员（system 归因），fail-soft 不抛。
    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().pull(file_token="doxNM", event_id="c4")

    assert result["status"] == "ok"
    assert result["captured"] == 1
    # active 不变（非成员不进 active）。
    refreshed = await ProjectMemory.objects.aget(pk=memory.id)
    assert refreshed.content == "active 原内容"
    # 飞书内容 capture 为 revision 留痕（绝不静默丢）。
    contents = await sync_to_async(
        lambda: [r.content for r in ProjectMemoryRevision.objects.filter(memory_id=memory.id)]
    )()
    assert "非成员尝试改写" in contents


async def test_pull_memory_member_edit_applies_active(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """MEMORY 成员飞书编辑 → 正常落 active + revision（飞书优先覆盖）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxM")
    user = await sync_to_async(
        lambda: get_user_model().objects.create_user(username="member1", password="x")
    )()
    # 把 user 加为项目成员。
    await sync_to_async(_add_member)(doc.project_id, user.id)
    # 成员贡献一条记忆（active）。
    memory = await MemoryService().append(
        project_id=doc.project_id,
        content="旧内容",
        contributor=user,
        _skip_doc_push=True,
    )
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="b1",
        db_ref=str(memory.id),
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("旧内容"),
    )
    _mock_blocks(respx_feishu, [_text_block("b1", "成员在飞书改的新内容")])

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().pull(
            file_token="doxM", event_id="c5", initiated_by_user_id=str(user.id)
        )

    assert result["status"] == "ok"
    refreshed = await ProjectMemory.objects.aget(pk=memory.id)
    assert refreshed.content == "成员在飞书改的新内容"  # 成员编辑落 active


async def test_frontend_nonmember_edit_still_fail_closed(project_doc_factory) -> None:
    """前端非成员贡献仍 MEM-02 fail-closed：MemoryService.edit 对非成员抛 MemoryPermissionError。"""
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxFC")
    memory = await MemoryService().append(
        project_id=doc.project_id,
        content="x",
        contributor=None,
        _skip_member_check=True,
        _skip_doc_push=True,
    )
    outsider = await sync_to_async(
        lambda: get_user_model().objects.create_user(username="outsider", password="x")
    )()
    with pytest.raises(MemoryPermissionError):
        await MemoryService().edit(
            memory_id=str(memory.id),
            content="非成员前端编辑",
            editor=outsider,
            _skip_doc_push=True,
        )


def _add_member(project_id: Any, user_id: Any) -> None:
    from initiatives.models import ProjectMember

    ProjectMember.objects.get_or_create(project_id=project_id, user_id=user_id)

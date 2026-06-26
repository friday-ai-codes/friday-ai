"""DocSyncService.push 推送链路单测（83-03 / SYNC-02），respx mock 飞书 block 写、不碰真机。

覆盖 must_haves：
- DB 系统区写 → 飞书 block 级增量推送（added→children / edited→update_block / deleted→delete_blocks），
  **全程无整篇 PUT/replace**（显式断言无该方法）。
- push 只读 section==SYSTEM（人工区 block_map 不进 diff、不被改/删）。
- 系统区写后 debounce defer push：lock 严格 ``docsync-{feishu_document_id}``（与 83-02 pull 同值）、
  idempotency_key=``docpush:{doc_id}``、run_at 含 debounce；同 doc 多次写合并同 key。
- 飞书来源（feishu_sync）写入不 defer（防 pull→push 回声）；钩子投递失败不阻断 DB 写。
- 限流退避：update_block 命中 99991400 经 @retry 退避后成功。
- fail-soft：归档 / 无 document_id / 无渲染器跳过不抛；外呼失败置 broken 不抛。

飞书 block 写真实端点/请求体（A4）为 [ASSUMED]，本测试以 respx 构造覆盖调用骨架，真机校验记 83-UAT.md。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from asgiref.sync import sync_to_async

from initiatives.models import (
    DocSection,
    DocSyncStatus,
    DocType,
    Project,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectMemoryStatus,
    ProjectStatus,
)
from initiatives.services.doc_sync_diff import block_content_hash
from initiatives.services.doc_sync_service import DocSyncService
from initiatives.services.memory_service import MemoryService
from services.feishu_doc import (
    DocumentNotFoundError,
    FeishuDocClient,
    RateLimitError,
)

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


async def _append_memory(project_id: Any, content: str) -> Any:
    """落一条 active 记忆且**不触发 push 钩子**（_skip_doc_push，避免 push 单测里的副作用 defer）。"""
    return await MemoryService().append(
        project_id=project_id,
        content=content,
        contributor=None,
        _skip_member_check=True,
        _skip_doc_push=True,
    )


def _children_route(router: Any) -> Any:
    return router.post(url__regex=r".*/blocks/[^/]+/children$").respond(
        json={"code": 0, "data": {"children": [{"block_id": "newblk"}]}}
    )


def _update_route(router: Any) -> Any:
    return router.patch(url__regex=r".*/blocks/[^/]+$").respond(json={"code": 0})


def _delete_route(router: Any) -> Any:
    return router.delete(url__regex=r".*/children/batch_delete$").respond(json={"code": 0})


def _assert_no_full_replace(router: Any) -> None:
    """硬断言：全程无整篇 PUT/replace（push 只发 block 级增量）。"""
    methods = {call.request.method for call in router.calls}
    assert "PUT" not in methods, f"push 不得整篇 PUT replace，实际方法集={methods}"
    for call in router.calls:
        # 任何外呼都必须打在 block 级 / token 端点，绝无整篇文档 replace 路由。
        assert "/blocks/" in str(call.request.url) or "tenant_access_token" in str(
            call.request.url
        ), f"非 block 级外呼: {call.request.url}"


# ---------------------------------------------------------------------------
# Task 1：update_block / delete_blocks / create_children（block 级、错误码、永不整篇）
# ---------------------------------------------------------------------------


async def test_update_block_patches_block(respx_feishu) -> None:
    """update_block → PATCH /blocks/{block_id}，code==0 即成功，无整篇 PUT。"""
    route = _update_route(respx_feishu)
    client = FeishuDocClient("cli_test", "shh")

    await client.update_block("doxX", "blk1", {"update_text_elements": {"elements": []}})

    assert route.called
    assert route.calls.last.request.method == "PATCH"
    assert "/blocks/blk1" in str(route.calls.last.request.url)
    _assert_no_full_replace(respx_feishu)


async def test_delete_blocks_batch_delete(respx_feishu) -> None:
    """delete_blocks → children batch_delete（DELETE），按 index 范围，无整篇 PUT。"""
    route = _delete_route(respx_feishu)
    client = FeishuDocClient("cli_test", "shh")

    await client.delete_blocks("doxX", start_index=0, end_index=1)

    assert route.called
    assert route.calls.last.request.method == "DELETE"
    assert "/children/batch_delete" in str(route.calls.last.request.url)
    _assert_no_full_replace(respx_feishu)


async def test_create_children_returns_new_block_ids(respx_feishu) -> None:
    """create_children → POST children，解析 data.children[].block_id 返回新建块 id。"""
    _children_route(respx_feishu)
    client = FeishuDocClient("cli_test", "shh")

    new_ids = await client.create_children(
        "doxX", children=[{"block_type": 2, "text": {"elements": []}}]
    )

    assert new_ids == ["newblk"]


async def test_block_write_classifies_errors(respx_feishu) -> None:
    """code!=0 错误码分类：not-found→DocumentNotFoundError；限流码→RateLimitError（直走 helper 免等待）。"""
    # not-found（1002）非限流 → 不重试，直接抛 DocumentNotFoundError。
    respx_feishu.patch(url__regex=r".*/blocks/[^/]+$").respond(
        json={"code": 1002, "msg": "not found"}
    )
    client = FeishuDocClient("cli_test", "shh")
    with pytest.raises(DocumentNotFoundError):
        await client.update_block("doxGONE", "blk1", {})

    # 限流码经 helper 分类（避免 @retry 真实退避等待）。
    with pytest.raises(RateLimitError):
        client._raise_for_block_error({"code": 99991400, "msg": "rate limit"})


async def test_update_block_retries_on_rate_limit(respx_feishu, monkeypatch) -> None:
    """限流退避：99991400 命中后 @retry 退避重试，第二次成功（wait_none 加速单测）。"""
    from tenacity import wait_none

    monkeypatch.setattr(FeishuDocClient.update_block.retry, "wait", wait_none())
    route = respx_feishu.patch(url__regex=r".*/blocks/[^/]+$").mock(
        side_effect=[
            httpx.Response(200, json={"code": 99991400, "msg": "rate limit"}),
            httpx.Response(200, json={"code": 0}),
        ]
    )
    client = FeishuDocClient("cli_test", "shh")

    await client.update_block("doxX", "blk1", {})

    assert route.call_count == 2  # 退避后重试一次成功


# ---------------------------------------------------------------------------
# Task 2：DocSyncService.push 系统区 block 级增量（add/edit/delete + 永不整篇 + 仅系统区）
# ---------------------------------------------------------------------------


async def test_push_adds_new_block_and_advances_revision(respx_feishu, project_doc_factory) -> None:
    """系统区新增（DB 有记忆、飞书无映射）→ create_children 增量写 + 落 block_map + CAS 0→1。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY, feishu_document_id="doxADD", last_synced_revision=0
    )
    memory = await _append_memory(doc.project_id, "first memory")
    children = _children_route(respx_feishu)

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render") as inval:
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result["status"] == "ok"
    assert result["added"] == 1
    assert children.called  # 走 children 增量新增
    # 新增块落 block_map（db_ref=memory.id，feishu_block_id=飞书返回新 id）。
    bm = await ProjectDocBlockMap.objects.aget(doc_id=doc.id, db_ref=str(memory.id))
    assert bm.feishu_block_id == "newblk"
    assert bm.section == DocSection.SYSTEM
    assert bm.content_hash == block_content_hash("first memory")
    # CAS 推进水位。
    refreshed = await ProjectDoc.objects.aget(pk=doc.id)
    assert refreshed.last_synced_revision == 1
    inval.assert_called_once_with(doc.id)
    _assert_no_full_replace(respx_feishu)


async def test_push_edits_changed_block(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """系统区编辑（指纹变）→ update_block 就地改既有块（绝不整篇），推进 block_map 指纹。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxEDIT")
    memory = await _append_memory(doc.project_id, "new content")
    # 预置映射：db_ref=memory.id、旧指纹 + 已知飞书块 id。
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="blk1",
        db_ref=str(memory.id),
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("old content"),
    )
    update = _update_route(respx_feishu)

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result["status"] == "ok"
    assert result["edited"] == 1
    assert update.called
    assert "/blocks/blk1" in str(update.calls.last.request.url)
    bm = await ProjectDocBlockMap.objects.aget(doc_id=doc.id, feishu_block_id="blk1")
    assert bm.content_hash == block_content_hash("new content")
    _assert_no_full_replace(respx_feishu)


async def test_push_deletes_orphan_block(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """系统区删除（DB 已无对应条目、映射仍有）→ delete_blocks 按 index 删 + 清 block_map。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxDEL")
    # 无 active 记忆，但映射表残留一条系统区块 → 期望态判 deleted。
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="oldblk",
        db_ref="ghost-memory-id",
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("gone"),
    )
    delete = _delete_route(respx_feishu)

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result["status"] == "ok"
    assert result["deleted"] == 1
    assert delete.called
    assert "/children/batch_delete" in str(delete.calls.last.request.url)
    # 映射清除。
    exists = await ProjectDocBlockMap.objects.filter(
        doc_id=doc.id, feishu_block_id="oldblk"
    ).aexists()
    assert not exists
    _assert_no_full_replace(respx_feishu)


async def test_push_never_full_replace_mixed_ops(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """add+edit+delete 混合一次推送 → 全程 block 级增量，显式断言无整篇 PUT/replace。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxMIX")
    edited = await _append_memory(doc.project_id, "edited new")
    await _append_memory(doc.project_id, "added fresh")  # 无映射 → added
    # edited 记忆旧映射（指纹变 → edited）。
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="blkE",
        db_ref=str(edited.id),
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("stale"),
    )
    # 残留映射（无对应 active 记忆 → deleted）。
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="blkD",
        db_ref="ghost",
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("gone"),
    )
    _children_route(respx_feishu)
    _update_route(respx_feishu)
    _delete_route(respx_feishu)

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result["status"] == "ok"
    assert result["added"] == 1 and result["edited"] == 1 and result["deleted"] == 1
    _assert_no_full_replace(respx_feishu)


async def test_push_ignores_human_section(
    respx_feishu, project_doc_factory, block_map_factory
) -> None:
    """push 只读 section==SYSTEM：人工区映射不进 diff、不被删（never-clobber 人工区）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxHUM")
    kept = await _append_memory(doc.project_id, "kept")
    # 系统区映射与期望态一致 → no-op。
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="sysblk",
        db_ref=str(kept.id),
        section=DocSection.SYSTEM,
        content_hash=block_content_hash("kept"),
    )
    # 人工区映射（db_ref 不在期望态）→ 若被纳入会被误删；正确行为：忽略。
    await block_map_factory(
        doc_id=doc.id,
        feishu_block_id="humanblk",
        db_ref="human-entry",
        section=DocSection.HUMAN,
        content_hash=block_content_hash("human text"),
    )
    delete = _delete_route(respx_feishu)

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result["status"] == "ok"
    assert result["deleted"] == 0
    assert not delete.called  # 人工区绝不被删
    # 人工区映射仍在。
    assert await ProjectDocBlockMap.objects.filter(
        doc_id=doc.id, feishu_block_id="humanblk"
    ).aexists()


async def test_push_skips_archived_project(respx_feishu, project_doc_factory) -> None:
    """项目归档 → fail-soft 跳过（不外呼）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxARCH")
    await sync_to_async(
        lambda: Project.objects.filter(pk=doc.project_id).update(status=ProjectStatus.ARCHIVED)
    )()
    children = _children_route(respx_feishu)

    result = await DocSyncService().push(doc_id=str(doc.id))

    assert result == {"status": "skipped", "reason": "project_not_developing"}
    assert not children.called


async def test_push_skips_without_document_id(project_doc_factory) -> None:
    """无 feishu_document_id → 跳过（未建飞书镜像，无可推）。"""
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="")
    result = await DocSyncService().push(doc_id=str(doc.id))
    assert result == {"status": "skipped", "reason": "no_document_id"}


async def test_push_skips_unsupported_doc_type(project_doc_factory) -> None:
    """无系统区渲染器（RESEARCH 留后续）→ 跳过，绝不对空期望态盲删既有块。"""
    doc = await project_doc_factory(doc_type=DocType.RESEARCH, feishu_document_id="doxRES")
    result = await DocSyncService().push(doc_id=str(doc.id))
    assert result == {"status": "skipped", "reason": "unsupported_doc_type"}


async def test_push_marks_broken_on_api_error(respx_feishu, project_doc_factory) -> None:
    """外呼失败（非限流错误码）→ fail-soft 置 broken 不抛。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxERR")
    await _append_memory(doc.project_id, "boom")
    respx_feishu.post(url__regex=r".*/blocks/[^/]+/children$").respond(
        json={"code": 1254, "msg": "server error"}
    )

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result["status"] == "failed"
    refreshed = await ProjectDoc.objects.aget(pk=doc.id)
    assert refreshed.sync_status == DocSyncStatus.BROKEN


async def test_push_skips_when_doc_not_found() -> None:
    """doc_id 无对应 ProjectDoc → 跳过（doc_not_found），不抛。"""
    result = await DocSyncService().push(doc_id="00000000-0000-0000-0000-000000000000")
    assert result == {"status": "skipped", "reason": "doc_not_found"}


# ---------------------------------------------------------------------------
# Task 3：系统区写后钩子（debounce defer push、共用 lock、防回声、fail-soft）
# ---------------------------------------------------------------------------


async def test_memory_write_schedules_push_with_shared_lock(project_doc_factory) -> None:
    """MEMORY 系统区写后 defer push：lock 严格 docsync-{document_id}（与 pull 同值）、key、debounce。"""
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxLOCK")
    defer = AsyncMock(return_value="job-1")

    with patch("durable.service.DurableTaskService.defer", defer):
        await MemoryService().append(
            project_id=doc.project_id,
            content="entry",
            contributor=None,
            _skip_member_check=True,
        )

    defer.assert_awaited_once()
    args, kwargs = defer.await_args.args, defer.await_args.kwargs
    assert args[0] == "durable_doc_sync_push"
    assert args[1] == {"doc_id": str(doc.id)}
    # lock 与 83-02 pull / 83-06 poll 对同一文档完全一致：docsync-{feishu_document_id}。
    assert kwargs["lock"] == f"docsync-{doc.feishu_document_id}"
    assert kwargs["lock"] == "docsync-doxLOCK"
    assert kwargs["idempotency_key"] == f"docpush:{doc.id}"
    from durable.queues import QUEUE_DOC_SYNC

    assert kwargs["queue"] == QUEUE_DOC_SYNC
    assert isinstance(kwargs["run_at"], datetime)  # debounce run_at


async def test_debounce_merges_same_idempotency_key(project_doc_factory) -> None:
    """同 doc 窗口内多次写 → idempotency_key 相同（合并一份 todo）。"""
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxMERGE")
    defer = AsyncMock(return_value="job")

    with patch("durable.service.DurableTaskService.defer", defer):
        await MemoryService().append(
            project_id=doc.project_id, content="a", contributor=None, _skip_member_check=True
        )
        await MemoryService().append(
            project_id=doc.project_id, content="b", contributor=None, _skip_member_check=True
        )

    assert defer.await_count == 2
    keys = {c.kwargs["idempotency_key"] for c in defer.await_args_list}
    assert keys == {f"docpush:{doc.id}"}  # 合并同 key


async def test_feishu_sync_write_does_not_schedule_push(project_doc_factory) -> None:
    """飞书来源（_skip_doc_push=True）写入不 defer（防 pull→push 回声，T-83-03-ECHO）。"""
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxECHO")
    defer = AsyncMock(return_value="job")

    with patch("durable.service.DurableTaskService.defer", defer):
        await MemoryService().append(
            project_id=doc.project_id,
            content="mirror",
            contributor=None,
            _skip_member_check=True,
            _skip_doc_push=True,
        )

    defer.assert_not_awaited()


async def test_schedule_failsoft_does_not_break_write(project_doc_factory) -> None:
    """钩子投递失败 → fail-soft warning，不阻断 DB 写主流程（记忆仍落库）。"""
    doc = await project_doc_factory(doc_type=DocType.MEMORY, feishu_document_id="doxFAIL")
    boom = AsyncMock(side_effect=RuntimeError("defer down"))

    with patch("durable.service.DurableTaskService.defer", boom):
        memory = await MemoryService().append(
            project_id=doc.project_id,
            content="resilient",
            contributor=None,
            _skip_member_check=True,
        )

    assert memory.id is not None
    assert memory.status == ProjectMemoryStatus.ACTIVE


async def test_no_memory_doc_skips_schedule(project_doc_factory) -> None:
    """项目无 MEMORY ProjectDoc（无飞书镜像）→ 不 defer（解析不到 document_id）。"""
    # 仅建 STATE doc，无 MEMORY doc。
    doc = await project_doc_factory(doc_type=DocType.STATE, feishu_document_id="doxNOMEM")
    defer = AsyncMock(return_value="job")

    with patch("durable.service.DurableTaskService.defer", defer):
        await MemoryService().append(
            project_id=doc.project_id, content="x", contributor=None, _skip_member_check=True
        )

    defer.assert_not_awaited()

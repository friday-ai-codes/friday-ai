"""DocSyncService.push 编辑感知延迟写 + 乐观并发 rebase 单测（83-04 / SYNC-04）。

respx mock 飞书 block 写、不碰真机；rebase 走乐观并发 CAS（不依赖真实 durable doing lock，
in-process/SQLite 用例即可覆盖，Pitfall 3）。覆盖 must_haves：
- 编辑感知延迟写：last_feishu_edit_at 在活跃窗口内 → push 重排 run_at 并返回 deferred，
  **不发任何 block 写**（断言 create_children/update_block 未被调）。
- 乐观并发 rebase：CAS 推进水位落空（并发改过）→ 先 self.pull rebase 再以最新水位重试，
  最终水位推进成功；rebase 有限次绝不死循环。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from initiatives.models import DocType, ProjectDoc
from initiatives.services.doc_sync_service import DocSyncService
from initiatives.services.memory_service import MemoryService
from initiatives.services.project_doc_service import ProjectDocService

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


# ---------------------------------------------------------------------------
# 编辑感知延迟写（gate ①）
# ---------------------------------------------------------------------------


async def test_push_defers_when_active_edit(respx_feishu, project_doc_factory) -> None:
    """last_feishu_edit_at 在活跃窗口内 → push 重排 run_at 并返回 deferred，不发任何 block 写。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY,
        feishu_document_id="doxACTIVE",
        last_feishu_edit_at=timezone.now(),  # 刚刚编辑 → 活跃
    )
    await _append_memory(doc.project_id, "应延迟的内容")
    children = _children_route(respx_feishu)
    defer = AsyncMock(return_value="job-defer")

    with (
        patch("initiatives.services.doc_sync_service.invalidate_doc_render"),
        patch("durable.service.DurableTaskService.defer", defer),
    ):
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result == {"status": "deferred", "reason": "active_edit"}
    assert not children.called  # 活跃编辑中绝不抢写 block
    # 重排一次延迟推送：lock/key 同口径 + run_at 带延迟。
    defer.assert_awaited_once()
    kwargs = defer.await_args.kwargs
    assert kwargs["lock"] == f"docsync-{doc.feishu_document_id}"
    assert kwargs["idempotency_key"] == f"docpush:{doc.id}"
    assert kwargs["run_at"] > timezone.now()


async def test_push_proceeds_when_edit_stale(respx_feishu, project_doc_factory) -> None:
    """last_feishu_edit_at 已过活跃窗口（久远）→ 正常推送，不延迟。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY,
        feishu_document_id="doxSTALE",
        last_feishu_edit_at=timezone.now() - timedelta(hours=1),
    )
    await _append_memory(doc.project_id, "正常推送")
    children = _children_route(respx_feishu)

    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result["status"] == "ok"
    assert children.called


# ---------------------------------------------------------------------------
# 乐观并发 rebase（gate ②，CAS 落空 → pull rebase 再重试）
# ---------------------------------------------------------------------------


async def test_push_rebases_on_revision_drift(respx_feishu, project_doc_factory) -> None:
    """CAS 推进水位落空（并发改过 revision）→ 先 pull rebase 再重试，最终水位推进成功。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY, feishu_document_id="doxREBASE", last_synced_revision=0
    )
    await _append_memory(doc.project_id, "待推送条目")
    _children_route(respx_feishu)

    real_advance = ProjectDocService.advance_sync_revision
    state = {"n": 0}

    async def flaky_advance(
        self: Any,
        *,
        doc_id: Any,
        expected_revision: int,
        new_revision: int,
        snapshot: str,
    ) -> bool:
        state["n"] += 1
        if state["n"] == 1:
            # 模拟并发写：在本次 CAS 前把 DB 水位推进，令本次条件 update 落空（影响 0 行）。
            await sync_to_async(
                lambda: ProjectDoc.objects.filter(pk=doc_id).update(
                    last_synced_revision=expected_revision + 1
                )
            )()
        return await real_advance(
            self,
            doc_id=doc_id,
            expected_revision=expected_revision,
            new_revision=new_revision,
            snapshot=snapshot,
        )

    pull_mock = AsyncMock(return_value={"status": "ok"})

    with (
        patch("initiatives.services.doc_sync_service.invalidate_doc_render"),
        patch.object(ProjectDocService, "advance_sync_revision", flaky_advance),
        patch.object(DocSyncService, "pull", pull_mock),
    ):
        result = await DocSyncService().push(doc_id=str(doc.id))

    assert result["status"] == "ok"
    assert result["advanced"] is True  # 重试后最终推进成功
    pull_mock.assert_awaited()  # CAS 落空触发 pull rebase
    # 最终水位为并发写后再 +1（不盲覆盖、以最新态推进）。
    refreshed = await ProjectDoc.objects.aget(pk=doc.id)
    assert refreshed.last_synced_revision == 2


async def test_push_rebase_bounded_no_infinite_loop(
    respx_feishu, project_doc_factory
) -> None:
    """CAS 持续落空（始终并发改过）→ 有限次 rebase 后返回（绝不死循环）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY, feishu_document_id="doxLOOP", last_synced_revision=0
    )
    await _append_memory(doc.project_id, "始终冲突的条目")
    _children_route(respx_feishu)

    # advance 恒返回 False（CAS 始终落空）。
    always_false = AsyncMock(return_value=False)
    pull_mock = AsyncMock(return_value={"status": "ok"})

    with (
        patch("initiatives.services.doc_sync_service.invalidate_doc_render"),
        patch.object(ProjectDocService, "advance_sync_revision", always_false),
        patch.object(DocSyncService, "pull", pull_mock),
    ):
        result = await DocSyncService().push(doc_id=str(doc.id))

    # 有限次重试后返回（最终仍未 advanced），但绝不死循环。
    assert result["advanced"] is False
    assert pull_mock.await_count <= 3

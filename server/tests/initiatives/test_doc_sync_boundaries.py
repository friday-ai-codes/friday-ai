"""边界/失败模式全收口单测（SYNC-06，83-06），全部 fail-soft 不反噬主流程。

覆盖 acceptance：
- not-found → ``set_sync_status(broken)`` 不抛；一键重建入口（rebuild_workspace）可触发。
- 项目归档 → pull/push skip + best-effort ``unsubscribe_file`` 被调（失败不抛）+ DB 只读
  快照（``last_synced_snapshot``）保留 + ``subscribed`` 置 False。
- 非成员飞书编辑 → operator 未映射 → 归因 system（contributor None），编辑 fail-soft 接受。
- 限流 → client ``@retry`` 退避耗尽不抛回主流程；记 doc_sync_rate_limited、**不置 broken**
  （瞬态可恢复，留下次事件/poll 兜底）。

不依赖 live 飞书：飞书外呼以 respx / fake client 覆盖，[ASSUMED] 真机项记 83-UAT.md。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import (
    DocSyncStatus,
    DocType,
    Project,
    ProjectDoc,
    ProjectMemory,
    ProjectStatus,
)
from initiatives.services.doc_sync_service import DocSyncService
from services.feishu_doc import RateLimitError

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


def _text_block(content: str) -> dict[str, Any]:
    return {
        "block_id": "b1",
        "block_type": 2,
        "text": {"elements": [{"text_run": {"content": content}}]},
    }


def _mock_blocks(router: Any, items: list[dict[str, Any]]) -> Any:
    return router.get(url__regex=r".*/docx/v1/documents/[^/]+/blocks").respond(
        json={"code": 0, "data": {"items": items}}
    )


# ---- not-found → broken + 一键重建入口 ----


async def test_pull_not_found_marks_broken_and_offers_rebuild(
    respx_feishu, project_doc_factory
) -> None:
    """回拉 not-found → fail-soft 置 broken 不抛；rebuild_workspace 一键重建可触发。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY, feishu_document_id="doxGONE"
    )
    respx_feishu.get(url__regex=r".*/docx/v1/documents/[^/]+/blocks").respond(
        json={"code": 1002, "msg": "not found"}
    )

    result = await DocSyncService().pull(file_token="doxGONE", event_id="e1")

    assert result == {"status": "failed", "reason": "document_not_found"}
    refreshed = await ProjectDoc.objects.aget(pk=doc.id)
    assert refreshed.sync_status == DocSyncStatus.BROKEN

    # 一键重建入口（复用 Phase 82 rebuild_workspace）：派发 provision，不抛。
    from initiatives.services.project_doc_service import ProjectDocService

    with patch.object(ProjectDocService, "provision_dispatch", return_value=None) as disp:
        await ProjectDocService().rebuild_workspace(project_id=doc.project_id)
    disp.assert_called_once()


# ---- 项目归档 → 停同步 + 退订 + 只读快照 ----


async def test_pull_archived_stops_sync_and_unsubscribes(project_doc_factory) -> None:
    """归档 → pull skip + unsubscribe_file 被调 + subscribed 置 False + 只读快照保留。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.STATE,
        feishu_document_id="doxARCH",
        subscribed=True,
        last_synced_snapshot="read-only snapshot",
    )
    await sync_to_async(
        lambda: Project.objects.filter(pk=doc.project_id).update(
            status=ProjectStatus.ARCHIVED
        )
    )()

    unsub = AsyncMock(return_value=True)

    class _FakeClient:
        async def unsubscribe_file(self, file_token: str, *, file_type: str = "docx") -> bool:
            return await unsub(file_token, file_type=file_type)

    async def _fake_build(space: Any) -> Any:
        return _FakeClient()

    with patch.object(DocSyncService, "_build_doc_client", staticmethod(_fake_build)):
        result = await DocSyncService().pull(file_token="doxARCH", event_id="e2")

    assert result == {"status": "skipped", "reason": "project_not_developing"}
    unsub.assert_awaited_once_with("doxARCH", file_type="docx")
    refreshed = await ProjectDoc.objects.aget(pk=doc.id)
    assert refreshed.subscribed is False
    # 只读快照保留（DB 不清，不再刷新）。
    assert refreshed.last_synced_snapshot == "read-only snapshot"


async def test_archived_unsubscribe_failure_is_failsoft(project_doc_factory) -> None:
    """归档退订外呼抛异常 → fail-soft 跳过不反噬（仍返回 skip，不抛）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.STATE, feishu_document_id="doxARCH2", subscribed=True
    )
    await sync_to_async(
        lambda: Project.objects.filter(pk=doc.project_id).update(
            status=ProjectStatus.ARCHIVED
        )
    )()

    async def _fake_build(space: Any) -> Any:
        raise RuntimeError("no feishu creds")

    with patch.object(DocSyncService, "_build_doc_client", staticmethod(_fake_build)):
        result = await DocSyncService().pull(file_token="doxARCH2", event_id="e3")

    assert result == {"status": "skipped", "reason": "project_not_developing"}


async def test_archived_without_subscription_skips_no_unsubscribe(
    project_doc_factory,
) -> None:
    """归档但未订阅 → 不退订（不建 client），仍 fail-soft skip（幂等，不反复退订）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.STATE, feishu_document_id="doxARCH3", subscribed=False
    )
    await sync_to_async(
        lambda: Project.objects.filter(pk=doc.project_id).update(
            status=ProjectStatus.ARCHIVED
        )
    )()

    build = AsyncMock()
    with patch.object(DocSyncService, "_build_doc_client", build):
        result = await DocSyncService().pull(file_token="doxARCH3", event_id="e4")

    assert result == {"status": "skipped", "reason": "project_not_developing"}
    build.assert_not_awaited()


# ---- 非成员飞书编辑 → 归因 system fail-soft 接受 ----


async def test_nonmember_edit_attributed_system_failsoft(
    respx_feishu, project_doc_factory
) -> None:
    """飞书 operator 未映射 Friday 用户 → 归因 system（contributor None），编辑 fail-soft 接受。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.MEMORY, feishu_document_id="doxNONMEM"
    )
    _mock_blocks(respx_feishu, [_text_block("entry from non-member")])

    # 非成员飞书编辑：上游 resolve_feishu_user 未映射出 Friday 用户（给到一个 DB 内不存在的
    # 合法 id）→ _resolve_user 取不到 → 归因 system（contributor None），fail-soft 接受不拒绝。
    import uuid as _uuid

    unmapped_id = str(_uuid.uuid4())
    with patch("initiatives.services.doc_sync_service.invalidate_doc_render"):
        result = await DocSyncService().pull(
            file_token="doxNONMEM", event_id="e5", initiated_by_user_id=unmapped_id
        )

    assert result["status"] == "ok"
    assert result["added"] == 1
    memory = await ProjectMemory.objects.aget(project_id=doc.project_id)
    # 未映射 → contributor None（归因 system，fail-soft 接受不拒绝）。
    assert memory.contributor_id is None


# ---- 限流 → 退避不抛回主流程，不置 broken ----


async def test_rate_limit_backoff_does_not_break_main_flow(project_doc_factory) -> None:
    """限流（@retry 退避耗尽 RateLimitError）→ fail-soft 返回 rate_limited 不抛、**不置 broken**。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.STATE, feishu_document_id="doxRL"
    )

    class _FakeClient:
        async def get_document_content(
            self, document_id: str
        ) -> tuple[str, list[dict[str, Any]]]:
            raise RateLimitError("rate limit exhausted after retry")

    async def _fake_build(space: Any) -> Any:
        return _FakeClient()

    with patch.object(DocSyncService, "_build_doc_client", staticmethod(_fake_build)):
        result = await DocSyncService().pull(file_token="doxRL", event_id="e6")

    assert result == {"status": "failed", "reason": "rate_limited"}
    # 瞬态不置 broken（保留 READY 待下次事件/poll 兜底）。
    refreshed = await ProjectDoc.objects.aget(pk=doc.id)
    assert refreshed.sync_status == DocSyncStatus.READY

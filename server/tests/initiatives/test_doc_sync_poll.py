"""TTL 兜底轮询单测（SYNC-01 漏事件兜底，83-06），respx mock 飞书回拉、不碰真机。

覆盖 must_haves / acceptance：
- 进行中项目 READY doc revision 漂移 → defer durable_doc_sync_pull；lock 严格等于
  ``docsync-{feishu_document_id}``（与 83-02 pull / 83-03 push 同文档同值）、idempotency_key=
  ``docpull:{feishu_document_id}:poll:{revision}``、initiated_by_user_id="system"。
- revision 未变 → 不 defer。
- 归档项目 doc / broken doc 不进 poll（不被反复触发 pull，T-83-06-DOS）。
- 单 doc 异常隔离不阻断整批（结构化 {checked, triggered} 返回）。

飞书回拉真实形态（A5）为 [ASSUMED]，本测试以构造 blocks 覆盖，真机校验记 83-UAT.md。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from durable.service import DurableTaskService
from initiatives.models import (
    DocSyncStatus,
    DocType,
    Project,
    ProjectStatus,
)
from initiatives.services.doc_sync_diff import block_content_hash
from services.feishu_doc import RateLimitError
from tasks.doc_sync_poll import poll_project_docs_revisions

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


async def test_poll_defers_pull_on_revision_drift(
    respx_feishu, project_doc_factory
) -> None:
    """READY doc 飞书侧漂移（指纹 != 快照指纹）→ defer durable_doc_sync_pull（lock/key/system）。"""
    await _set_system_feishu_creds()
    doc = await project_doc_factory(
        doc_type=DocType.STATE,
        feishu_document_id="doxDRIFT",
        last_synced_snapshot="old snapshot",
    )
    _mock_blocks(respx_feishu, [_text_block("brand new feishu content")])
    expected_revision = block_content_hash("brand new feishu content")

    defer_mock = AsyncMock(return_value="job-1")
    with patch.object(DurableTaskService, "defer", defer_mock):
        result = await poll_project_docs_revisions()

    assert result == {"checked": 1, "triggered": 1}
    defer_mock.assert_awaited_once()
    args, kwargs = defer_mock.call_args
    assert args[0] == "durable_doc_sync_pull"
    assert args[1] == {
        "file_token": "doxDRIFT",
        "event_id": f"poll:{expected_revision}",
    }
    # lock 与 83-02 pull / 83-03 push 对同一文档完全一致（三处同值）。
    assert kwargs["lock"] == f"docsync-{doc.feishu_document_id}"
    assert kwargs["lock"] == "docsync-doxDRIFT"
    assert kwargs["idempotency_key"] == f"docpull:doxDRIFT:poll:{expected_revision}"
    assert kwargs["initiated_by_user_id"] == "system"


async def test_poll_no_defer_when_revision_unchanged(
    respx_feishu, project_doc_factory
) -> None:
    """飞书侧未漂移（指纹 == 快照指纹）→ 不 defer。"""
    await _set_system_feishu_creds()
    await project_doc_factory(
        doc_type=DocType.STATE,
        feishu_document_id="doxSAME",
        last_synced_snapshot="stable content",
    )
    _mock_blocks(respx_feishu, [_text_block("stable content")])

    defer_mock = AsyncMock(return_value="job-x")
    with patch.object(DurableTaskService, "defer", defer_mock):
        result = await poll_project_docs_revisions()

    assert result == {"checked": 1, "triggered": 0}
    defer_mock.assert_not_awaited()


async def test_poll_skips_archived_and_broken_docs(
    respx_feishu, project_doc_factory
) -> None:
    """归档项目 doc + broken doc 不进 poll（不被反复触发 pull，T-83-06-DOS）。"""
    await _set_system_feishu_creds()
    # 归档项目 doc（READY 但项目非 developing）→ 不进 poll。
    archived = await project_doc_factory(
        doc_type=DocType.STATE, feishu_document_id="doxARCH"
    )
    await sync_to_async(
        lambda: Project.objects.filter(pk=archived.project_id).update(
            status=ProjectStatus.ARCHIVED
        )
    )()
    # broken doc（进行中项目但 sync_status=broken）→ 不进 poll。
    await project_doc_factory(
        doc_type=DocType.STATE,
        feishu_document_id="doxBROKEN",
        sync_status=DocSyncStatus.BROKEN,
    )
    route = _mock_blocks(respx_feishu, [_text_block("x")])

    defer_mock = AsyncMock(return_value="job-y")
    with patch.object(DurableTaskService, "defer", defer_mock):
        result = await poll_project_docs_revisions()

    # 两个 doc 都不可轮询 → checked=0、不回拉、不 defer。
    assert result == {"checked": 0, "triggered": 0}
    assert not route.called
    defer_mock.assert_not_awaited()


async def test_poll_isolates_single_doc_failure(project_doc_factory) -> None:
    """单 doc 回拉异常隔离不阻断整批；其余正常 doc 仍能 defer（结构化返回不受影响）。"""
    await _set_system_feishu_creds()
    await project_doc_factory(
        doc_type=DocType.STATE,
        feishu_document_id="doxBAD",
        last_synced_snapshot="old",
    )
    await project_doc_factory(
        doc_type=DocType.STATE,
        feishu_document_id="doxGOOD",
        last_synced_snapshot="old",
    )

    class _FakeClient:
        async def get_document_content(
            self, document_id: str
        ) -> tuple[str, list[dict[str, Any]]]:
            # doxBAD 回拉抛限流耗尽（异常）；doxGOOD 返回漂移正文。
            if "doxBAD" in document_id:
                raise RateLimitError("rate limit exhausted")
            return "fresh good", [_text_block("fresh good")]

    async def _fake_build(space: Any) -> Any:
        return _FakeClient()

    defer_mock = AsyncMock(return_value="job-z")
    from initiatives.services.doc_sync_service import DocSyncService

    with (
        patch.object(DurableTaskService, "defer", defer_mock),
        patch.object(DocSyncService, "_build_doc_client", staticmethod(_fake_build)),
    ):
        result = await poll_project_docs_revisions()

    # 两个都 checked；bad 抛异常被隔离不计 triggered，good 漂移 defer 一次。
    assert result["checked"] == 2
    assert result["triggered"] == 1
    assert defer_mock.await_count == 1

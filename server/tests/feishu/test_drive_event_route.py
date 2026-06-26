"""drive.file.edit_v1 路由 normalizer + durable defer 单测（83-02 / SYNC-01）。

不碰真实飞书 / DB：
- normalizer（``_normalize_drive_edit_event``）纯函数，覆盖 event / payload 两种容器与缺字段。
- handler（``_handle_drive_file_edit``）以 mock 的 ``DurableTaskService.defer`` /
  ``resolve_feishu_user`` 验证：归因、defer 入参（**lock=docsync-{file_token}**、idempotency_key、
  queue、initiated_by）、未映射 operator→system、缺 file_token 不 defer、handler 不回拉正文
  （``get_document_content`` 未被调）。

飞书真实事件字段名（A1）为 [ASSUMED]，本测试以构造 payload 覆盖，真机校验记 83-UAT.md。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from feishu.views import FeishuWebhookView, _normalize_drive_edit_event

# 标准开放平台 schema（header + event）：drive 事件不携带 project_key。
_EVENT_SCHEMA = {
    "schema": "2.0",
    "header": {"event_id": "evt-1", "event_type": "drive.file.edit_v1"},
    "event": {
        "file_token": "doxcnXXXX",
        "file_type": "docx",
        "operator_id_list": [{"open_id": "ou_operator"}],
    },
}


# ---------------------------------------------------------------------------
# normalizer
# ---------------------------------------------------------------------------


def test_normalize_extracts_from_event_schema() -> None:
    info = _normalize_drive_edit_event(_EVENT_SCHEMA)
    assert info["file_token"] == "doxcnXXXX"
    assert info["operator"] == "ou_operator"
    assert info["event_id"] == "evt-1"


def test_normalize_falls_back_to_payload_container() -> None:
    # 兼容 payload 容器 + operator_id dict 形态 + header.uuid。
    data = {
        "header": {"uuid": "uuid-2"},
        "payload": {"file_token": "doxcnYYYY", "operator_id": {"open_id": "ou_b"}},
    }
    info = _normalize_drive_edit_event(data)
    assert info["file_token"] == "doxcnYYYY"
    assert info["operator"] == "ou_b"
    assert info["event_id"] == "uuid-2"


def test_normalize_missing_fields_degrades_to_empty() -> None:
    assert _normalize_drive_edit_event({}) == {
        "file_token": "",
        "operator": "",
        "event_id": "",
    }
    # 非 dict 入参也不抛。
    assert _normalize_drive_edit_event(None)["file_token"] == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# handler → durable defer
# ---------------------------------------------------------------------------


async def test_handler_defers_pull_with_unified_lock_and_idempotency() -> None:
    """未映射 operator → initiated_by=system；defer 入参严格匹配（lock=docsync-{file_token}）。"""
    view = FeishuWebhookView()
    defer_mock = AsyncMock(return_value="job-1")
    fetch_mock = AsyncMock()
    with (
        patch("durable.service.DurableTaskService.defer", defer_mock),
        patch("feishu.services.identity.resolve_feishu_user", AsyncMock(return_value=None)),
        patch("services.feishu_doc.FeishuDocClient.get_document_content", fetch_mock),
    ):
        await view._handle_drive_file_edit(_EVENT_SCHEMA)

    defer_mock.assert_awaited_once()
    args, kwargs = defer_mock.await_args
    assert args[0] == "durable_doc_sync_pull"
    assert args[1] == {"file_token": "doxcnXXXX", "event_id": "evt-1"}
    assert kwargs["queue"] == "doc_sync"
    # lock 统一 docsync-{feishu_document_id}（file_token 即 feishu_document_id），与 push/poll 同。
    assert kwargs["lock"] == "docsync-doxcnXXXX"
    assert kwargs["idempotency_key"] == "docpull:doxcnXXXX:evt-1"
    assert kwargs["initiated_by_user_id"] == "system"
    # handler 不回拉正文（取材在后台 durable pull）。
    fetch_mock.assert_not_called()


async def test_handler_attributes_mapped_operator() -> None:
    """operator 命中 Friday 用户 → initiated_by_user_id = 该用户 id。"""
    view = FeishuWebhookView()
    defer_mock = AsyncMock(return_value="job-2")
    mapped_user = SimpleNamespace(id=42)
    with (
        patch("durable.service.DurableTaskService.defer", defer_mock),
        patch(
            "feishu.services.identity.resolve_feishu_user",
            AsyncMock(return_value=mapped_user),
        ),
    ):
        await view._handle_drive_file_edit(_EVENT_SCHEMA)

    _args, kwargs = defer_mock.await_args
    assert kwargs["initiated_by_user_id"] == "42"


async def test_handler_skips_when_file_token_missing() -> None:
    """缺 file_token → 不 defer（不构造身份、不回拉），fail-soft 返回。"""
    view = FeishuWebhookView()
    defer_mock = AsyncMock()
    data = {"header": {"event_id": "e"}, "event": {"operator_id_list": [{"open_id": "ou"}]}}
    with patch("durable.service.DurableTaskService.defer", defer_mock):
        await view._handle_drive_file_edit(data)
    defer_mock.assert_not_awaited()


async def test_handler_defer_failure_is_fail_soft() -> None:
    """defer 抛错 → 吞掉不反噬（退化 TTL 轮询兜底），handler 不抛。"""
    view = FeishuWebhookView()
    defer_mock = AsyncMock(side_effect=RuntimeError("durable down"))
    with (
        patch("durable.service.DurableTaskService.defer", defer_mock),
        patch("feishu.services.identity.resolve_feishu_user", AsyncMock(return_value=None)),
    ):
        # 不抛即通过。
        await view._handle_drive_file_edit(_EVENT_SCHEMA)

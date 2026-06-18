"""上线文档（Bitable）同步：行解析器 + 预览/同步 REST 端点测试。

- 解析器（``parse_release_row`` / ``extract_kanban_id``）：看板id 列优先、feature 分支
  正则回退（m-<数字> / <数字>-m）、父记录跳过、MR 仓库匹配。
- 预览端点：monkeypatch ``fetch_preview`` → 200 透传；未配置凭证 ValueError → 400。
- 同步端点：建 ReleaseBatch（真实经 ReleaseService）+ 每行建 running IngestRun（共享
  batch_id，steps={release,mr_diff}）+ run_in_background 派发 sync_release_row。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from delivery.models import IngestRun, ReleaseBatch
from delivery.services.release_bitable_sync import (
    build_kanban_url,
    extract_kanban_id,
    parse_release_row,
)

pytestmark = pytest.mark.django_db(transaction=True)

MR_URL = "https://gitlab.yc345.tv/frontend/space-admin/-/merge_requests/360"
REPO_INDEX = {("gitlab.yc345.tv", "frontend/space-admin"): "space-admin"}


async def _make_user_headers() -> dict[str, str]:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="release_sync_user", password="pass-123456"
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


# ============================================================================
# 解析器（纯函数）
# ============================================================================


def test_extract_kanban_id_from_column() -> None:
    """看板id 列为纯数字 → 直接取，来源标看板id。"""
    kid, source = extract_kanban_id("6764053712", "feat/whatever")
    assert kid == 6764053712
    assert source == "看板id"


def test_extract_kanban_id_from_branch_prefix() -> None:
    """看板id 列空 → 从分支 m-<数字> 提取。"""
    kid, source = extract_kanban_id("", "feat/m-6764053712-login")
    assert kid == 6764053712
    assert source == "feature分支"


def test_extract_kanban_id_from_branch_suffix() -> None:
    """看板id 列空 → 从分支 <数字>-m 提取。"""
    kid, source = extract_kanban_id("", "feat/6764053712-m")
    assert kid == 6764053712
    assert source == "feature分支"


def test_extract_kanban_id_none() -> None:
    """两处都没有 → None。"""
    kid, source = extract_kanban_id("", "feat/no-id-here")
    assert kid is None
    assert source == ""


def test_build_kanban_url() -> None:
    """看板 id + 空间 key → 飞书工作项详情 URL；缺任一 → 空串。"""
    assert (
        build_kanban_url(6764053712, "abc123")
        == "https://project.feishu.cn/abc123/issue/detail/6764053712"
    )
    assert build_kanban_url(None, "abc123") == ""
    assert build_kanban_url(6764053712, "") == ""


def test_parse_release_row_basic() -> None:
    """完整行：抽业务/MR/看板id/分类/日期 + 命中仓库 + 看板 URL。"""
    record = {
        "record_id": "recABC",
        "fields": {
            "上线业务": "NPC切图替换需求",
            "MR（合并Master）": {"link": MR_URL, "text": MR_URL},
            "feature分支": "feat/npc-img",
            "看板id": "6764053712",
            "上线分类": "前端",
            "上线日期": 1722182400000,
        },
    }
    row = parse_release_row(record, repo_index=REPO_INDEX, feishu_project_key="abc123")
    assert row is not None
    assert row.business == "NPC切图替换需求"
    assert row.mr_url == MR_URL
    assert row.kanban_id == 6764053712
    assert row.kanban_url == "https://project.feishu.cn/abc123/issue/detail/6764053712"
    assert row.category == "前端"
    assert row.release_date == 1722182400000
    assert row.repo_matched is True
    assert row.repo_name == "space-admin"
    assert row.ingestable is True


def test_parse_release_row_no_project_key_empty_url() -> None:
    """无飞书空间 key → kanban_url 为空串（前端降级为纯文本）。"""
    record = {
        "record_id": "recABC",
        "fields": {"上线业务": "x", "看板id": "6764053712"},
    }
    row = parse_release_row(record, repo_index=REPO_INDEX)
    assert row is not None
    assert row.kanban_id == 6764053712
    assert row.kanban_url == ""


def test_parse_release_row_unmatched_repo_not_ingestable() -> None:
    """MR 未命中已落库仓库 → repo_matched False、ingestable False。"""
    record = {
        "record_id": "recX",
        "fields": {
            "上线业务": "某需求",
            "MR（合并Master）": {"link": "https://gitlab.other.com/a/b/-/merge_requests/1"},
        },
    }
    row = parse_release_row(record, repo_index=REPO_INDEX)
    assert row is not None
    assert row.repo_matched is False
    assert row.ingestable is False


def test_parse_release_row_parent_skipped() -> None:
    """既无上线业务又无 MR 的父记录 → None。"""
    record = {"record_id": "recParent", "fields": {"聚合上线服务": "golang升级"}}
    assert parse_release_row(record, repo_index=REPO_INDEX) is None


# ============================================================================
# 预览端点
# ============================================================================


async def test_preview_returns_rows(monkeypatch) -> None:
    """合法请求 → 200 + 透传 fetch_preview 结果。"""
    headers = await _make_user_headers()

    async def _fake_fetch_preview(**kwargs):
        return {
            "rows": [{"record_id": "recABC", "business": "x", "mr_url": MR_URL}],
            "page_token": "next",
            "has_more": True,
            "total": 100,
        }

    monkeypatch.setattr(
        "delivery.services.release_bitable_sync.fetch_preview", _fake_fetch_preview
    )

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/release/bitable/preview/",
        data={"page_size": 1},
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["has_more"] is True
    assert len(body["rows"]) == 1


async def test_preview_no_credentials_400(monkeypatch) -> None:
    """未配置飞书凭证（fetch_preview 抛 ValueError）→ 400。"""
    headers = await _make_user_headers()

    async def _raise(**kwargs):
        raise ValueError("未配置飞书开放平台应用凭证")

    monkeypatch.setattr(
        "delivery.services.release_bitable_sync.fetch_preview", _raise
    )

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/release/bitable/preview/",
        data={},
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 400


async def test_preview_unauthenticated_rejected() -> None:
    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/release/bitable/preview/",
        data={},
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)


# ============================================================================
# 同步端点
# ============================================================================


async def test_sync_dispatches_runs(monkeypatch) -> None:
    """合法勾选行 → 202 + 建 ReleaseBatch + 每行 running IngestRun（共享 batch_id）。"""
    headers = await _make_user_headers()

    recorder = MagicMock(return_value="coro")
    monkeypatch.setattr(
        "delivery.services.release_bitable_sync.sync_release_row", recorder
    )

    def _fake_run_in_background(factory, *, name=None):
        factory()
        return MagicMock()

    monkeypatch.setattr("delivery.api.views.run_in_background", _fake_run_in_background)

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/release/bitable/sync/",
        data={
            "rows": [
                {
                    "record_id": "recABC",
                    "mr_url": MR_URL,
                    "business": "需求A",
                    "kanban_id": 6764053712,
                    "category": "前端",
                },
            ]
        },
        content_type="application/json",
        headers=headers,
    )

    assert resp.status_code == 202, resp.content
    body = resp.json()
    batch_id = body["batch_id"]
    assert batch_id
    assert len(body["runs"]) == 1

    # ReleaseBatch 已建
    assert await ReleaseBatch.objects.filter(id=batch_id).aexists()

    # IngestRun 已建（running，steps 两步，batch_id 一致）
    runs = [r async for r in IngestRun.objects.filter(batch_id=batch_id)]
    assert len(runs) == 1
    assert runs[0].status == IngestRun.Status.RUNNING
    assert set(runs[0].steps.keys()) == {"release", "mr_diff"}

    # sync_release_row 被派发，入参含 batch_id + payload
    recorder.assert_called_once()
    args = recorder.call_args[0]
    assert args[1] == batch_id
    assert args[2]["mr_url"] == MR_URL
    assert args[2]["kanban_id"] == 6764053712


async def test_sync_non_http_mr_400(monkeypatch) -> None:
    """非 http(s) MR → 400，不建 run。"""
    headers = await _make_user_headers()
    monkeypatch.setattr(
        "delivery.api.views.run_in_background", lambda *a, **k: MagicMock()
    )

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/release/bitable/sync/",
        data={"rows": [{"record_id": "r1", "mr_url": "ftp://x/y"}]},
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 400


async def test_sync_unauthenticated_rejected() -> None:
    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/release/bitable/sync/",
        data={"rows": [{"record_id": "r1", "mr_url": MR_URL}]},
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)

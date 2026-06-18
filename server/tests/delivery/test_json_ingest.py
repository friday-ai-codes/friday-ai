"""JSON 批量摄取：空间解析器 + resolve/batch-json 端点 + 工作项关联文档端点。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from delivery.models import IngestRun
from delivery.services.space_resolver import SpaceResolution, aresolve_space

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_user_headers() -> dict[str, str]:
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="json_ingest_user", password="pass-123456"
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


async def _make_project(name: str, key: str):
    from projects.models import Project

    return await Project.objects.acreate(name=name, feishu_project_key=key)


# ============================================================================
# 空间解析器
# ============================================================================


async def test_resolve_space_by_key() -> None:
    await _make_project("学习工具与平台", "study_platform")
    project, reason = await aresolve_space("study_platform")
    assert project is not None
    assert reason == SpaceResolution.BY_KEY


async def test_resolve_space_by_id() -> None:
    p = await _make_project("学习工具与平台", "study_platform")
    project, reason = await aresolve_space(str(p.id))
    assert project is not None
    assert project.id == p.id
    assert reason == SpaceResolution.BY_ID


async def test_resolve_space_by_fuzzy_name() -> None:
    await _make_project("学习工具与平台", "study_platform")
    project, reason = await aresolve_space("学习工具")
    assert project is not None
    assert project.name == "学习工具与平台"
    assert reason == SpaceResolution.BY_NAME_FUZZY


async def test_resolve_space_not_found() -> None:
    await _make_project("学习工具与平台", "study_platform")
    project, reason = await aresolve_space("不存在的空间XYZ")
    assert project is None
    assert reason == SpaceResolution.NOT_FOUND


async def test_resolve_space_ambiguous() -> None:
    await _make_project("测试空间一", "key_one")
    await _make_project("测试空间二", "key_two")
    project, reason = await aresolve_space("测试空间")
    assert project is None
    assert reason == SpaceResolution.AMBIGUOUS


# ============================================================================
# resolve 预览端点
# ============================================================================


async def test_resolve_endpoint_reports_per_item(monkeypatch) -> None:
    await _make_project("学习工具与平台", "study_platform")
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/resolve/",
        data={
            "items": [
                {"space": "学习工具", "work_item_id": 6935339052, "work_item_type": "story"},
                {"space": "不存在XYZ", "work_item_id": 1},
                {"space": "study_platform", "work_item_id": 0},
            ]
        },
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 200, resp.content
    items = resp.json()["items"]
    assert items[0]["resolved"] is True
    assert items[0]["feishu_project_key"] == "study_platform"
    assert items[0]["board_url"].endswith("/study_platform/story/detail/6935339052")
    assert items[1]["resolved"] is False  # 空间未找到
    assert items[2]["resolved"] is False  # work_item_id 非法


# ============================================================================
# batch-json 派发端点
# ============================================================================


async def test_batch_json_dispatches_resolved_and_skips_rest(monkeypatch) -> None:
    await _make_project("学习工具与平台", "study_platform")
    headers = await _make_user_headers()

    recorder = MagicMock(return_value="coro")
    monkeypatch.setattr("delivery.services.json_ingest.run_json_batch", recorder)
    monkeypatch.setattr(
        "delivery.api.views.run_in_background", lambda *a, **k: MagicMock()
    )

    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/batch-json/",
        data={
            "concurrency": 5,
            "items": [
                {"space": "学习工具", "work_item_id": 6935339052, "work_item_type": "story"},
                {"space": "不存在XYZ", "work_item_id": 1},
            ],
        },
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 202, resp.content
    body = resp.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["feishu_project_key"] == "study_platform"
    assert body["runs"][0]["work_item_id"] == 6935339052
    assert len(body["skipped"]) == 1

    batch_id = body["batch_id"]
    runs = [r async for r in IngestRun.objects.filter(batch_id=batch_id)]
    assert len(runs) == 1
    assert set(runs[0].steps.keys()) == {"work_item", "document", "mr_diff"}


async def test_batch_json_unauthenticated_rejected() -> None:
    client = AsyncClient()
    resp = await client.post(
        "/api/delivery/ingest/batch-json/",
        data={"items": [{"space": "x", "work_item_id": 1}]},
        content_type="application/json",
    )
    assert resp.status_code in (401, 403)


# ============================================================================
# 工作项关联文档端点
# ============================================================================


async def test_work_item_artifacts_returns_summary() -> None:
    from delivery.models import WorkItem

    headers = await _make_user_headers()
    await WorkItem.objects.acreate(
        feishu_project_key="study_platform",
        work_item_type="story",
        work_item_id=6935339052,
        title="切图替换需求",
        status_display_name="开发中",
        prd_url="https://project.feishu.cn/study_platform/story/detail/6935339052",
    )

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/artifacts/"
        "?feishu_project_key=study_platform&work_item_type=story&work_item_id=6935339052",
        headers=headers,
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["work_item"]["title"] == "切图替换需求"
    assert body["work_item"]["prd_url"].endswith("/story/detail/6935339052")
    assert body["documents"] == []


async def test_work_item_artifacts_404_when_missing() -> None:
    headers = await _make_user_headers()
    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/artifacts/"
        "?feishu_project_key=nope&work_item_type=story&work_item_id=1",
        headers=headers,
    )
    assert resp.status_code == 404

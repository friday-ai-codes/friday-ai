"""MCP lookup_project_by_branch 守护测试（CURSOR-01）。

覆盖：
- happy（单命中 + 召回 + 写 RetrievalTrace）；
- 无法解析分支名 → fail-soft 空返回；
- 解析成功但无项目 → fail-soft 空候选；
- 多命中 → fail-soft 候选列表（matched=False，不抛）；
- 非项目成员 → packer fail-closed 召回为空（matched 仍命中但 context 空，不泄漏）。
"""

from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from delivery.services import WorkItemIdentity, WorkItemService
from initiatives.services import ProjectService
from interactions.models import RetrievalTrace
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
_URL = "/api/mcp/tools/lookup_project_by_branch/"


@sync_to_async
def _make_space(key="lpb-space"):
    return Space.objects.create(name="S", feishu_project_key=key)


async def _make_work_item(work_item_id: int, feishu_project_key="lpb-wpk"):
    return await WorkItemService().upsert(
        WorkItemIdentity(
            feishu_project_key=feishu_project_key,
            work_item_type="story",
            work_item_id=work_item_id,
        ),
        source="feishu_webhook",
        fetch=False,
    )


async def _make_project(created_by, key="lpb-board"):
    space = await _make_space(key=f"{key}-sp")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=created_by
    )
    return project


@sync_to_async
def _trace_count(source: str) -> int:
    # MCP 链 trace 的 source 落在 payload（基类 _record 不设 model.source 列）。
    return RetrievalTrace.objects.filter(payload__source=source).count()


async def test_happy_single_match_recall_and_trace(mcp_client, access_user) -> None:
    client, _ = mcp_client
    project = await _make_project(access_user, key="lpb-a")
    wi = await _make_work_item(1001)
    await ProjectService().attach_work_item(project_id=project.id, work_item=wi)

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m1001-add-login"}, format="json"
    )
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["matched"] is True
    assert body["work_item_id"] == 1001
    assert body["project"]["id"] == str(project.id)
    assert len(body["candidates"]) == 1
    # MCP 链 RetrievalTrace 已写（补齐 Phase-80 MCP 链）。
    assert await _trace_count("mcp_lookup_project_by_branch") >= 1


async def test_unparseable_branch_fail_soft(mcp_client) -> None:
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "main"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["work_item_id"] is None
    assert body["candidates"] == []


async def test_parseable_no_project_fail_soft(mcp_client) -> None:
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m99999-nope"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False
    assert body["work_item_id"] == 99999
    assert body["candidates"] == []


async def test_multi_match_fail_soft_candidates(mcp_client, access_user) -> None:
    client, _ = mcp_client
    p1 = await _make_project(access_user, key="lpb-m1")
    p2 = await _make_project(access_user, key="lpb-m2")
    # 同数字 work_item_id 不同 feishu_project_key → 两条 WorkItem → 两个项目命中。
    wi1 = await _make_work_item(2002, feishu_project_key="k1")
    wi2 = await _make_work_item(2002, feishu_project_key="k2")
    await ProjectService().attach_work_item(project_id=p1.id, work_item=wi1)
    await ProjectService().attach_work_item(project_id=p2.id, work_item=wi2)

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m2002-x"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is False  # 多命中绝不臆断
    assert len(body["candidates"]) == 2
    assert body["context"] == ""


async def test_non_member_failclosed_empty_context(mcp_client) -> None:
    client, _ = mcp_client
    other = await sync_to_async(User.objects.create_user)(
        username="other-owner", password="x"
    )
    project = await _make_project(other, key="lpb-nm")
    wi = await _make_work_item(3003)
    await ProjectService().attach_work_item(project_id=project.id, work_item=wi)

    resp = await sync_to_async(client.post)(
        _URL, {"branch_name": "feat/xxxx-m3003-x"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    # 命中项目（候选可见），但 token 用户非成员 → packer fail-closed 召回为空，不泄漏内容。
    assert body["matched"] is True
    assert body["context"] == ""


async def test_requires_auth() -> None:
    from rest_framework.test import APIClient

    resp = await sync_to_async(APIClient().post)(
        _URL, {"branch_name": "feat/xxxx-m1-x"}, format="json"
    )
    assert resp.status_code in (401, 403)

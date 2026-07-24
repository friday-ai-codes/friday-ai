"""评论树只读 REST 端点测试（Phase 29-03 Task 2）。

覆盖 ``WorkItemCommentTreeView``（IsAuthenticated）：
- 认证用户 GET 携三元组 → 200 + 评论树投影（含线程层级 + approval 语义）。
- 未认证 → 401/403。
- 缺三元组参数 → 400；work_item 不存在 → 404；非法 work_item_id → 400。
- 端点只读：GET 前后事件行数不变（不旁路 fetch/落库）。

评论事件经 CommentEventService.append_events 单一写入收口预置（INV-6）；
无真实网络，pytest-socket 隔离。异步 ORM 跨连接 → transaction=True。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db(transaction=True)

PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002


async def _make_user_headers() -> dict[str, str]:
    """创建测试用户 + JWT Bearer 头（async）。"""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user = await user_model.objects.acreate_user(
        username="comment_api_user",
        password="comment-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {token.access_token}"}


async def _make_work_item_with_comments():
    """直接落 WorkItem（测试夹具）+ 经单一写入收口预置评论事件（root/reply/approval）。"""
    from delivery.models import WorkItem
    from delivery.services import CommentEventService

    work_item = await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=STORY_ID,
        origin="manual",
    )
    comments = [
        {"id": "c1", "content": "根评论", "created_at": 1700000000000, "author": "u1"},
        {
            "id": "c2",
            "content": "一条回复",
            "created_at": 1700000001000,
            "author": "u2",
            "thread_parent_id": "c1",
        },
        {"id": "c3", "content": "通过，lgtm", "created_at": 1700000002000, "author": "u3"},
    ]
    await CommentEventService().append_events(work_item, comments, source="feishu_webhook")
    return work_item


async def test_comment_tree_authenticated_returns_projection() -> None:
    """认证用户 GET 携三元组 → 200 + 评论树投影（线程层级 + approval 语义）。"""
    headers = await _make_user_headers()
    await _make_work_item_with_comments()

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/comments/",
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["work_item_id"] == STORY_ID

    roots = body["comments"]
    # 顶层两根节点：c1（含 child c2）+ c3（approval）
    assert len(roots) == 2
    by_id = {n["feishu_comment_id"]: n for n in roots}
    assert set(by_id) == {"c1", "c3"}

    # c1 线程层级：含一条回复 c2
    c1 = by_id["c1"]
    assert len(c1["children"]) == 1
    assert c1["children"][0]["feishu_comment_id"] == "c2"
    assert c1["children"][0]["thread_parent_id"] == "c1"

    # c3 approval 语义事件
    c3 = by_id["c3"]
    assert c3["approval_semantic"] == "approve"
    assert c3["event_type"] == "approval"


async def test_comment_tree_unauthenticated_rejected() -> None:
    """未认证 GET → 401/403（IsAuthenticated 守卫，T-29-07）。"""
    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/comments/",
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
    )
    assert resp.status_code in (401, 403)


async def test_comment_tree_missing_params_400() -> None:
    """缺三元组参数 → 400。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/comments/",
        {"feishu_project_key": PROJECT_KEY},
        headers=headers,
    )
    assert resp.status_code == 400


async def test_comment_tree_missing_work_item_404() -> None:
    """work_item 不存在 → 404（只读，不旁路 fetch/落库）。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/comments/",
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": 999999,
        },
        headers=headers,
    )
    assert resp.status_code == 404


async def test_comment_tree_invalid_work_item_id_400() -> None:
    """非法 work_item_id（非整数）→ 400。"""
    headers = await _make_user_headers()

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/comments/",
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": "abc",
        },
        headers=headers,
    )
    assert resp.status_code == 400


async def test_comment_tree_is_read_only() -> None:
    """端点只读：GET 前后事件行数不变（投影读时计算，不写库）。"""
    from delivery.models import WorkItemCommentEvent

    headers = await _make_user_headers()
    await _make_work_item_with_comments()

    before = await WorkItemCommentEvent.objects.acount()

    client = AsyncClient()
    resp = await client.get(
        "/api/delivery/work-items/comments/",
        {
            "feishu_project_key": PROJECT_KEY,
            "work_item_type": "story",
            "work_item_id": STORY_ID,
        },
        headers=headers,
    )
    assert resp.status_code == 200

    after = await WorkItemCommentEvent.objects.acount()
    assert before == after == 3

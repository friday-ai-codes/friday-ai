"""project_comment_tree 投影守护测试（Phase 29-02 Task 2，CMT-02）。

覆盖：从事件流读时投影当前评论树——
- 线程树：replied 事件按 thread_parent_id 挂到父节点 children 下，根节点置顶层。
- 编辑取最新：同 feishu_comment_id 两次 body（模拟 edited 序列）→ 节点 body 为最新。
- 删除标记：deleted 事件 → 节点 is_deleted=True（保留占位维持线程结构）。
- 排序：同层节点按 event_time 升序；投影不写库（事件行数前后不变）。

直接经 ``WorkItemCommentEvent.objects`` 造事件（不走 service），隔离验证投影逻辑。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.django_db(transaction=True)

PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002


def _ts(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


async def _make_work_item():
    from delivery.models import WorkItem, WorkItemOrigin

    return await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=STORY_ID,
        origin=WorkItemOrigin.MANUAL,
        title="评论宿主工作项",
    )


async def _add_event(
    work_item,
    *,
    feishu_comment_id: str,
    event_type: str,
    body: str = "",
    thread_parent_id: str = "",
    author: str = "u1",
    event_ms: int | None = None,
    approval_semantic: str = "none",
):
    from delivery.models import WorkItemCommentEvent

    return await WorkItemCommentEvent.objects.acreate(
        work_item=work_item,
        feishu_comment_id=feishu_comment_id,
        event_type=event_type,
        body=body,
        thread_parent_id=thread_parent_id,
        author=author,
        approval_semantic=approval_semantic,
        event_time=_ts(event_ms) if event_ms is not None else None,
    )


# ============================================================================
# 线程树组装
# ============================================================================


async def test_projection_thread_structure() -> None:
    """replied 按 thread_parent_id 挂父节点 children；根节点置顶层。"""
    from delivery.services import project_comment_tree

    work_item = await _make_work_item()
    await _add_event(
        work_item,
        feishu_comment_id="c1",
        event_type="created",
        body="根评论",
        event_ms=1700000000000,
    )
    await _add_event(
        work_item,
        feishu_comment_id="c2",
        event_type="replied",
        body="回复1",
        thread_parent_id="c1",
        event_ms=1700000100000,
    )
    await _add_event(
        work_item,
        feishu_comment_id="c3",
        event_type="replied",
        body="回复2",
        thread_parent_id="c1",
        event_ms=1700000200000,
    )

    from asgiref.sync import sync_to_async

    tree = await sync_to_async(project_comment_tree)(work_item)

    assert len(tree) == 1
    root = tree[0]
    assert root["feishu_comment_id"] == "c1"
    assert root["body"] == "根评论"
    child_ids = [c["feishu_comment_id"] for c in root["children"]]
    assert child_ids == ["c2", "c3"]


async def test_projection_orphan_reply_promoted_to_root() -> None:
    """父不在集合内的 replied → 提升为顶层（防丢节点）。"""
    from delivery.services import project_comment_tree

    work_item = await _make_work_item()
    await _add_event(
        work_item,
        feishu_comment_id="c2",
        event_type="replied",
        body="孤儿回复",
        thread_parent_id="missing_parent",
        event_ms=1700000000000,
    )

    from asgiref.sync import sync_to_async

    tree = await sync_to_async(project_comment_tree)(work_item)
    assert len(tree) == 1
    assert tree[0]["feishu_comment_id"] == "c2"


# ============================================================================
# 编辑取最新
# ============================================================================


async def test_projection_edit_takes_latest_body() -> None:
    """同 feishu_comment_id 两次 body（created→edited）→ 节点 body 为最新。"""
    from delivery.services import project_comment_tree

    work_item = await _make_work_item()
    await _add_event(
        work_item,
        feishu_comment_id="c1",
        event_type="created",
        body="原始内容",
        event_ms=1700000000000,
    )
    await _add_event(
        work_item,
        feishu_comment_id="c1",
        event_type="edited",
        body="编辑后内容",
        event_ms=1700000500000,
    )

    from asgiref.sync import sync_to_async

    tree = await sync_to_async(project_comment_tree)(work_item)
    assert len(tree) == 1  # 同一评论归并为单节点
    assert tree[0]["body"] == "编辑后内容"
    assert tree[0]["event_type"] == "edited"


async def test_projection_approval_semantic_latest_non_none() -> None:
    """approval_semantic 取最新非 none。"""
    from delivery.services import project_comment_tree

    work_item = await _make_work_item()
    await _add_event(
        work_item,
        feishu_comment_id="c1",
        event_type="created",
        body="先评论",
        event_ms=1700000000000,
    )
    await _add_event(
        work_item,
        feishu_comment_id="c1",
        event_type="approval",
        body="通过",
        approval_semantic="approve",
        event_ms=1700000500000,
    )

    from asgiref.sync import sync_to_async

    tree = await sync_to_async(project_comment_tree)(work_item)
    assert tree[0]["approval_semantic"] == "approve"


# ============================================================================
# 删除标记
# ============================================================================


async def test_projection_delete_marks_node() -> None:
    """deleted 事件 → 节点 is_deleted=True（保留占位维持线程结构）。"""
    from delivery.services import project_comment_tree

    work_item = await _make_work_item()
    await _add_event(
        work_item,
        feishu_comment_id="c1",
        event_type="created",
        body="父评论",
        event_ms=1700000000000,
    )
    await _add_event(
        work_item,
        feishu_comment_id="c2",
        event_type="replied",
        body="子评论",
        thread_parent_id="c1",
        event_ms=1700000100000,
    )
    await _add_event(
        work_item,
        feishu_comment_id="c1",
        event_type="deleted",
        body="父评论",
        event_ms=1700000200000,
    )

    from asgiref.sync import sync_to_async

    tree = await sync_to_async(project_comment_tree)(work_item)
    # 占位保留 → 子节点仍挂在删除的父下
    assert len(tree) == 1
    assert tree[0]["is_deleted"] is True
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["feishu_comment_id"] == "c2"


# ============================================================================
# 排序 + 读时不写库
# ============================================================================


async def test_projection_siblings_sorted_by_event_time() -> None:
    """同层节点按 event_time 升序（乱序入库仍升序输出）。"""
    from delivery.services import project_comment_tree

    work_item = await _make_work_item()
    # 故意乱序 ingest（event_time 反序）
    await _add_event(
        work_item, feishu_comment_id="c3", event_type="created", body="第三", event_ms=1700000300000
    )
    await _add_event(
        work_item, feishu_comment_id="c1", event_type="created", body="第一", event_ms=1700000100000
    )
    await _add_event(
        work_item, feishu_comment_id="c2", event_type="created", body="第二", event_ms=1700000200000
    )

    from asgiref.sync import sync_to_async

    tree = await sync_to_async(project_comment_tree)(work_item)
    assert [n["feishu_comment_id"] for n in tree] == ["c1", "c2", "c3"]


async def test_projection_is_read_only_no_db_writes() -> None:
    """投影读时计算不写库：事件行数前后不变（CMT-02）。"""
    from delivery.models import WorkItemCommentEvent
    from delivery.services import project_comment_tree

    work_item = await _make_work_item()
    await _add_event(
        work_item, feishu_comment_id="c1", event_type="created", body="a", event_ms=1700000000000
    )
    await _add_event(
        work_item, feishu_comment_id="c1", event_type="edited", body="b", event_ms=1700000500000
    )

    before = await WorkItemCommentEvent.objects.filter(work_item=work_item).acount()

    from asgiref.sync import sync_to_async

    await sync_to_async(project_comment_tree)(work_item)

    after = await WorkItemCommentEvent.objects.filter(work_item=work_item).acount()
    assert before == after == 2  # 投影不增不改事件行


async def test_aproject_comment_tree_async_wrapper() -> None:
    """aproject_comment_tree async 包装可直接 await。"""
    from delivery.services import aproject_comment_tree

    work_item = await _make_work_item()
    await _add_event(
        work_item, feishu_comment_id="c1", event_type="created", body="根", event_ms=1700000000000
    )

    tree = await aproject_comment_tree(work_item)
    assert len(tree) == 1
    assert tree[0]["feishu_comment_id"] == "c1"

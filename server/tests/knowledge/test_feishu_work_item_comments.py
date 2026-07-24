"""feishu_work_item 评论入图守护测试（Plan 34-02 Task 1 / RREF-02）。

覆盖（per PLAN behavior 五类）：

- 已落库 delivery WorkItem + 若干 WorkItemCommentEvent → normalize content 含
  ``## 评论`` 段且包含各评论 body 文本（评论入图，可被既有检索召回）。
- 无 delivery WorkItem（三元组查无）→ content 不含评论段、不抛、warning
  （缺段不缺实体，§1.4 降级）。
- 有 WorkItem 但无评论事件 → content 不含评论段（空树不渲染空段），不抛。
- 评论内容不变两次 normalize → content 逐字一致（hash-no-version 守护）。
- deleted 评论节点（is_deleted=True）仍以占位 ``（已删除）`` 保留（维持线程结构）。

不新增 EntityKind；feishu_document.py 不改动。无真实网络：feishu client
monkeypatch，pytest-socket 第二保险。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from delivery.models import (
    CommentEventType,
    WorkItem,
    WorkItemCommentEvent,
    WorkItemOrigin,
)
from knowledge.ingestion import IngestionRequest
from knowledge.sources import feishu_work_item
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002
SOURCE_ID = f"{PROJECT_KEY}:story:{STORY_ID}"


def _make_request() -> IngestionRequest:
    return IngestionRequest(
        source_kind="feishu_work_item",
        source_id=SOURCE_ID,
        trigger="test_feishu_work_item_comments",
    )


async def _make_project() -> Space:
    return await Space.objects.acreate(name="测试项目", feishu_project_key=PROJECT_KEY)


async def _make_work_item() -> WorkItem:
    return await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=STORY_ID,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )


async def _make_comment_event(
    work_item: WorkItem,
    *,
    cid: str,
    body: str,
    author: str = "u1",
    event_type: str = CommentEventType.CREATED,
    thread_parent_id: str = "",
    ms: int = 1700000000000,
) -> WorkItemCommentEvent:
    return await WorkItemCommentEvent.objects.acreate(
        work_item=work_item,
        feishu_comment_id=cid,
        thread_parent_id=thread_parent_id,
        event_type=event_type,
        author=author,
        body=body,
        event_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
    )


@pytest.fixture
def mock_feishu_client(monkeypatch):
    """monkeypatch feishu client（get_work_item 空 fields → 无 doc 取材，聚焦评论段）。"""
    cfg = SimpleNamespace(name="测试需求", description="需求描述", status="developing")

    class _FakeFeishuClient:
        async def get_work_item(self, *, project_key, work_item_id, work_item_type):
            return SimpleNamespace(
                name=cfg.name,
                description=cfg.description,
                status=cfg.status,
                fields={},
            )

        async def get_work_item_relations(self, *, project_key, work_item_id, work_item_type):
            return []

    monkeypatch.setattr(
        feishu_work_item, "create_feishu_client_for_project", lambda project: _FakeFeishuClient()
    )
    return cfg


# ============================================================================
# ① 评论树并入 work_item 投影 content（评论入图，可召回）
# ============================================================================


async def test_comment_tree_folded_into_content(mock_feishu_client) -> None:
    """delivery WorkItem + 评论事件 → content 含 `## 评论` 段 + 各 body 子串命中。"""
    await _make_project()
    work_item = await _make_work_item()
    await _make_comment_event(work_item, cid="c1", body="这是根评论需要澄清", ms=1700000000000)
    await _make_comment_event(
        work_item,
        cid="c2",
        body="回复确认通过",
        event_type=CommentEventType.REPLIED,
        thread_parent_id="c1",
        ms=1700000100000,
    )

    events = await feishu_work_item.normalize(_make_request())

    assert len(events) == 1
    content = events[0].content
    assert "## 评论" in content
    assert "这是根评论需要澄清" in content
    assert "回复确认通过" in content
    # 评论树天然关联到本 work_item 实体（payload 元数据 + 同一 source_id）
    assert events[0].source_id == SOURCE_ID
    assert events[0].payload["comment_count"] == 2


# ============================================================================
# ② 无 delivery WorkItem → 缺段不缺实体（降级 guard ⑤）
# ============================================================================


async def test_no_work_item_no_comment_section(mock_feishu_client) -> None:
    """三元组查无 delivery WorkItem → content 无评论段、不抛、事件照常产出。"""
    await _make_project()
    # 不建 delivery WorkItem

    events = await feishu_work_item.normalize(_make_request())

    assert len(events) == 1
    assert "## 评论" not in events[0].content
    assert events[0].payload["comment_count"] == 0


# ============================================================================
# ③ 有 WorkItem 但无评论事件 → 空树不渲染空段
# ============================================================================


async def test_work_item_without_comments_no_section(mock_feishu_client) -> None:
    """有 delivery WorkItem 但无评论事件 → content 不含评论段（空树不渲染）。"""
    await _make_project()
    await _make_work_item()

    events = await feishu_work_item.normalize(_make_request())

    assert len(events) == 1
    assert "## 评论" not in events[0].content
    assert events[0].payload["comment_count"] == 0


# ============================================================================
# ④ hash-no-version：评论不变两次 normalize content 逐字一致
# ============================================================================


async def test_content_deterministic_across_normalize(mock_feishu_client) -> None:
    """评论内容不变两次 normalize → content 逐字一致（hash 相等不翻版本）。"""
    await _make_project()
    work_item = await _make_work_item()
    await _make_comment_event(work_item, cid="c1", body="稳定内容", ms=1700000000000)

    first = (await feishu_work_item.normalize(_make_request()))[0].content
    second = (await feishu_work_item.normalize(_make_request()))[0].content

    assert "## 评论" in first
    assert first == second


# ============================================================================
# ⑤ deleted 节点占位保留（维持线程结构）
# ============================================================================


async def test_deleted_comment_placeholder_retained(mock_feishu_client) -> None:
    """deleted 评论节点（is_deleted=True）以占位 `（已删除）` 保留 + body 保留。"""
    await _make_project()
    work_item = await _make_work_item()
    await _make_comment_event(work_item, cid="c1", body="原始评论内容", ms=1700000000000)
    await _make_comment_event(
        work_item,
        cid="c1",
        body="原始评论内容",
        event_type=CommentEventType.DELETED,
        ms=1700000100000,
    )

    events = await feishu_work_item.normalize(_make_request())

    content = events[0].content
    assert "## 评论" in content
    assert "（已删除）" in content
    assert "原始评论内容" in content

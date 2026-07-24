"""WorkItemCommentEvent 模型层单测（Phase 29-01，CMT-01/CMT-02）。

纯 ORM、无网络（pytest-socket 隔离）。核心覆盖：
- 五种 event_type + 三种 approval_semantic 可落库读回；attachments 默认 list、
  approval_semantic 默认 none。
- append-only：同一 feishu_comment_id 先 created 再 edited 两行并存（不就地改写），
  event_time/ingested_at 可区分（CMT-02）。
- work_item CASCADE：删 WorkItem，关联 comment_events 随删。
- (work_item, event_time) 索引存在。

fixture 取值参考 DOMAIN §16 实测（story 1000000002）。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from delivery.models import (
    ApprovalSemantic,
    CommentEventType,
    WorkItem,
    WorkItemCommentEvent,
    WorkItemOrigin,
)

pytestmark = pytest.mark.django_db

# DOMAIN §16 实测自然键
PROJECT_KEY = "000000000000000000000001"


def _make_work_item(work_item_id: int = 1000000002, **overrides) -> WorkItem:
    """创建一个 story WorkItem（origin=manual），允许 override。"""
    defaults = dict(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=work_item_id,
        feishu_project_simple_name="example_platform",
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )
    defaults.update(overrides)
    return WorkItem.objects.create(**defaults)


def test_all_event_types_and_defaults_readback():
    """五种 event_type 可落库读回；attachments 默认 list、approval_semantic 默认 none。"""
    wi = _make_work_item()
    for idx, event_type in enumerate(CommentEventType.values):
        WorkItemCommentEvent.objects.create(
            work_item=wi,
            feishu_comment_id=f"c{idx}",
            event_type=event_type,
        )
    assert wi.comment_events.count() == 5
    assert set(wi.comment_events.values_list("event_type", flat=True)) == set(
        CommentEventType.values
    )
    # 默认值
    sample = wi.comment_events.first()
    assert sample.attachments == []
    assert sample.approval_semantic == ApprovalSemantic.NONE
    assert sample.thread_parent_id == ""
    assert sample.author == ""
    assert sample.body == ""
    assert sample.ingested_at is not None


def test_all_approval_semantics_readback():
    """三种 approval_semantic 可落库读回（none/approve/reject）。"""
    wi = _make_work_item()
    for idx, semantic in enumerate(ApprovalSemantic.values):
        WorkItemCommentEvent.objects.create(
            work_item=wi,
            feishu_comment_id=f"a{idx}",
            event_type=CommentEventType.APPROVAL,
            approval_semantic=semantic,
        )
    assert set(wi.comment_events.values_list("approval_semantic", flat=True)) == set(
        ApprovalSemantic.values
    )


def test_append_only_edit_is_new_row():
    """append-only：同一 feishu_comment_id 先 created 再 edited 两行并存（不就地改写，CMT-02）。"""
    wi = _make_work_item()
    t1 = datetime(2026, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 15, 11, 0, 0, tzinfo=timezone.utc)
    created = WorkItemCommentEvent.objects.create(
        work_item=wi,
        feishu_comment_id="cmt-1",
        event_type=CommentEventType.CREATED,
        body="原始内容",
        event_time=t1,
    )
    edited = WorkItemCommentEvent.objects.create(
        work_item=wi,
        feishu_comment_id="cmt-1",
        event_type=CommentEventType.EDITED,
        body="编辑后内容",
        event_time=t2,
    )
    # 两行并存——同一评论的两个事件，未就地改写旧行
    same_comment = wi.comment_events.filter(feishu_comment_id="cmt-1").order_by("event_time")
    assert same_comment.count() == 2
    assert list(same_comment.values_list("event_type", flat=True)) == [
        CommentEventType.CREATED,
        CommentEventType.EDITED,
    ]
    # 旧行 body 未被改写
    created.refresh_from_db()
    assert created.body == "原始内容"
    assert edited.body == "编辑后内容"
    # event_time / ingested_at 可区分
    assert created.event_time < edited.event_time
    assert created.pk != edited.pk


def test_work_item_cascade_delete():
    """删 WorkItem，关联 comment_events 随 CASCADE 删除。"""
    wi = _make_work_item()
    WorkItemCommentEvent.objects.create(
        work_item=wi,
        feishu_comment_id="cmt-x",
        event_type=CommentEventType.CREATED,
    )
    assert WorkItemCommentEvent.objects.count() == 1
    wi.delete()
    assert WorkItemCommentEvent.objects.count() == 0


def test_work_item_event_time_index_present():
    """(work_item, event_time) 索引存在（DOMAIN §12.4）。"""
    index_field_sets = [tuple(idx.fields) for idx in WorkItemCommentEvent._meta.indexes]
    assert ("work_item", "event_time") in index_field_sets

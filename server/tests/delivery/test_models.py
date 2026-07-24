"""delivery 模型层单测（Phase 28-01）。

纯 ORM、无网络（pytest-socket 隔离）。核心覆盖：
- WorkItem 字段可读回（origin=manual）。
- 三元组重复创建抛 IntegrityError（INV-1 由 DB unique_together 强制）。
- (work_item, facet) 重复 SyncState 抛 IntegrityError。
- WorkItemRelation 带 target_external_id 占位（target_work_item=None）成功。
- WorkItemStatusEvent(pre/cur state_key) 成功。

fixture 取值参考 DOMAIN §16 实测（story 1000000002 / issue 1000000006）。
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from delivery.models import (
    SyncFacet,
    SyncStatus,
    WorkItem,
    WorkItemOrigin,
    WorkItemRelation,
    WorkItemStatusEvent,
    WorkItemSyncState,
)
from delivery.models.relation import RelationType

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
        status_state_key="fi46o4r6m",
        status_display_name="Sprint计划",
    )
    defaults.update(overrides)
    return WorkItem.objects.create(**defaults)


def test_create_work_item_readback():
    """创建 WorkItem（origin=manual）后字段可读回，JSON 默认值正确。"""
    wi = _make_work_item()
    fetched = WorkItem.objects.get(pk=wi.pk)
    assert fetched.feishu_project_key == PROJECT_KEY
    assert fetched.work_item_type == "story"
    assert fetched.work_item_id == 1000000002
    assert fetched.origin == WorkItemOrigin.MANUAL
    assert fetched.status_display_name == "Sprint计划"
    # JSONField 默认值
    assert fetched.feishu_fields == []
    assert fetched.field_provenance == {}
    # enhanced/writeback 默认空
    assert fetched.business_line_normalized == ""
    assert fetched.feishu_chat_id == ""


def test_duplicate_triple_raises_integrity_error():
    """同三元组重复创建 → IntegrityError（INV-1 由 DB unique_together 强制）。"""
    _make_work_item()
    with pytest.raises(IntegrityError):
        WorkItem.objects.create(
            feishu_project_key=PROJECT_KEY,
            work_item_type="story",
            work_item_id=1000000002,
            origin=WorkItemOrigin.FEISHU_WEBHOOK,
        )


def test_different_triple_allowed():
    """不同三元组（不同 type / id）可共存，不触发唯一约束。"""
    _make_work_item(work_item_id=1000000002)
    _make_work_item(work_item_id=1000000006, work_item_type="issue")
    assert WorkItem.objects.count() == 2


def test_sync_state_unique_per_facet():
    """同 (work_item, facet) 二次创建 → IntegrityError。"""
    wi = _make_work_item()
    WorkItemSyncState.objects.create(
        work_item=wi,
        facet=SyncFacet.BASIC_FIELDS,
        status=SyncStatus.COMPLETE,
        source=WorkItemOrigin.MANUAL,
    )
    with pytest.raises(IntegrityError):
        WorkItemSyncState.objects.create(
            work_item=wi,
            facet=SyncFacet.BASIC_FIELDS,
            status=SyncStatus.PARTIAL,
            source=WorkItemOrigin.FEISHU_WEBHOOK,
        )


def test_sync_state_distinct_facets_allowed():
    """同 work_item 不同 facet 可共存。"""
    wi = _make_work_item()
    WorkItemSyncState.objects.create(
        work_item=wi,
        facet=SyncFacet.BASIC_FIELDS,
        status=SyncStatus.COMPLETE,
        source=WorkItemOrigin.MANUAL,
    )
    WorkItemSyncState.objects.create(
        work_item=wi,
        facet=SyncFacet.RELATIONS,
        status=SyncStatus.MISSING,
        source=WorkItemOrigin.MANUAL,
    )
    assert wi.sync_states.count() == 2


def test_relation_with_external_id_placeholder():
    """WorkItemRelation 带 target_external_id 占位（target_work_item=None）成功。"""
    wi = _make_work_item()
    rel = WorkItemRelation.objects.create(
        source_work_item=wi,
        target_work_item=None,
        target_external_id=1000000004,
        relation_type=RelationType.BELONGS_TO_PROJECT,
        source_field_key="field_000008",
    )
    fetched = WorkItemRelation.objects.get(pk=rel.pk)
    assert fetched.target_work_item is None
    assert fetched.target_external_id == 1000000004
    assert fetched.relation_type == RelationType.BELONGS_TO_PROJECT
    # origin 默认 feishu_field
    assert fetched.origin == "feishu_field"
    assert wi.out_relations.count() == 1


def test_status_event_append():
    """WorkItemStatusEvent(pre/cur state_key) 成功创建（append-only）。"""
    wi = _make_work_item()
    ev = WorkItemStatusEvent.objects.create(
        work_item=wi,
        pre_state_key="state_1",
        cur_state_key="fi46o4r6m",
        operator="tester",
    )
    fetched = WorkItemStatusEvent.objects.get(pk=ev.pk)
    assert fetched.pre_state_key == "state_1"
    assert fetched.cur_state_key == "fi46o4r6m"
    assert fetched.ingested_at is not None
    assert wi.status_events.count() == 1

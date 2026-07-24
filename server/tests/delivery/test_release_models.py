"""Release 账本宽容模型守护单测（Phase 31-01，REL-01）。

纯 ORM、无网络（pytest-socket 隔离）、无 ReleaseService 依赖——直接建实例验证
schema / 约束 / FK / raw_row 无损。核心覆盖：

- raw_row 无损：复杂嵌套 JSON（dict/list/中文/数字/bool/None）写入 ReleaseBatch +
  ReleaseRecord，读回与原 dict 完全相等（REL-01 物理保证：adapter 演进不丢数据）。
- natural key 占位：work_item=None + work_item_external_id 占位 + bitable_record_key
  可创建读回（对齐 WorkItemRelation / Document.work_item 占位范式）。
- natural key 唯一：相同非空 bitable_record_key 二次 create 抛 IntegrityError；
  两个空键行可共存（条件唯一豁免空键，镜像 document uniq 范式）。
- 关联：ReleaseRecord.batch / ReleaseArtifact.release_record FK 命中；artifact_type
  枚举落库读回。
- work_item 连 FK：真实 WorkItem 经 related_name="release_records" 反查命中。
- build_bitable_record_key helper：拼接 / 空段豁免。

fixture 自然键参考 DOMAIN §16 实测。
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from delivery.models import (
    ReleaseArtifact,
    ReleaseArtifactType,
    ReleaseBatch,
    ReleaseRecord,
    ReleaseSource,
    WorkItem,
    WorkItemOrigin,
    build_bitable_record_key,
)

pytestmark = pytest.mark.django_db(transaction=True)

# DOMAIN §16 实测自然键
PROJECT_KEY = "000000000000000000000001"

# 含嵌套 dict/list/中文/数字/bool/None 的复杂原始行（REL-01 无损守护）
COMPLEX_ROW = {
    "需求标题": "上线广和支付模块",
    "fields": {
        "数量": 42,
        "比例": 3.14,
        "已完成": True,
        "备注": None,
        "标签": ["MR", "回归", "灰度"],
    },
    "records": [
        {"id": "rec1", "状态": "已上线"},
        {"id": "rec2", "状态": "回滚"},
    ],
}


def _make_work_item(work_item_id: int = 1000000002, **overrides) -> WorkItem:
    """创建一个 story WorkItem（origin=manual），允许 override。"""
    defaults = dict(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=work_item_id,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )
    defaults.update(overrides)
    return WorkItem.objects.create(**defaults)


def _make_batch(**overrides) -> ReleaseBatch:
    """创建一个 bitable 来源 ReleaseBatch，允许 override。"""
    defaults = dict(
        name="2026-06 上线窗口",
        source=ReleaseSource.BITABLE,
    )
    defaults.update(overrides)
    return ReleaseBatch.objects.create(**defaults)


def test_build_bitable_record_key():
    """helper 拼接 natural key；任一段为空返回 ""（无法定位即不立 key）。"""
    assert build_bitable_record_key("appX", "tblY", "recZ") == "appX:tblY:recZ"
    assert build_bitable_record_key("", "tblY", "recZ") == ""
    assert build_bitable_record_key("appX", "", "recZ") == ""
    assert build_bitable_record_key("appX", "tblY", "") == ""


def test_release_batch_raw_row_lossless():
    """ReleaseBatch.raw_row 复杂 JSON 写入 → 读回完全相等（REL-01 核心）。"""
    batch = _make_batch(raw_row=COMPLEX_ROW)
    fetched = ReleaseBatch.objects.get(pk=batch.pk)
    assert fetched.raw_row == COMPLEX_ROW
    # 默认值与字段读回
    assert fetched.source == ReleaseSource.BITABLE
    assert fetched.name == "2026-06 上线窗口"
    assert fetched.external_ref == ""
    assert fetched.released_at is None


def test_release_record_raw_row_lossless():
    """ReleaseRecord.raw_row 复杂 JSON 写入 → 读回完全相等（REL-01 核心）。"""
    batch = _make_batch()
    rec = ReleaseRecord.objects.create(batch=batch, raw_row=COMPLEX_ROW)
    fetched = ReleaseRecord.objects.get(pk=rec.pk)
    assert fetched.raw_row == COMPLEX_ROW
    # 默认值
    assert fetched.work_item is None
    assert fetched.work_item_external_id is None
    assert fetched.bitable_record_key == ""
    assert fetched.status == ""
    assert fetched.note == ""


def test_release_record_external_id_placeholder():
    """work_item 未落库：work_item=None + work_item_external_id 占位 + natural key 可建可读。"""
    batch = _make_batch()
    key = build_bitable_record_key("appX", "tblY", "recZ")
    rec = ReleaseRecord.objects.create(
        batch=batch,
        work_item=None,
        work_item_external_id=1000000002,
        bitable_record_key=key,
    )
    fetched = ReleaseRecord.objects.get(pk=rec.pk)
    assert fetched.work_item is None
    assert fetched.work_item_external_id == 1000000002
    assert fetched.bitable_record_key == "appX:tblY:recZ"


def test_bitable_record_key_unique_when_non_empty():
    """相同非空 bitable_record_key 二次 create → IntegrityError（条件唯一）。"""
    batch = _make_batch()
    key = build_bitable_record_key("appX", "tblY", "recZ")
    ReleaseRecord.objects.create(batch=batch, bitable_record_key=key)
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            ReleaseRecord.objects.create(batch=batch, bitable_record_key=key)


def test_empty_bitable_record_key_can_coexist():
    """两个空 bitable_record_key 行可共存（条件唯一豁免空键）。"""
    batch = _make_batch()
    ReleaseRecord.objects.create(batch=batch, bitable_record_key="")
    ReleaseRecord.objects.create(batch=batch, bitable_record_key="")
    assert batch.records.filter(bitable_record_key="").count() == 2


def test_release_record_batch_fk_reverse():
    """ReleaseRecord.batch FK 命中 ReleaseBatch，经 related_name="records" 反查。"""
    batch = _make_batch()
    ReleaseRecord.objects.create(batch=batch, bitable_record_key="appX:tblY:rec1")
    ReleaseRecord.objects.create(batch=batch, bitable_record_key="appX:tblY:rec2")
    assert batch.records.count() == 2


def test_release_artifact_type_enum_readback():
    """ReleaseArtifact.artifact_type 枚举落库读回；release_record FK 反查命中。"""
    batch = _make_batch()
    rec = ReleaseRecord.objects.create(batch=batch, bitable_record_key="appX:tblY:rec1")
    art = ReleaseArtifact.objects.create(
        release_record=rec,
        artifact_type=ReleaseArtifactType.MR,
        ref="https://gitlab.example.com/group/proj/-/merge_requests/42",
        payload={"sha": "abc123", "title": "fix: 支付回调"},
    )
    fetched = ReleaseArtifact.objects.get(pk=art.pk)
    assert fetched.artifact_type == ReleaseArtifactType.MR
    assert fetched.payload == {"sha": "abc123", "title": "fix: 支付回调"}
    # 反查 artifacts
    assert rec.artifacts.count() == 1
    assert rec.artifacts.first().pk == art.pk


def test_release_record_work_item_fk_and_reverse():
    """work_item 连 FK：真实 WorkItem 经 related_name="release_records" 反查命中。"""
    wi = _make_work_item()
    batch = _make_batch()
    rec = ReleaseRecord.objects.create(
        batch=batch,
        work_item=wi,
        bitable_record_key="appX:tblY:recW",
    )
    assert wi.release_records.count() == 1
    assert wi.release_records.first().pk == rec.pk

"""ReleaseService 行为守护测试（Phase 31-02 Task 3）。

覆盖 REL-01 / INV-6 写入收口与 CONTEXT Grey Area 3：

- ingest 建批 + N 记录：``ingest_batch`` 传 N 行 → 1 个 ReleaseBatch + N 条
  ReleaseRecord，每条 raw_row 与传入原始行完全相等（REL-01 无损）。
- 幂等 upsert：同非空 ``bitable_record_key`` 二次 ingest → 不新增 ReleaseRecord
  （收敛同行），raw_row 刷新为最新。
- work_item 反查命中：先落 WorkItem(work_item_id=X)，raw_row 占位映射含
  work_item_external_id=X → 该 ReleaseRecord.work_item 连 FK 命中。
- work_item 反查未命中：work_item_external_id=Y（无对应 WorkItem）→ work_item=None
  且 work_item_external_id=Y 占位，不抛。
- 降级：某行畸形（非 dict）触发异常不回滚整批，其余行与 batch 仍落库（best-effort）。

无真实网络（pytest-socket 隔离；ReleaseService 不回源，raw_rows 由测试直接传入）。
异步 + sync_to_async 跨线程写库 → transaction=True（与 30-02 service 测试同理）。
"""

from __future__ import annotations

import pytest

from delivery.models import (
    ReleaseBatch,
    ReleaseRecord,
    ReleaseSource,
    WorkItem,
    WorkItemOrigin,
)
from delivery.services import ReleaseService

pytestmark = pytest.mark.django_db(transaction=True)

# DOMAIN §16 实测自然键
PROJECT_KEY = "000000000000000000000001"
WORK_ITEM_ID = 1000000002


async def _make_work_item(work_item_id: int = WORK_ITEM_ID) -> WorkItem:
    """建一个 story WorkItem（origin=manual），作为 work_item 反查目标。"""
    return await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=work_item_id,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )


# ============================================================================
# ingest 建批 + N 记录 + raw_row 无损
# ============================================================================


async def test_ingest_batch_creates_batch_and_records_lossless() -> None:
    """ingest N 行 → 1 ReleaseBatch + N ReleaseRecord，raw_row 与传入原始行完全相等。"""
    raw_rows = [
        {"bitable_record_key": f"app:tbl:rec{i}", "status": "released", "col_x": i}
        for i in range(3)
    ]
    service = ReleaseService()

    batch = await service.ingest_batch(raw_rows=raw_rows, source=ReleaseSource.BITABLE)

    assert await ReleaseBatch.objects.acount() == 1
    assert await ReleaseRecord.objects.filter(batch=batch).acount() == 3
    for raw in raw_rows:
        record = await ReleaseRecord.objects.aget(
            bitable_record_key=raw["bitable_record_key"]
        )
        # REL-01：raw_row 原样无损保留。
        assert record.raw_row == raw
        assert record.status == "released"


async def test_ingest_batch_preserves_batch_meta_raw_row() -> None:
    """batch_meta 原始内容落 ReleaseBatch.raw_row 保留（REL-01）。"""
    meta = {"name": "v1.2.0", "external_ref": "app/tbl", "extra": {"window": "晚高峰"}}
    service = ReleaseService()

    batch = await service.ingest_batch(
        raw_rows=[], source=ReleaseSource.MANUAL, batch_meta=meta
    )

    fresh = await ReleaseBatch.objects.aget(id=batch.id)
    assert fresh.raw_row == meta
    assert fresh.name == "v1.2.0"
    assert fresh.external_ref == "app/tbl"


# ============================================================================
# 幂等 upsert（同 bitable_record_key 收敛同行）
# ============================================================================


async def test_ingest_idempotent_by_bitable_record_key() -> None:
    """同非空 bitable_record_key 二次 ingest 不新增 ReleaseRecord，raw_row 刷新为最新。"""
    key = "app:tbl:rec-dup"
    service = ReleaseService()

    await service.ingest_batch(
        raw_rows=[{"bitable_record_key": key, "v": "first"}],
        source=ReleaseSource.BITABLE,
    )
    await service.ingest_batch(
        raw_rows=[{"bitable_record_key": key, "v": "second"}],
        source=ReleaseSource.BITABLE,
    )

    # 收敛同行：记录数不增（幂等）。
    assert await ReleaseRecord.objects.filter(bitable_record_key=key).acount() == 1
    record = await ReleaseRecord.objects.aget(bitable_record_key=key)
    # raw_row 刷新为最新原始行。
    assert record.raw_row == {"bitable_record_key": key, "v": "second"}


async def test_empty_key_rows_not_deduped() -> None:
    """空 key 行无去重依据 → 多行共存（豁免唯一约束）。"""
    service = ReleaseService()

    batch = await service.ingest_batch(
        raw_rows=[{"col": "a"}, {"col": "b"}],
        source=ReleaseSource.BITABLE,
    )

    assert await ReleaseRecord.objects.filter(batch=batch).acount() == 2


# ============================================================================
# work_item 反查（命中连 FK / 未命中占位不抛）
# ============================================================================


async def test_workitem_backfill_hit_links_fk() -> None:
    """work_item_external_id 命中已落库 WorkItem → ReleaseRecord.work_item 连 FK。"""
    wi = await _make_work_item()
    service = ReleaseService()

    await service.ingest_batch(
        raw_rows=[
            {"bitable_record_key": "app:tbl:hit", "work_item_external_id": WORK_ITEM_ID}
        ],
        source=ReleaseSource.BITABLE,
    )

    record = await ReleaseRecord.objects.aget(bitable_record_key="app:tbl:hit")
    assert record.work_item_id == wi.id
    assert record.work_item_external_id == WORK_ITEM_ID


async def test_workitem_backfill_miss_keeps_placeholder() -> None:
    """work_item_external_id 未命中 → work_item=None 且占位保留，不抛。"""
    missing_id = 9_999_999_999
    service = ReleaseService()

    await service.ingest_batch(
        raw_rows=[
            {"bitable_record_key": "app:tbl:miss", "work_item_external_id": missing_id}
        ],
        source=ReleaseSource.BITABLE,
    )

    record = await ReleaseRecord.objects.aget(bitable_record_key="app:tbl:miss")
    assert record.work_item_id is None
    assert record.work_item_external_id == missing_id


# ============================================================================
# 降级（畸形行不回滚整批）
# ============================================================================


async def test_ingest_malformed_row_does_not_rollback_batch() -> None:
    """某行畸形（非 dict）触发异常不回滚整批，batch 与其余行仍落库（best-effort）。"""
    raw_rows = [
        {"bitable_record_key": "app:tbl:ok1", "v": 1},
        "not-a-dict",  # 触发 raw_row.get AttributeError
        {"bitable_record_key": "app:tbl:ok2", "v": 2},
    ]
    service = ReleaseService()

    batch = await service.ingest_batch(raw_rows=raw_rows, source=ReleaseSource.BITABLE)

    # batch 已建，两条有效行落库，畸形行被跳过（不冒泡致整批失败）。
    assert await ReleaseBatch.objects.filter(id=batch.id).aexists()
    assert await ReleaseRecord.objects.filter(batch=batch).acount() == 2


# ============================================================================
# work_item_external_id 非整型容错（脏值不丢整行，WR-03）
# ============================================================================


@pytest.mark.parametrize(
    "dirty_value",
    [
        pytest.param("not-an-int", id="str"),
        pytest.param({"k": "v"}, id="dict"),
        pytest.param([1, 2], id="list"),
    ],
)
async def test_non_integer_external_id_persists_record_lossless(dirty_value) -> None:
    """work_item_external_id 非整型 → 仍无损落库（raw_row 保留 + work_item/external_id 留空），绝不丢行。"""
    raw = {
        "bitable_record_key": "app:tbl:dirty",
        "work_item_external_id": dirty_value,
        "status": "released",
    }
    service = ReleaseService()

    batch = await service.ingest_batch(
        raw_rows=[raw], source=ReleaseSource.BITABLE
    )

    # 整行未被丢弃：仍落 1 条 ReleaseRecord。
    assert await ReleaseRecord.objects.filter(batch=batch).acount() == 1
    record = await ReleaseRecord.objects.aget(bitable_record_key="app:tbl:dirty")
    # raw_row 无损保留原始脏值（REL-01）。
    assert record.raw_row == raw
    # 占位字段对脏值容错：work_item 留空、external_id 留 null（不让脏值吃掉整行）。
    assert record.work_item_id is None
    assert record.work_item_external_id is None
    assert record.status == "released"


# ============================================================================
# batch 级幂等（同 external_ref 收敛同批，不累积空批次，WR-02）
# ============================================================================


async def test_ingest_batch_idempotent_by_external_ref() -> None:
    """同非空 external_ref 二次 ingest_batch 收敛回同一 ReleaseBatch（不新建空批次）。"""
    meta = {"external_ref": "app:tbl", "name": "first"}
    service = ReleaseService()

    batch1 = await service.ingest_batch(
        raw_rows=[{"bitable_record_key": "app:tbl:r1", "v": 1}],
        source=ReleaseSource.BITABLE,
        batch_meta=meta,
    )
    batch2 = await service.ingest_batch(
        raw_rows=[{"bitable_record_key": "app:tbl:r1", "v": 2}],
        source=ReleaseSource.BITABLE,
        batch_meta={"external_ref": "app:tbl", "name": "second"},
    )

    # 收敛同批：仅 1 个 ReleaseBatch（幂等，不累积空批次）。
    assert batch1.id == batch2.id
    assert await ReleaseBatch.objects.acount() == 1
    # 已存在批次元信息刷新为最新（raw_row 无损覆盖）。
    fresh = await ReleaseBatch.objects.aget(id=batch1.id)
    assert fresh.name == "second"


async def test_ingest_batch_empty_external_ref_not_deduped() -> None:
    """空 external_ref 无去重依据 → 多批共存（豁免唯一约束）。"""
    service = ReleaseService()

    batch1 = await service.ingest_batch(raw_rows=[], source=ReleaseSource.MANUAL)
    batch2 = await service.ingest_batch(raw_rows=[], source=ReleaseSource.MANUAL)

    assert batch1.id != batch2.id
    assert await ReleaseBatch.objects.acount() == 2

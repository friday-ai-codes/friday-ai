"""`knowledge.models` 三模型约束 / 枚举兜底 / 版本链回溯测试（KMOD-01/02/03）。

覆盖：
KMOD-01（实体）
1. 四类 kind 各落库一条成功，字段读回一致
2. 同 (kind, source_kind, source_id) 二次 create → IntegrityError（uniq_kentity_natural_key）
3. kind / origin 非法值绕过 full_clean 直接 create → IntegrityError（DB CheckConstraint 兜底）
4. generate_entity_id 同参幂等 / 不同 kind 不同 UUID

KMOD-03（版本链）
5. v1→v2→v3 supersedes 链：按 version 号回溯 + 沿 FK 反向回溯
6. 同 entity 同 version 二次 create → IntegrityError（uniq_kversion_entity_version）
7. 同 entity 两行 is_latest=True → IntegrityError（uniq_kversion_one_latest）
8. 删除被 supersedes 引用的 v1 → ProtectedError（失效置位不删除保险）
9. invalid_at <= valid_at → IntegrityError（kversion_valid_range）

KMOD-02（边）
10. 四时间戳字段齐备；置位 invalid_at 后行仍存在（失效是置位不是删除）
11. 同 (source, target, relation) 两条活跃边 → IntegrityError（uniq_kedge_active）；
    第一条失效后再建 → 成功（条件唯一仅约束活跃边）
12. target_entity / target_chunk_id 双空、双填 → IntegrityError（kedge_target_xor）
13. relation 非法值 / invalid_at <= valid_at → IntegrityError

索引
14. fanout 查询 EXPLAIN QUERY PLAN 走 idx_kedge_fanout（SQLite）
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEntity,
    generate_entity_id,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# KMOD-01：实体落库与 natural key / 枚举约束
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [k.value for k in EntityKind])
def test_entity_four_kinds_create_and_readback(entity_factory, kind: str) -> None:
    """四类 kind 各落库一条成功，source_kind/source_id/origin/event_time 读回一致。"""
    event_time = timezone.now()
    entity = entity_factory(
        kind=kind,
        origin=EntityOrigin.CHAT,
        source_kind="coding_plan",
        source_id=f"sid-{kind}",
        event_time=event_time,
    )
    fetched = KnowledgeEntity.objects.get(pk=entity.pk)
    assert fetched.kind == kind
    assert fetched.origin == EntityOrigin.CHAT
    assert fetched.source_kind == "coding_plan"
    assert fetched.source_id == f"sid-{kind}"
    assert fetched.event_time == event_time


def test_entity_natural_key_duplicate_rejected(entity_factory) -> None:
    """同 (kind, source_kind, source_id) 二次 create → IntegrityError（uniq_kentity_natural_key）。"""
    entity_factory(kind=EntityKind.WORK_ITEM, source_kind="feishu_work_item", source_id="p:t:1")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            KnowledgeEntity.objects.create(
                # 换一个 id 绕开 PK 冲突，专门触发 natural key 唯一约束
                id=uuid.uuid4(),
                kind=EntityKind.WORK_ITEM,
                origin=EntityOrigin.FEISHU,
                source_kind="feishu_work_item",
                source_id="p:t:1",
                title="重复实体",
                event_time=timezone.now(),
            )


def test_entity_bogus_kind_rejected_at_db_level() -> None:
    """kind 非法值绕过 full_clean 直接 create → IntegrityError（kentity_kind_valid DB 兜底）。"""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            KnowledgeEntity.objects.create(
                id=uuid.uuid4(),
                kind="bogus",
                origin=EntityOrigin.FEISHU,
                source_kind="feishu_work_item",
                source_id="p:t:bogus-kind",
                title="非法 kind",
                event_time=timezone.now(),
            )


def test_entity_bogus_origin_rejected_at_db_level() -> None:
    """origin 非法值绕过 full_clean 直接 create → IntegrityError（kentity_origin_valid DB 兜底）。"""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            KnowledgeEntity.objects.create(
                id=uuid.uuid4(),
                kind=EntityKind.WORK_ITEM,
                origin="bogus",
                source_kind="feishu_work_item",
                source_id="p:t:bogus-origin",
                title="非法 origin",
                event_time=timezone.now(),
            )


def test_generate_entity_id_deterministic_and_kind_sensitive() -> None:
    """generate_entity_id 同参幂等（uuid5 确定性）；不同 kind 不同 UUID。"""
    eid1 = generate_entity_id("work_item", "feishu_work_item", "p:t:1")
    eid2 = generate_entity_id("work_item", "feishu_work_item", "p:t:1")
    eid3 = generate_entity_id("tech_plan", "feishu_work_item", "p:t:1")
    assert eid1 == eid2
    assert eid1 != eid3


# ---------------------------------------------------------------------------
# Phase 100（KNOW-01）：learning_case 枚举扩展
# ---------------------------------------------------------------------------


def test_generate_entity_id_learning_case_deterministic() -> None:
    """learning_case natural key 同参两次派生同 id（Phase 100 规则表新行）。"""
    source_id = str(uuid.uuid4())
    eid1 = generate_entity_id("learning_case", "learning_case", source_id)
    eid2 = generate_entity_id("learning_case", "learning_case", source_id)
    assert eid1 == eid2


def test_entity_learning_case_kind_passes_check_constraint(entity_factory) -> None:
    """kind=learning_case 落库过 kentity_kind_valid CHECK 约束（migration 0008 放行）。"""
    entity = entity_factory(
        kind=EntityKind.LEARNING_CASE,
        origin=EntityOrigin.MCP,
        source_kind="learning_case",
        source_id=str(uuid.uuid4()),
    )
    fetched = KnowledgeEntity.objects.get(pk=entity.pk)
    assert fetched.kind == EntityKind.LEARNING_CASE


def test_entity_bogus_kind_still_rejected_after_learning_case_extension() -> None:
    """枚举扩展后非法 kind 仍被 kentity_kind_valid 拒绝（Phase 100 约束回归）。"""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            KnowledgeEntity.objects.create(
                id=uuid.uuid4(),
                kind="bogus_case",
                origin=EntityOrigin.MCP,
                source_kind="learning_case",
                source_id=str(uuid.uuid4()),
                title="非法 kind（Phase 100 回归）",
                event_time=timezone.now(),
            )


# ---------------------------------------------------------------------------
# KMOD-03：supersedes 版本链
# ---------------------------------------------------------------------------


def _make_version_chain(entity_factory, version_factory):
    """构造 v1→v2→v3 链（is_latest 仅 v3），供版本链用例复用。"""
    entity = entity_factory()
    v1 = version_factory(entity, version=1, content="v1 内容", is_latest=False)
    v2 = version_factory(entity, version=2, content="v2 内容", is_latest=False, supersedes=v1)
    v3 = version_factory(entity, version=3, content="v3 内容", is_latest=True, supersedes=v2)
    return entity, v1, v2, v3


def test_version_chain_lookup_by_version_number(entity_factory, version_factory) -> None:
    """v1→v2→v3 链按 version 号查回任意旧版本，内容正确，latest 仅 v3。"""
    entity, v1, v2, v3 = _make_version_chain(entity_factory, version_factory)
    assert entity.versions.get(version=1).content == "v1 内容"
    assert entity.versions.get(version=2).content == "v2 内容"
    assert entity.versions.filter(is_latest=True).count() == 1
    assert entity.versions.get(is_latest=True).pk == v3.pk


def test_version_chain_backtrack_via_supersedes_fk(entity_factory, version_factory) -> None:
    """沿 supersedes FK 反向回溯 v3→v2→v1，链尾 supersedes 为 None。"""
    _, v1, v2, v3 = _make_version_chain(entity_factory, version_factory)
    assert v3.supersedes_id == v2.pk
    assert v3.supersedes.supersedes_id == v1.pk
    assert v3.supersedes.supersedes.supersedes is None


def test_version_duplicate_entity_version_rejected(entity_factory, version_factory) -> None:
    """同 entity 同 version 二次 create → IntegrityError（uniq_kversion_entity_version）。"""
    entity = entity_factory()
    version_factory(entity, version=1, is_latest=False)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            version_factory(entity, version=1, is_latest=False)


def test_version_two_latest_rows_rejected(entity_factory, version_factory) -> None:
    """同 entity 两行 is_latest=True → IntegrityError（uniq_kversion_one_latest 条件唯一）。"""
    entity = entity_factory()
    version_factory(entity, version=1, is_latest=True)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            version_factory(entity, version=2, is_latest=True)


def test_version_protected_delete_of_superseded(entity_factory, version_factory) -> None:
    """删除被 supersedes 引用的 v1 → ProtectedError（PROTECT 失效置位不删除保险）。"""
    _, v1, _v2, _v3 = _make_version_chain(entity_factory, version_factory)
    with pytest.raises(ProtectedError):
        v1.delete()


def test_version_invalid_at_not_after_valid_at_rejected(entity_factory, version_factory) -> None:
    """invalid_at <= valid_at → IntegrityError（kversion_valid_range 时间次序兜底）。"""
    entity = entity_factory()
    now = timezone.now()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            version_factory(entity, version=1, valid_at=now, invalid_at=now)


def test_version_vector_synced_defaults_false(entity_factory, version_factory) -> None:
    """新建版本默认 vector_synced=False（Phase 13 幂等短路的向量侧凭据）。

    短路条件 = content_hash 相同 AND vector_synced——堵住"DB 已 commit、
    向量未写入"窗口（Pitfall 2）；摄取核心在向量 upsert 成功后置 True。
    """
    entity = entity_factory()
    version = version_factory(entity, version=1)
    assert version.vector_synced is False
    version.refresh_from_db()
    assert version.vector_synced is False


# ---------------------------------------------------------------------------
# KMOD-02：bi-temporal 边
# ---------------------------------------------------------------------------


def test_edge_four_timestamps_and_invalidate_keeps_row(entity_factory, edge_factory) -> None:
    """四时间戳齐备：created_at 自动写入、invalid_at/expired_at 为 NULL；
    置位 invalid_at 后行仍存在（失效是置位不是删除）。"""
    a, b = entity_factory(), entity_factory()
    edge = edge_factory(a, b)
    assert edge.created_at is not None
    assert edge.valid_at is not None
    assert edge.invalid_at is None
    assert edge.expired_at is None

    edge.invalid_at = edge.valid_at + datetime.timedelta(minutes=1)
    edge.save(update_fields=["invalid_at"])
    edge.refresh_from_db()
    assert edge.invalid_at is not None  # 行仍存在且失效已置位


def test_edge_active_duplicate_rejected_then_allowed_after_invalidate(
    entity_factory, edge_factory
) -> None:
    """同 (source, target, relation) 两条活跃边 → IntegrityError（uniq_kedge_active）；
    第一条 invalid_at 置位后再建第二条 → 成功（条件唯一仅约束活跃边）。"""
    a, b = entity_factory(), entity_factory()
    first = edge_factory(a, b, relation=EdgeRelation.HAS_PLAN)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            edge_factory(a, b, relation=EdgeRelation.HAS_PLAN)

    first.invalid_at = first.valid_at + datetime.timedelta(minutes=1)
    first.save(update_fields=["invalid_at"])
    second = edge_factory(a, b, relation=EdgeRelation.HAS_PLAN)
    assert second.pk != first.pk


def test_edge_target_both_null_rejected(entity_factory, edge_factory) -> None:
    """target_entity 与 target_chunk_id 双空 → IntegrityError（kedge_target_xor）。"""
    a = entity_factory()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            edge_factory(a, target_entity=None)


def test_edge_target_both_filled_rejected(entity_factory, edge_factory) -> None:
    """target_entity 与 target_chunk_id 双填 → IntegrityError（kedge_target_xor）。"""
    a, b = entity_factory(), entity_factory()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            edge_factory(
                a,
                target_entity=b,
                target_chunk_id=uuid.uuid4(),
                relation=EdgeRelation.MODIFIES_CHUNK,
            )


def test_edge_chunk_target_only_allowed(entity_factory, edge_factory) -> None:
    """仅填 target_chunk_id（MODIFIES_CHUNK 弱引用形态）→ 成功（XOR 另一分支）。"""
    a = entity_factory()
    edge = edge_factory(
        a,
        target_entity=None,
        target_chunk_id=uuid.uuid4(),
        relation=EdgeRelation.MODIFIES_CHUNK,
    )
    assert edge.target_entity is None
    assert edge.target_chunk_id is not None


def test_edge_bogus_relation_rejected_at_db_level(entity_factory, edge_factory) -> None:
    """relation 非法值绕过 full_clean 直接 create → IntegrityError（kedge_relation_valid）。"""
    a, b = entity_factory(), entity_factory()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            edge_factory(a, b, relation="BOGUS_REL")


def test_edge_invalid_at_not_after_valid_at_rejected(entity_factory, edge_factory) -> None:
    """invalid_at <= valid_at → IntegrityError（kedge_valid_range 时间次序兜底）。"""
    a, b = entity_factory(), entity_factory()
    now = timezone.now()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            edge_factory(a, b, valid_at=now, invalid_at=now)


# ---------------------------------------------------------------------------
# 索引：fanout 查询走 idx_kedge_fanout（SQLite EXPLAIN QUERY PLAN）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    connection.vendor != "sqlite",
    reason="EXPLAIN QUERY PLAN 为 SQLite 专有语法；PG 小数据集下 planner 可合法选 seq scan，索引断言不可移植",
)
def test_edge_fanout_query_uses_fanout_index(entity_factory) -> None:
    """按 (source_entity_id, relation) 查询应走 idx_kedge_fanout 索引。"""
    a = entity_factory()
    with connection.cursor() as cur:
        cur.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM knowledge_knowledgeedge "
            "WHERE source_entity_id = %s AND relation = %s",
            [str(a.pk), EdgeRelation.RELATES_TO.value],
        )
        rows = cur.fetchall()
    plan_text = " ".join(str(row) for row in rows)
    assert "idx_kedge_fanout" in plan_text, f"plan: {plan_text}"

"""`code_relations.models` 模型行为测试（contract 8 条用例）。

覆盖：
1. ChunkRegistry upsert 同 chunk_id 不同 content_hash 路径（update_or_create）
2. chunk_id 确定性（同三元组同 UUID）
3. chunk_id 分散性（三元组任一字段变化 → 不同 UUID）
4. ChunkEdge 6 类边正常插入（共享 source/target 不同 edge_type）
5. ChunkEdge edge_type typo 拒绝（小写 / 半角下划线变体 / 拼写错误）
6. ChunkEdge weight 越界 validator 拒绝（-0.1 / 1.1）+ 边界正常（0.0 / 0.5 / 1.0）
7. ChunkEdge weight CheckConstraint DB 层拒绝（绕过 validator 直接 .create）
8. ChunkEdge unique 三元组冲突 → IntegrityError + 索引 EXPLAIN 走 idx_chunkedge_target
"""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from code_relations.utils import generate_chunk_id

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# 用例 1：ChunkRegistry upsert（同 chunk_id 不同 content_hash）
# ---------------------------------------------------------------------------


def test_chunk_registry_upsert_same_id_diff_content_hash(repository) -> None:
    """同 chunk_id 两次 update_or_create：第二次走 update 路径，content_hash 已更新。"""
    cid = generate_chunk_id(str(repository.id), "src/foo.py", 0)
    h1 = "a" * 64
    h2 = "b" * 64

    obj1, created1 = ChunkRegistry.objects.update_or_create(
        chunk_id=cid,
        defaults={
            "content_hash": h1,
            "repository": repository,
            "file_path": "src/foo.py",
            "chunk_index": 0,
        },
    )
    assert created1 is True
    assert obj1.content_hash == h1

    obj2, created2 = ChunkRegistry.objects.update_or_create(
        chunk_id=cid,
        defaults={
            "content_hash": h2,
            "repository": repository,
            "file_path": "src/foo.py",
            "chunk_index": 0,
        },
    )
    assert created2 is False
    assert obj2.chunk_id == cid
    assert obj2.content_hash == h2
    assert ChunkRegistry.objects.count() == 1


# ---------------------------------------------------------------------------
# 用例 2-3：chunk_id 确定性与分散性（与 plan test_utils.py 互证）
# ---------------------------------------------------------------------------


def test_chunk_id_deterministic_same_triplet() -> None:
    """同三元组两次生成必须完全相等（防御性测试，跨 plan 互证）。"""
    cid1 = generate_chunk_id("repo-X", "src/a.py", 0)
    cid2 = generate_chunk_id("repo-X", "src/a.py", 0)
    assert cid1 == cid2


@pytest.mark.parametrize(
    ("triplet_a", "triplet_b"),
    [
        (("repo-X", "src/a.py", 0), ("repo-Y", "src/a.py", 0)),
        (("repo-X", "src/a.py", 0), ("repo-X", "src/b.py", 0)),
        (("repo-X", "src/a.py", 0), ("repo-X", "src/a.py", 1)),
    ],
)
def test_chunk_id_differs_per_triplet_field(
    triplet_a: tuple[str, str, int], triplet_b: tuple[str, str, int]
) -> None:
    """三元组任一字段不同 → chunk_id 必须不同。"""
    cid_a = generate_chunk_id(*triplet_a)
    cid_b = generate_chunk_id(*triplet_b)
    assert cid_a != cid_b


# ---------------------------------------------------------------------------
# 用例 4：6 类边正常插入（共享 source/target 但 edge_type 不同 → unique 允许）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("edge_type", [e.value for e in EdgeType])
def test_chunkedge_edge_types_insert_ok(repository, edge_type: str) -> None:
    """EdgeType.value 各自可以正常 .save() 插入（共享 source/target 不冲突）。"""
    src = uuid.uuid4()
    tgt = uuid.uuid4()
    edge = ChunkEdge.objects.create(
        source_chunk_id=src,
        target_chunk_id=tgt,
        edge_type=edge_type,
        weight=0.5,
        metadata={},
        repository=repository,
    )
    assert edge.edge_type == edge_type
    assert ChunkEdge.objects.filter(edge_type=edge_type).exists()


def test_chunkedge_same_source_target_diff_edge_type_unique_allows(repository) -> None:
    """同 (source, target) 但不同 edge_type 应当全部允许写入。"""
    src = uuid.uuid4()
    tgt = uuid.uuid4()
    for et in EdgeType:
        ChunkEdge.objects.create(
            source_chunk_id=src,
            target_chunk_id=tgt,
            edge_type=et.value,
            weight=0.3,
            metadata={"sentinel": et.value},
            repository=repository,
        )
    assert (
        ChunkEdge.objects.filter(source_chunk_id=src, target_chunk_id=tgt).count()
        == len(EdgeType)
    )


# ---------------------------------------------------------------------------
# 用例 5：edge_type typo 拒绝（full_clean choices 校验）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_type", ["call", "Co_Changed", "COCHANGED"])
def test_chunkedge_edge_type_typo_rejected(repository, bad_type: str) -> None:
    """edge_type typo（小写 / 拼写错误 / 大小写混合）必须被 full_clean 拒绝。"""
    edge = ChunkEdge(
        source_chunk_id=uuid.uuid4(),
        target_chunk_id=uuid.uuid4(),
        edge_type=bad_type,
        weight=0.5,
        metadata={},
        repository=repository,
    )
    with pytest.raises(ValidationError):
        edge.full_clean()


# ---------------------------------------------------------------------------
# 用例 6：weight 越界 validator 拒绝 + 边界正常
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("good_weight", [0.0, 0.5, 1.0])
def test_chunkedge_weight_boundary_ok(repository, good_weight: float) -> None:
    """weight 边界值 0.0 / 0.5 / 1.0 必须通过 full_clean 校验。"""
    edge = ChunkEdge(
        source_chunk_id=uuid.uuid4(),
        target_chunk_id=uuid.uuid4(),
        edge_type=EdgeType.CALL,
        weight=good_weight,
        metadata={},
        repository=repository,
    )
    edge.full_clean()


@pytest.mark.parametrize("bad_weight", [-0.1, 1.1, -1.0, 2.0])
def test_chunkedge_weight_out_of_range_validator(
    repository, bad_weight: float
) -> None:
    """weight 越界（< 0 或 > 1）full_clean 抛 ValidationError。"""
    edge = ChunkEdge(
        source_chunk_id=uuid.uuid4(),
        target_chunk_id=uuid.uuid4(),
        edge_type=EdgeType.CALL,
        weight=bad_weight,
        metadata={},
        repository=repository,
    )
    with pytest.raises(ValidationError):
        edge.full_clean()


# ---------------------------------------------------------------------------
# 用例 7：CheckConstraint DB 层拒绝越界 weight（绕过 validator 直接 .create）
# ---------------------------------------------------------------------------


def test_chunkedge_weight_check_constraint_db_level(repository) -> None:
    """绕过 validator 直接 .create(weight=-0.5) → DB CheckConstraint 拒绝（IntegrityError）。"""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ChunkEdge.objects.create(
                source_chunk_id=uuid.uuid4(),
                target_chunk_id=uuid.uuid4(),
                edge_type=EdgeType.CALL,
                weight=-0.5,
                metadata={},
                repository=repository,
            )


# ---------------------------------------------------------------------------
# 用例 7b（work item）：edge_type DB 层 CheckConstraint 兜底（绕过 full_clean）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_type", ["call", "Co_Changed", "COCHANGED", ""])
def test_chunkedge_edge_type_check_constraint_db_level(
    repository, bad_type: str
) -> None:
    """绕过 full_clean 直接 .create(edge_type="call") → DB CheckConstraint 拒绝（IntegrityError）。

    保证 initial implementation EdgeBuilder 即便走 bulk_create / .create() 不调 full_clean，
    typo edge_type 仍被 DB 层挡下（满足 ROADMAP 成功条件 #4 双保险）。
    """
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ChunkEdge.objects.create(
                source_chunk_id=uuid.uuid4(),
                target_chunk_id=uuid.uuid4(),
                edge_type=bad_type,
                weight=0.5,
                metadata={},
                repository=repository,
            )


# ---------------------------------------------------------------------------
# 用例 8：unique 三元组冲突 → IntegrityError
# ---------------------------------------------------------------------------


def test_chunkedge_unique_triple_collision(repository) -> None:
    """同 (source, target, edge_type) 二次 .create() → IntegrityError。"""
    src = uuid.uuid4()
    tgt = uuid.uuid4()
    ChunkEdge.objects.create(
        source_chunk_id=src,
        target_chunk_id=tgt,
        edge_type=EdgeType.CALL,
        weight=0.5,
        metadata={},
        repository=repository,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ChunkEdge.objects.create(
                source_chunk_id=src,
                target_chunk_id=tgt,
                edge_type=EdgeType.CALL,
                weight=0.7,
                metadata={"dup": True},
                repository=repository,
            )


# ---------------------------------------------------------------------------
# 用例 8（续）：EXPLAIN QUERY PLAN 走 idx_chunkedge_target 索引
# ---------------------------------------------------------------------------


def test_chunkedge_fan_in_query_uses_target_index(repository) -> None:
    """按 target_chunk_id 查询应走 idx_chunkedge_target 索引（SQLite EXPLAIN QUERY PLAN）。"""
    tgt = uuid.uuid4()
    with connection.cursor() as cur:
        cur.execute(
            'EXPLAIN QUERY PLAN '
            'SELECT * FROM code_relations_chunkedge WHERE target_chunk_id = %s',
            [str(tgt)],
        )
        rows = cur.fetchall()
    plan_text = " ".join(str(row) for row in rows)
    assert "idx_chunkedge_target" in plan_text, f"plan: {plan_text}"

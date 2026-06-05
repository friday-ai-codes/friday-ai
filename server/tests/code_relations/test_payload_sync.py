"""code_relations.payload_sync.aggregate_top_neighbors 测试（per implementation contract/24/25）。

覆盖：
- 基础聚合（50 chunks × 30 邻居 → 50 updates × top-20）
- top-N 排序（weight desc + chunk_id 字典序稳定）
- 5KB 截断阶梯（20→15→10→5→1）
- 空 dirty 短路
- dirty 含无边 chunk → 不入 updates
- 单次 SQL（无 N+1，filter 调一次）
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from code_relations.constants import MAX_NEIGHBORS_PER_CHUNK, MAX_PAYLOAD_SIZE_BYTES
from code_relations.models import ChunkEdge, EdgeType
from code_relations.payload_sync import aggregate_top_neighbors


@pytest.mark.django_db(transaction=True)
async def test_empty_dirty_returns_empty_without_sql() -> None:
    """空 dirty_chunk_ids → 立即返回 []，不走 SQL。"""
    with patch.object(ChunkEdge.objects, "filter") as mock_filter:
        result = await aggregate_top_neighbors("11111111-1111-1111-1111-111111111111", [])
    assert result == []
    mock_filter.assert_not_called()


@pytest.mark.django_db(transaction=True)
async def test_basic_aggregation_50_chunks_30_neighbors_each(repository) -> None:
    """50 dirty × 30 邻居 → 50 updates × top-20。"""
    sources = [uuid.uuid4() for _ in range(50)]
    edges_to_create: list[ChunkEdge] = []
    for src in sources:
        for j in range(30):
            edges_to_create.append(
                ChunkEdge(
                    source_chunk_id=src,
                    target_chunk_id=uuid.uuid4(),
                    edge_type=EdgeType.CALL,
                    weight=0.01 + j * 0.03,
                    metadata={},
                    repository=repository,
                )
            )
    await ChunkEdge.objects.abulk_create(edges_to_create)

    updates = await aggregate_top_neighbors(str(repository.id), sources)

    assert len(updates) == 50
    for _point_id, payload in updates:
        assert len(payload["related_chunks"]) == MAX_NEIGHBORS_PER_CHUNK


@pytest.mark.django_db(transaction=True)
async def test_top_n_sorted_weight_desc(repository) -> None:
    """单 chunk 25 邻居 weight 0..0.99 → top 20 严格 weight desc，第 21..25 被截。"""
    src = uuid.uuid4()
    targets = [uuid.uuid4() for _ in range(25)]
    edges = [
        ChunkEdge(
            source_chunk_id=src,
            target_chunk_id=tgt,
            edge_type=EdgeType.CALL,
            weight=i * 0.04,
            metadata={},
            repository=repository,
        )
        for i, tgt in enumerate(targets)
    ]
    await ChunkEdge.objects.abulk_create(edges)

    updates = await aggregate_top_neighbors(str(repository.id), [src])
    assert len(updates) == 1
    point_id, payload = updates[0]
    assert point_id == str(src)
    chunks = payload["related_chunks"]
    assert len(chunks) == MAX_NEIGHBORS_PER_CHUNK

    weights = [c[2] for c in chunks]
    assert weights == sorted(weights, reverse=True)
    assert weights[0] == pytest.approx(24 * 0.04)
    assert weights[-1] == pytest.approx(5 * 0.04)


@pytest.mark.django_db(transaction=True)
async def test_same_weight_chunk_id_lexicographic(repository) -> None:
    """5 邻居全 weight=0.5 → 按 chunk_id 字典序稳定排序。"""
    src = uuid.uuid4()
    targets = sorted([uuid.uuid4() for _ in range(5)], key=str)
    edges = [
        ChunkEdge(
            source_chunk_id=src,
            target_chunk_id=tgt,
            edge_type=EdgeType.IMPORT,
            weight=0.5,
            metadata={},
            repository=repository,
        )
        for tgt in targets
    ]
    await ChunkEdge.objects.abulk_create(edges)

    updates = await aggregate_top_neighbors(str(repository.id), [src])
    _, payload = updates[0]
    chunk_ids_in_payload = [c[0] for c in payload["related_chunks"]]
    assert chunk_ids_in_payload == [str(t) for t in targets]


@pytest.mark.django_db(transaction=True)
async def test_payload_size_truncated_below_5kb(repository) -> None:
    """100 邻居 + 长 chunk_id 全长 → 截断后 payload bytes ≤ 5KB。

    注：metadata 不进 payload（只进 ChunkEdge 表），所以靠 chunk_id + edge_type 字符串
    + JSON overhead 撑大；UUID4 长度 36 + edge_type 最长 'CO_CHANGED' = 10，单条邻居
    JSON 序列化约 60-70 byte，100 条 ≈ 7KB 触顶。
    """
    src = uuid.uuid4()
    edges = [
        ChunkEdge(
            source_chunk_id=src,
            target_chunk_id=uuid.uuid4(),
            edge_type=EdgeType.CO_CHANGED,
            weight=1.0 - i * 0.005,
            metadata={},
            repository=repository,
        )
        for i in range(100)
    ]
    await ChunkEdge.objects.abulk_create(edges)

    updates = await aggregate_top_neighbors(str(repository.id), [src])
    assert len(updates) == 1
    _, payload = updates[0]
    payload_bytes = len(json.dumps(payload).encode())
    assert payload_bytes <= MAX_PAYLOAD_SIZE_BYTES
    assert len(payload["related_chunks"]) <= MAX_NEIGHBORS_PER_CHUNK


@pytest.mark.django_db(transaction=True)
async def test_dirty_chunk_without_edges_excluded(repository) -> None:
    """dirty 含 chunk 但 ChunkEdge 表空 → updates 不含该 chunk。"""
    src_with_edge = uuid.uuid4()
    src_without_edge = uuid.uuid4()
    await ChunkEdge.objects.abulk_create(
        [
            ChunkEdge(
                source_chunk_id=src_with_edge,
                target_chunk_id=uuid.uuid4(),
                edge_type=EdgeType.SAME_FILE,
                weight=0.3,
                metadata={},
                repository=repository,
            )
        ]
    )

    updates = await aggregate_top_neighbors(
        str(repository.id), [src_with_edge, src_without_edge]
    )
    point_ids = {point_id for point_id, _ in updates}
    assert point_ids == {str(src_with_edge)}


@pytest.mark.django_db(transaction=True)
async def test_single_sql_call_no_n_plus_one(repository) -> None:
    """50 dirty + 多边 → ChunkEdge.objects.filter 全过程**只调一次**（不 N+1）。"""
    sources = [uuid.uuid4() for _ in range(50)]
    edges = [
        ChunkEdge(
            source_chunk_id=src,
            target_chunk_id=uuid.uuid4(),
            edge_type=EdgeType.CALL,
            weight=0.5,
            metadata={},
            repository=repository,
        )
        for src in sources
    ]
    await ChunkEdge.objects.abulk_create(edges)

    original_filter = ChunkEdge.objects.filter
    call_count = 0

    def _spy_filter(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        return original_filter(*args, **kwargs)

    with patch.object(ChunkEdge.objects, "filter", side_effect=_spy_filter):
        await aggregate_top_neighbors(str(repository.id), sources)

    assert call_count == 1, f"expected 1 SQL filter call, got {call_count}"


@pytest.mark.django_db(transaction=True)
async def test_oversize_after_all_truncate_steps_skipped(
    repository, monkeypatch
) -> None:
    """work item 回归：阶梯走到 limit=1 后单条邻居仍超 MAX_PAYLOAD_SIZE_BYTES →
    update 被 skip + log warning，不流到 batch_set_payload。"""
    src = uuid.uuid4()
    await ChunkEdge.objects.abulk_create(
        [
            ChunkEdge(
                source_chunk_id=src,
                target_chunk_id=uuid.uuid4(),
                edge_type=EdgeType.CALL,
                weight=0.5,
                metadata={},
                repository=repository,
            )
        ]
    )

    # 临时把 MAX_PAYLOAD_SIZE_BYTES 调到 1（任何 payload 必超），强制最后一档仍超限
    monkeypatch.setattr(
        "code_relations.payload_sync.MAX_PAYLOAD_SIZE_BYTES", 1
    )
    updates = await aggregate_top_neighbors(str(repository.id), [src])
    assert updates == []

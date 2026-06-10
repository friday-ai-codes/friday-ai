"""hop2_expander —— implementation 编排器二跳 ORM 扩散测试（contract / contract）。

覆盖矩阵（10 条）：

Task 1（assert_hops_within_limit + fetch_hop2_edges）：
1. assert_hops_within_limit(0/1/2) 不抛
2. assert_hops_within_limit(3) raise ValueError 含 "MAX_HOPS=2"
3. assert_hops_within_limit(-1) raise ValueError 含 "non-negative"
4. fetch_hop2_edges([], ["r1"]) → [] 零 SQL（fast path）
5. fetch_hop2_edges(["c1"], []) → [] 零 SQL（fast path）
6. fetch_hop2_edges(...): 5 sources × 10 邻居 → 50 edges + ChunkEdge.filter 调 1 次
7. fetch_hop2_edges(...): 100 邻居 → 截断到 TOP_NEIGHBORS_PER_HOP2=50 + log capped=True

Task 2（expand_hop2 三重去重 + NeighborMetadata 输出 + hop=2）：
8. hop2 target ∈ hop1 → 过滤
9. hop2 target ∈ rag_chunk_ids → 过滤
10. hop2 source == target（自环）→ 过滤
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.db import connection
from structlog.testing import capture_logs

from code_relations.constants import MAX_HOPS, TOP_NEIGHBORS_PER_HOP2
from code_relations.models import ChunkEdge, ChunkRegistry, EdgeType
from services.retrieval.hop2_expander import (
    assert_hops_within_limit,
    expand_hop2,
    fetch_hop2_edges,
)


def _default_reason(
    edge_type: str,
    source_file: str | None,
    target_file: str | None,
    metadata: dict,
) -> str:
    """work item 后 ReasonFn 新签名 ``(edge_type, source_file, target_file, metadata)``。"""
    descriptor = target_file if target_file else "<missing>"
    return f"{edge_type} from {descriptor}"


@contextmanager
def _capture_async_queries() -> Iterator[list[dict]]:
    """async-safe 等价于 ``CaptureQueriesContext``。

    ``CaptureQueriesContext.__enter__`` 调 ``ensure_connection()``，后者带
    ``@async_unsafe`` 装饰器在 async 测试体内直接抛 ``SynchronousOnlyOperation``；
    本 helper 通过 ``force_debug_cursor=True`` + ``queries_log`` 切片实现等价
    （连接已由 pytest-django ``transaction=True`` 提前建立）。
    """
    prev = connection.force_debug_cursor
    connection.force_debug_cursor = True
    initial = len(connection.queries_log)
    captured: list[dict] = []
    try:
        yield captured
    finally:
        captured.extend(list(connection.queries_log)[initial:])
        connection.force_debug_cursor = prev


# ---------------------------------------------------------------------------
# Task 1 case 1-3：assert_hops_within_limit
# ---------------------------------------------------------------------------


def test_assert_hops_within_limit_accepts_zero_one_two() -> None:
    """0 / 1 / 2 都在合法范围 [0, MAX_HOPS=2]，不抛异常。"""
    assert MAX_HOPS == 2  # plan 假设前提
    assert_hops_within_limit(0)
    assert_hops_within_limit(1)
    assert_hops_within_limit(2)


def test_assert_hops_within_limit_rejects_above_max() -> None:
    """hops=3 > MAX_HOPS=2 → ValueError 错误信息含两个具体值。"""
    with pytest.raises(ValueError) as exc_info:
        assert_hops_within_limit(3)
    msg = str(exc_info.value)
    assert "hops=3" in msg
    assert "MAX_HOPS=2" in msg


def test_assert_hops_within_limit_rejects_negative() -> None:
    """hops=-1 → ValueError 含 'non-negative'。"""
    with pytest.raises(ValueError) as exc_info:
        assert_hops_within_limit(-1)
    msg = str(exc_info.value)
    assert "non-negative" in msg
    assert "hops=-1" in msg


# ---------------------------------------------------------------------------
# Task 1 case 4-5：fast-path 零 SQL
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_fetch_hop2_edges_empty_hop1_returns_empty_zero_sql(
    repository,
) -> None:
    """hop1_chunk_ids=[] → 立即 [] 零 SQL（fast path 早返）。"""
    with _capture_async_queries() as captured:
        result = await fetch_hop2_edges([], [str(repository.id)])
    assert result == []
    assert len(captured) == 0, (
        f"empty hop1 path must not query DB; got {len(captured)} queries"
    )


@pytest.mark.django_db(transaction=True)
async def test_fetch_hop2_edges_empty_repo_ids_returns_empty_zero_sql(
    repository,
) -> None:
    """repo_ids=[] → 立即 [] 零 SQL。"""
    fake_chunk_id = str(uuid.uuid4())
    with _capture_async_queries() as captured:
        result = await fetch_hop2_edges([fake_chunk_id], [])
    assert result == []
    assert len(captured) == 0


# ---------------------------------------------------------------------------
# Task 1 case 6：正常路径 5 sources × 10 邻居 → 50 edges 按 weight desc + 1 ORM
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_fetch_hop2_edges_returns_sorted_within_single_query(
    repository,
) -> None:
    """5 hop1 sources × 10 outgoing edges → 50 edges 按 weight desc + ChunkEdge.filter
    仅被调用 1 次（无 N+1）。

    Note:
        ``CaptureQueriesContext`` 在 async 测试体内会触发 SynchronousOnlyOperation
        且 Django 5+ async ORM 走 sync_to_async 线程导致 ``queries_log`` 跨线程不可见；
        改走 patch spy on manager —— 单次 ``.filter(...)`` 调用即可证明无 N+1
        （与 hop1_reader test_resolve_metadata_calls_in_bulk_exactly_once 同模式）。
    """
    sources = [uuid.uuid4() for _ in range(5)]
    edges: list[ChunkEdge] = []
    for s_idx, src in enumerate(sources):
        for j in range(10):
            edges.append(
                ChunkEdge(
                    source_chunk_id=src,
                    target_chunk_id=uuid.uuid4(),
                    edge_type=EdgeType.CALL,
                    weight=0.5 + (s_idx * 10 + j) * 0.001,
                    repository=repository,
                )
            )
    await ChunkEdge.objects.abulk_create(edges)

    real_filter = ChunkEdge.objects.filter
    with patch.object(
        ChunkEdge.objects, "filter", side_effect=real_filter
    ) as spy:
        result = await fetch_hop2_edges(
            [str(s) for s in sources], [str(repository.id)]
        )

    assert spy.call_count == 1, (
        f"expected exactly 1 ChunkEdge.objects.filter call (no N+1), got {spy.call_count}"
    )
    assert len(result) == 50
    weights = [w for _src, _tgt, _et, w, _meta in result]
    assert weights == sorted(weights, reverse=True), "must be weight desc"

    for src_str, tgt_str, et, w, meta in result:
        assert isinstance(src_str, str)
        assert isinstance(tgt_str, str)
        assert isinstance(et, str)
        assert isinstance(w, float)
        assert isinstance(meta, dict)  # 5-tuple 含 metadata


# ---------------------------------------------------------------------------
# Task 1 case 7：100 邻居 → 截断到 50 + log capped=True
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_fetch_hop2_edges_caps_at_top_neighbors_per_hop2(
    repository,
) -> None:
    """单 source 100 邻居 → 输出截断到 TOP_NEIGHBORS_PER_HOP2=50 + capped=True log。"""
    src = uuid.uuid4()
    edges = [
        ChunkEdge(
            source_chunk_id=src,
            target_chunk_id=uuid.uuid4(),
            edge_type=EdgeType.CALL,
            weight=0.001 + j * 0.005,
            repository=repository,
        )
        for j in range(100)
    ]
    await ChunkEdge.objects.abulk_create(edges)

    with capture_logs() as events:
        result = await fetch_hop2_edges([str(src)], [str(repository.id)])

    assert len(result) == TOP_NEIGHBORS_PER_HOP2 == 50
    fetched_logs = [e for e in events if e.get("event") == "hop2_edges_fetched"]
    assert fetched_logs, f"expected hop2_edges_fetched event, got {events}"
    assert fetched_logs[-1]["capped"] is True
    assert fetched_logs[-1]["edge_count"] == 50


# ---------------------------------------------------------------------------
# Task 2 case 8：expand_hop2 三重去重 —— hop2 target ∈ hop1 → 过滤
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_expand_hop2_filters_targets_in_hop1(repository) -> None:
    """hop2 target 与 hop1_chunk_ids 重合 → 三重去重过滤；非重合 target 保留 + hop=2。"""
    hop1_a = uuid.uuid4()
    hop1_b = uuid.uuid4()
    target_distinct = uuid.uuid4()

    for cid, fp in (
        (hop1_a, "src/a.py"),
        (hop1_b, "src/b.py"),
        (target_distinct, "src/c.py"),
    ):
        await ChunkRegistry.objects.acreate(
            chunk_id=cid,
            content_hash=cid.hex,
            repository=repository,
            file_path=fp,
            chunk_index=0,
            line_start=1,
            line_end=5,
        )

    # hop1_a -> hop1_b（target ∈ hop1，应过滤）
    # hop1_a -> target_distinct（保留）
    await ChunkEdge.objects.abulk_create(
        [
            ChunkEdge(
                source_chunk_id=hop1_a,
                target_chunk_id=hop1_b,
                edge_type=EdgeType.CALL,
                weight=0.9,
                repository=repository,
            ),
            ChunkEdge(
                source_chunk_id=hop1_a,
                target_chunk_id=target_distinct,
                edge_type=EdgeType.CALL,
                weight=0.8,
                repository=repository,
            ),
        ]
    )

    out = await expand_hop2(
        hop1_chunk_ids={str(hop1_a), str(hop1_b)},
        rag_chunk_ids=set(),
        repo_ids=[str(repository.id)],
        reason_fn=_default_reason,
    )
    chunk_ids = {n.chunk_id for n in out}
    assert str(hop1_b) not in chunk_ids
    assert str(target_distinct) in chunk_ids
    assert all(n.hop == 2 for n in out)


# ---------------------------------------------------------------------------
# Task 2 case 9：expand_hop2 三重去重 —— hop2 target ∈ rag_chunk_ids → 过滤
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_expand_hop2_filters_targets_in_rag(repository) -> None:
    """hop2 target 与 rag_chunk_ids 重合 → 三重去重过滤。"""
    hop1_src = uuid.uuid4()
    rag_overlap_target = uuid.uuid4()
    fresh_target = uuid.uuid4()

    for cid, fp in (
        (hop1_src, "src/h.py"),
        (rag_overlap_target, "src/rag_overlap.py"),
        (fresh_target, "src/fresh.py"),
    ):
        await ChunkRegistry.objects.acreate(
            chunk_id=cid,
            content_hash=cid.hex,
            repository=repository,
            file_path=fp,
            chunk_index=0,
            line_start=1,
            line_end=5,
        )

    await ChunkEdge.objects.abulk_create(
        [
            ChunkEdge(
                source_chunk_id=hop1_src,
                target_chunk_id=rag_overlap_target,
                edge_type=EdgeType.IMPORT,
                weight=0.7,
                repository=repository,
            ),
            ChunkEdge(
                source_chunk_id=hop1_src,
                target_chunk_id=fresh_target,
                edge_type=EdgeType.CALL,
                weight=0.6,
                repository=repository,
            ),
        ]
    )

    out = await expand_hop2(
        hop1_chunk_ids={str(hop1_src)},
        rag_chunk_ids={str(rag_overlap_target)},
        repo_ids=[str(repository.id)],
        reason_fn=_default_reason,
    )
    chunk_ids = {n.chunk_id for n in out}
    assert str(rag_overlap_target) not in chunk_ids
    assert str(fresh_target) in chunk_ids


# ---------------------------------------------------------------------------
# Task 2 case 10：expand_hop2 自环边过滤 —— hop2 source == target → 过滤
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
async def test_expand_hop2_filters_self_loops(repository) -> None:
    """hop2 边的 source == target（自环）→ 过滤；同源到不同 target 保留。"""
    src_self = uuid.uuid4()
    fresh_target = uuid.uuid4()

    for cid, fp in (
        (src_self, "src/self.py"),
        (fresh_target, "src/fresh2.py"),
    ):
        await ChunkRegistry.objects.acreate(
            chunk_id=cid,
            content_hash=cid.hex,
            repository=repository,
            file_path=fp,
            chunk_index=0,
            line_start=1,
            line_end=5,
        )

    await ChunkEdge.objects.abulk_create(
        [
            ChunkEdge(
                source_chunk_id=src_self,
                target_chunk_id=src_self,
                edge_type=EdgeType.SAME_FILE,
                weight=0.5,
                repository=repository,
            ),
            ChunkEdge(
                source_chunk_id=src_self,
                target_chunk_id=fresh_target,
                edge_type=EdgeType.CALL,
                weight=0.4,
                repository=repository,
            ),
        ]
    )

    out = await expand_hop2(
        hop1_chunk_ids={str(src_self)},
        rag_chunk_ids=set(),
        repo_ids=[str(repository.id)],
        reason_fn=_default_reason,
    )
    chunk_ids = {n.chunk_id for n in out}
    # 自环 target == hop1 source，同时落 hop1 三重去重 + 自环单独过滤双重保险
    assert str(src_self) not in chunk_ids
    assert str(fresh_target) in chunk_ids

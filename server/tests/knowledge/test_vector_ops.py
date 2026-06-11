"""delivery_knowledge 写操作薄层回归测试（INGEST-06/08，T-13-02/T-13-03）。

锁定语义：
- payload 键集合 ⊇ ``KNOWLEDGE_PAYLOAD_INDEXED_FIELDS`` ∪
  ``KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS``（import 常量断言，禁止硬编码键名）；
- 任一写操作失败响亮：upsert 返回 False → raise、tombstone 异常重抛、
  删点失败吞但 structlog error（纯优化层）。
"""

from __future__ import annotations

import pytest
from qdrant_client import models
from qdrant_client.http.models import SparseVector
from structlog.testing import capture_logs

from knowledge.chunking import KnowledgeChunk, derive_point_ids
from knowledge.collection import (
    DELIVERY_KNOWLEDGE_COLLECTION,
    KNOWLEDGE_PAYLOAD_INDEXED_FIELDS,
    KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS,
)
from knowledge.exceptions import KnowledgeError
from knowledge.vector_ops import (
    build_knowledge_points,
    delete_points,
    tombstone_points,
    upsert_knowledge_points,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def built_points(entity_factory, version_factory):
    """构造一组真实 entity/version 派生的 points（含空 sparse 降级项）。"""
    entity = entity_factory()
    version = version_factory(entity)
    chunks = [
        KnowledgeChunk(index=0, text="标题\n\n首段", chunk_kind="summary"),
        KnowledgeChunk(index=1, text="## 正文", chunk_kind="section"),
    ]
    point_ids = derive_point_ids(version.id, len(chunks))
    dense = [[0.1] * 4, [0.2] * 4]
    sparse = [
        {"indices": [1, 2], "values": [0.5, 0.3]},
        {"indices": [], "values": []},  # 空 sparse → 该 point 降级 dense-only
    ]
    points = build_knowledge_points(
        entity=entity,
        version=version,
        chunks=chunks,
        dense_vectors=dense,
        sparse_vectors=sparse,
        point_ids=point_ids,
        embedding_model="BAAI/bge-m3",
    )
    return points, point_ids


# ---------------------------------------------------------------------------
# Test 1：payload 键集合锁定（T-13-02）
# ---------------------------------------------------------------------------


def test_payload_keys_superset_of_schema_constants(built_points) -> None:
    """每个 point payload 键集合 ⊇ 索引字段 ∪ 必带字段（单一事实源常量断言）。"""
    points, _ = built_points
    required = set(KNOWLEDGE_PAYLOAD_INDEXED_FIELDS) | set(KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS)
    for point in points:
        assert required <= set(point["payload"].keys())


def test_payload_none_org_fields_written_as_empty_string(built_points) -> None:
    """project_id / repository_id 为 None 时写空串（KEYWORD 索引类型稳定契约）。"""
    points, _ = built_points
    for point in points:
        assert point["payload"]["project_id"] == ""
        assert point["payload"]["repository_id"] == ""
        assert point["payload"]["file_path"] == ""
        assert point["payload"]["is_latest"] is True


# ---------------------------------------------------------------------------
# Test 2：hybrid 格式
# ---------------------------------------------------------------------------


def test_hybrid_vector_format_and_dense_only_fallback(built_points) -> None:
    """sparse 非空 → {"dense": ..., "sparse": SparseVector}；sparse 空 → 纯 dense。"""
    points, point_ids = built_points
    assert [p["id"] for p in points] == point_ids

    hybrid_vector = points[0]["vector"]
    assert isinstance(hybrid_vector, dict)
    assert hybrid_vector["dense"] == [0.1] * 4
    assert isinstance(hybrid_vector["sparse"], SparseVector)
    assert hybrid_vector["sparse"].indices == [1, 2]

    dense_only = points[1]["vector"]
    assert dense_only == [0.2] * 4


# ---------------------------------------------------------------------------
# Test 3：失败响亮（T-13-03）
# ---------------------------------------------------------------------------


async def test_upsert_returns_false_raises(monkeypatch, built_points) -> None:
    """upsert_vectors_by_name 返回 False → upsert_knowledge_points raise（绝不静默）。"""
    from services.qdrant_service import QdrantService

    monkeypatch.setattr(
        QdrantService, "upsert_vectors_by_name", classmethod(lambda cls, name, pts: False)
    )
    points, _ = built_points
    with pytest.raises(KnowledgeError):
        await upsert_knowledge_points(points)


async def test_upsert_success_no_raise(monkeypatch, built_points) -> None:
    """upsert 成功（True）不抛；目标 collection 为 DELIVERY_KNOWLEDGE_COLLECTION。"""
    from services.qdrant_service import QdrantService

    calls: list[tuple[str, int]] = []

    def _fake(cls, name, pts):
        calls.append((name, len(pts)))
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake))
    points, _ = built_points
    await upsert_knowledge_points(points)
    assert calls == [(DELIVERY_KNOWLEDGE_COLLECTION, len(points))]


async def test_upsert_batches_at_100(monkeypatch, built_points) -> None:
    """超过 100 个 point 分批 upsert（indexer 同款编排）。"""
    from services.qdrant_service import QdrantService

    batch_sizes: list[int] = []

    def _fake(cls, name, pts):
        batch_sizes.append(len(pts))
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake))
    points, _ = built_points
    many = [dict(points[0], id=f"id-{i}") for i in range(150)]
    await upsert_knowledge_points(many)
    assert batch_sizes == [100, 50]


async def test_tombstone_failure_reraises_with_error_log(mock_qdrant_client) -> None:
    """set_payload 抛异常 → tombstone_points 重抛 + structlog error。"""
    mock_qdrant_client.set_payload.side_effect = RuntimeError("qdrant down")
    with capture_logs() as cap:
        with pytest.raises(RuntimeError):
            await tombstone_points(["pid-1"])
    events = [e["event"] for e in cap if e.get("log_level") == "error"]
    assert "knowledge_vector_tombstone_failed" in events


async def test_delete_failure_swallowed_but_logged(mock_qdrant_client) -> None:
    """delete 抛异常 → delete_points 不 raise（纯优化层）但 structlog error。"""
    mock_qdrant_client.delete.side_effect = RuntimeError("qdrant down")
    with capture_logs() as cap:
        await delete_points(["pid-1"])  # 不应 raise
    events = [e["event"] for e in cap if e.get("log_level") == "error"]
    assert "knowledge_vector_delete_failed" in events


# ---------------------------------------------------------------------------
# Test 4：调用形态
# ---------------------------------------------------------------------------


async def test_tombstone_call_shape(mock_qdrant_client) -> None:
    """tombstone 以 wait=True + payload={"is_latest": False} + points=旧 id 列表调用。"""
    await tombstone_points(["pid-1", "pid-2"])
    mock_qdrant_client.set_payload.assert_called_once_with(
        collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
        payload={"is_latest": False},
        points=["pid-1", "pid-2"],
        wait=True,
    )


async def test_delete_call_shape_uses_point_ids_list(mock_qdrant_client) -> None:
    """delete 以 PointIdsList（按 id，绝不按 filter，P1）+ wait=True 调用。"""
    await delete_points(["pid-1", "pid-2"])
    mock_qdrant_client.delete.assert_called_once()
    kwargs = mock_qdrant_client.delete.call_args.kwargs
    assert kwargs["collection_name"] == DELIVERY_KNOWLEDGE_COLLECTION
    assert kwargs["wait"] is True
    selector = kwargs["points_selector"]
    assert isinstance(selector, models.PointIdsList)
    assert selector.points == ["pid-1", "pid-2"]


async def test_empty_point_ids_noop(mock_qdrant_client) -> None:
    """空列表直接 return，不触碰 client。"""
    await tombstone_points([])
    await delete_points([])
    mock_qdrant_client.set_payload.assert_not_called()
    mock_qdrant_client.delete.assert_not_called()

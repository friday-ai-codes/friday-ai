"""Phase 136：Process canonical 文档、generation 与双 lane 投影。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.code_graph.process_index import (
    build_process_document,
    process_generation,
    rebuild_process_index,
    search_process_index,
)


def _trace() -> dict:
    return {
        "process_key": "POST:/api/orders",
        "name": "创建订单流程",
        "entry_endpoint": {
            "http_method": "POST",
            "url_path": "/api/orders",
            "handler_name": "create_order",
            "file_path": "orders/api.py",
            "line_number": 12,
        },
        "steps": [
            {
                "symbol_id": "s1",
                "name": "create_order",
                "file_path": "orders/api.py",
                "line": 12,
            },
            {
                "symbol_id": "s2",
                "name": "reserve_inventory",
                "file_path": "inventory/service.py",
                "start_line": 30,
                "end_line": 44,
            },
        ],
        "built_at_sha": "abc123",
    }


def test_build_process_document_preserves_canonical_evidence() -> None:
    doc = build_process_document(_trace())
    assert doc["name"] == "创建订单流程"
    assert doc["entry"]["url_path"] == "/api/orders"
    assert doc["terminal"]["symbol_id"] == "s2"
    assert doc["steps"][0]["start_line"] == 12
    assert doc["steps"][0]["end_line"] == 12
    assert doc["steps"][1]["start_line"] == 30
    assert doc["steps"][1]["end_line"] == 44
    assert doc["modules"] == ["inventory", "orders"]
    assert "创建订单流程" in doc["content"]


def test_generation_is_stable_and_watermark_sensitive() -> None:
    first = process_generation("repo", "main", "sha-1")
    assert first == process_generation("repo", "main", "sha-1")
    assert first != process_generation("repo", "main", "sha-2")
    assert first != process_generation("repo", "feature", "sha-1")


@pytest.mark.asyncio
async def test_rebuild_writes_dense_sparse_with_strict_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.code_graph.process_index._load_traces",
        lambda _repo, _branch: [_trace()],
    )

    async def fake_embeddings(_texts):
        return [[0.1, 0.2, 0.3]]

    monkeypatch.setattr(
        "services.code_graph.process_index.EmbeddingService.generate_embeddings_batch",
        fake_embeddings,
    )
    monkeypatch.setattr(
        "services.sparse_encoder.SparseEncoderService.encode_batch",
        lambda _texts: [{"indices": [1], "values": [1.0]}],
    )
    captured: dict = {}

    def fake_create(_name, **kwargs):
        captured["create"] = kwargs
        return True

    def fake_upsert(_name, points):
        captured["points"] = points
        return True

    monkeypatch.setattr(
        "services.qdrant_service.QdrantService.create_collection_by_name",
        fake_create,
    )
    monkeypatch.setattr(
        "services.qdrant_service.QdrantService.upsert_vectors_by_name",
        fake_upsert,
    )

    result = await rebuild_process_index(
        "repo-id",
        "main",
        initiated_by_user_id="42",
    )

    assert result["indexed"] == 1
    point = captured["points"][0]
    assert set(point["vector"]) == {"dense", "sparse"}
    assert point["payload"]["repository_id"] == "repo-id"
    assert point["payload"]["branch_name"] == "main"
    assert point["payload"]["commit_sha"] == "abc123"
    assert point["payload"]["generation"] == result["generation"]
    assert captured["create"]["hybrid"] is True


@pytest.mark.asyncio
async def test_search_filters_generation_and_marks_hybrid_lane(monkeypatch) -> None:
    async def fake_embed(_query):
        return SimpleNamespace(primary=[0.1, 0.2])

    monkeypatch.setattr(
        "services.query_embedding.embed_query",
        fake_embed,
    )
    monkeypatch.setattr(
        "services.sparse_encoder.SparseEncoderService.encode",
        lambda _query: {"indices": [1], "values": [1.0]},
    )
    captured: dict = {}

    def fake_search(_name, _dense, _sparse, **kwargs):
        captured.update(kwargs)
        return [{"score": 0.9, "payload": build_process_document(_trace())}]

    monkeypatch.setattr(
        "services.qdrant_service.QdrantService.hybrid_search_by_name",
        fake_search,
    )

    rows = await search_process_index(
        "库存预占",
        repository_id="repo-id",
        branch_name="main",
        commit_sha="abc123",
    )

    assert rows[0]["lane"] == "hybrid"
    assert rows[0]["name"] == "创建订单流程"
    assert captured["filters"] == {
        "repository_id": "repo-id",
        "branch_name": "main",
        "generation": process_generation("repo-id", "main", "abc123"),
        "commit_sha": "abc123",
    }

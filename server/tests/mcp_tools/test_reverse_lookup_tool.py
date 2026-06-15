"""`reverse_lookup_requirements` MCP 工具守护测试（Phase 34 RREF-01，Task 3）。

覆盖（对齐 plan done / threat_model）：
- 带 AccessToken POST (repo,file,line) → 200 结构化 {chunks, related_work_items,
  related_documents, paths, run_id}，并记录 EDGE trace。
- 缺 token / 未认证 → authentication_failed 401（T-34A-04）。
- 缺 (file_path+line) 且缺 chunk_id → invalid_params 400。
- 被排除文件 → 200 且 related 为空（不泄漏，T-34A-01）。
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from interactions.models import RetrievalTrace

pytestmark = pytest.mark.django_db

URL = "/api/mcp/tools/reverse_lookup_requirements/"


def _make_chunk(repository, *, chunk_id, file_path, line_start=10, line_end=30, chunk_index=0):
    from code_relations.models import ChunkRegistry

    return ChunkRegistry.objects.create(
        chunk_id=chunk_id,
        content_hash="a" * 64,
        repository=repository,
        file_path=file_path,
        chunk_index=chunk_index,
        branch_name="",
        line_start=line_start,
        line_end=line_end,
    )


def _make_entity(kind, *, title="t"):
    from knowledge.models import EntityOrigin, KnowledgeEntity, generate_entity_id

    source_kind = f"sk_{kind}"
    source_id = uuid.uuid4().hex
    return KnowledgeEntity.objects.create(
        id=generate_entity_id(kind, source_kind, source_id),
        kind=kind,
        origin=EntityOrigin.FEISHU,
        source_kind=source_kind,
        source_id=source_id,
        title=title,
        event_time=timezone.now(),
    )


def _make_edge(source_entity, *, target_entity=None, target_chunk_id=None, relation):
    from knowledge.models import KnowledgeEdge

    return KnowledgeEdge.objects.create(
        source_entity=source_entity,
        target_entity=target_entity,
        target_chunk_id=target_chunk_id,
        relation=relation,
        valid_at=timezone.now(),
    )


def _build_chain(repository, *, file_path="src/a.py"):
    from knowledge.models import EdgeRelation, EntityKind

    chunk_id = uuid.uuid4()
    _make_chunk(repository, chunk_id=chunk_id, file_path=file_path)
    cc = _make_entity(EntityKind.CODE_CHANGE)
    tp = _make_entity(EntityKind.TECH_PLAN)
    wi = _make_entity(EntityKind.WORK_ITEM, title="需求A")
    doc = _make_entity(EntityKind.DOCUMENT, title="文档X")
    _make_edge(cc, target_chunk_id=chunk_id, relation=EdgeRelation.MODIFIES_CHUNK)
    _make_edge(tp, target_entity=cc, relation=EdgeRelation.IMPLEMENTED_BY)
    _make_edge(wi, target_entity=tp, relation=EdgeRelation.HAS_PLAN)
    _make_edge(wi, target_entity=doc, relation=EdgeRelation.REFERENCES)
    return chunk_id, wi, doc


def test_reverse_lookup_tool_returns_structured(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    _chunk_id, wi, doc = _build_chain(indexed_repository)

    response = client.post(
        URL,
        {"repository_id": str(indexed_repository.id), "file_path": "src/a.py", "line": 15},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert {"chunks", "related_work_items", "related_documents", "paths", "run_id"} <= set(body)
    assert str(wi.id) in {w["entity_id"] for w in body["related_work_items"]}
    assert str(doc.id) in {d["entity_id"] for d in body["related_documents"]}
    assert body["paths"]
    assert RetrievalTrace.objects.filter(kind=RetrievalTrace.Kind.EDGE).exists()


def test_reverse_lookup_tool_unauthenticated(indexed_repository) -> None:
    client = APIClient()
    response = client.post(
        URL,
        {"repository_id": str(indexed_repository.id), "file_path": "src/a.py", "line": 15},
        format="json",
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "authentication_failed"


def test_reverse_lookup_tool_missing_source_400(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    response = client.post(
        URL,
        {"repository_id": str(indexed_repository.id)},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_params"


def test_reverse_lookup_tool_excluded_file_no_leak(
    mcp_client: tuple[APIClient, str],
    indexed_repository,
) -> None:
    client, _plaintext = mcp_client
    _build_chain(indexed_repository, file_path=".env")
    response = client.post(
        URL,
        {"repository_id": str(indexed_repository.id), "file_path": ".env", "line": 15},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["chunks"] == []
    assert body["related_work_items"] == []
    assert body["related_documents"] == []
    assert body["paths"] == []

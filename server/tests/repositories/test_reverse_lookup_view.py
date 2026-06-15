"""`GET /api/repositories/<id>/reverse-lookup/` 守护测试（Phase 34 RREF-01，Task 2）。

覆盖（对齐 plan done / threat_model）：
- (repo,file,line) 反查到 work_item/document → 200 结构化。
- 未认证 → 401/403（T-34A-04）。
- 缺 path 且缺 chunk_id → 400。
- 提供 path 但 line 非正整数 → 400。
- 被排除文件 → 200 且 chunks/related 为空（不泄漏，T-34A-01）。
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/repositories/{repo_id}/reverse-lookup/"


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


class TestReverseLookupView:
    def test_hit_returns_structured(self, authenticated_client, repository: Repository) -> None:
        _chunk_id, wi, doc = _build_chain(repository)
        resp = authenticated_client.get(
            URL.format(repo_id=repository.id), {"path": "src/a.py", "line": 15}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert {k for k in data} == {"chunks", "related_work_items", "related_documents", "paths"}
        assert str(wi.id) in {w["entity_id"] for w in data["related_work_items"]}
        assert str(doc.id) in {d["entity_id"] for d in data["related_documents"]}
        assert data["paths"]

    def test_unauthenticated_blocked(self, api_client, repository: Repository) -> None:
        resp = api_client.get(URL.format(repo_id=repository.id), {"path": "src/a.py", "line": 5})
        assert resp.status_code in (401, 403)

    def test_missing_path_and_chunk_id_400(
        self, authenticated_client, repository: Repository
    ) -> None:
        resp = authenticated_client.get(URL.format(repo_id=repository.id))
        assert resp.status_code == 400

    def test_non_positive_line_400(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.get(
            URL.format(repo_id=repository.id), {"path": "src/a.py", "line": 0}
        )
        assert resp.status_code == 400

    def test_non_integer_line_400(self, authenticated_client, repository: Repository) -> None:
        resp = authenticated_client.get(
            URL.format(repo_id=repository.id), {"path": "src/a.py", "line": "abc"}
        )
        assert resp.status_code == 400

    def test_malformed_chunk_id_400(self, authenticated_client, repository: Repository) -> None:
        # 畸形 chunk_id（非 UUID）应在 view 层 fail 到 400，而非穿透到 ORM 触 500（WR-01）
        resp = authenticated_client.get(
            URL.format(repo_id=repository.id), {"chunk_id": "not-a-uuid"}
        )
        assert resp.status_code == 400

    def test_excluded_file_no_existence_leak(
        self, authenticated_client, repository: Repository
    ) -> None:
        _build_chain(repository, file_path=".env")
        resp = authenticated_client.get(
            URL.format(repo_id=repository.id), {"path": ".env", "line": 15}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["chunks"] == []
        assert data["related_work_items"] == []
        assert data["related_documents"] == []
        assert data["paths"] == []

    def test_missing_repo_404(self, authenticated_client) -> None:
        resp = authenticated_client.get(
            URL.format(repo_id="00000000-0000-0000-0000-000000000001"),
            {"path": "src/a.py", "line": 5},
        )
        assert resp.status_code == 404

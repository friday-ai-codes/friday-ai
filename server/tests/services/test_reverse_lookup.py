"""`reverse_lookup` 片段→需求反查守护测试（Phase 34 RREF-01，per 34-01 plan Task 1）。

覆盖（对齐 plan behavior / threat_model）：
- (repo,file,line) 命中 chunk + 完整图谱链 → related_work_items/related_documents/paths（guard ①）。
- 多 chunk / 多 code_change 命中时 related 去重（同一 work_item 不重复）。
- MODIFIES_CHUNK 边被失效（invalid_at）后默认当前视图不再召回（guard ③，衔接 Phase 33 as-of）。
- 被排除文件（find_chunk_at fail-closed）→ 空 chunks/related，不泄漏（guard ②）。
- chunk_id 直接入参先经 ChunkRegistry 复判 file_path 排除，被排除返回空（不绕过安全边界）。
- 只有 chunk 命中但无上游图谱边（部分图谱）→ chunks 非空、related_* 为空，不抛。
- 反查纯读：service 源码不含任何写接口调用。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from services.reverse_lookup import reverse_lookup

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


def _make_chunk(
    repository,
    *,
    chunk_id: uuid.UUID,
    file_path: str = "src/a.py",
    line_start: int | None = 10,
    line_end: int | None = 30,
    chunk_index: int = 0,
    branch_name: str = "",
):
    from code_relations.models import ChunkRegistry

    return ChunkRegistry.objects.create(
        chunk_id=chunk_id,
        content_hash="a" * 64,
        repository=repository,
        file_path=file_path,
        chunk_index=chunk_index,
        branch_name=branch_name,
        line_start=line_start,
        line_end=line_end,
    )


def _make_entity(kind: str, *, title: str = "测试实体", space=None):
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
        space=space,
        event_time=timezone.now(),
    )


def _make_edge(source_entity, *, target_entity=None, target_chunk_id=None, relation, invalid_at=None):
    from knowledge.models import KnowledgeEdge

    valid_at = timezone.now()
    edge = KnowledgeEdge.objects.create(
        source_entity=source_entity,
        target_entity=target_entity,
        target_chunk_id=target_chunk_id,
        relation=relation,
        valid_at=valid_at,
    )
    if invalid_at is not None:
        KnowledgeEdge.objects.filter(id=edge.id).update(invalid_at=invalid_at)
    return edge


def _build_full_chain(repository, *, file_path="src/a.py", invalidate_modifies=False):
    """构建完整反查链：chunk ←MODIFIES_CHUNK code_change ←IMPLEMENTED_BY tech_plan
    ←HAS_PLAN work_item →REFERENCES document。返回各实体与 chunk_id。"""
    from knowledge.models import EdgeRelation, EntityKind

    chunk_id = uuid.uuid4()
    _make_chunk(repository, chunk_id=chunk_id, file_path=file_path)
    code_change = _make_entity(EntityKind.CODE_CHANGE, title="变更")
    tech_plan = _make_entity(EntityKind.TECH_PLAN, title="方案")
    work_item = _make_entity(EntityKind.WORK_ITEM, title="需求A")
    document = _make_entity(EntityKind.DOCUMENT, title="文档X")

    _make_edge(
        code_change,
        target_chunk_id=chunk_id,
        relation=EdgeRelation.MODIFIES_CHUNK,
        invalid_at=(timezone.now() + timedelta(seconds=1)) if invalidate_modifies else None,
    )
    _make_edge(tech_plan, target_entity=code_change, relation=EdgeRelation.IMPLEMENTED_BY)
    _make_edge(work_item, target_entity=tech_plan, relation=EdgeRelation.HAS_PLAN)
    _make_edge(work_item, target_entity=document, relation=EdgeRelation.REFERENCES)
    return {
        "chunk_id": chunk_id,
        "code_change": code_change,
        "tech_plan": tech_plan,
        "work_item": work_item,
        "document": document,
    }


async def test_reverse_lookup_full_chain(repository) -> None:
    data = await sync_to_async(_build_full_chain)(repository)
    result = await reverse_lookup(str(repository.id), file_path="src/a.py", line=15)

    assert [c["chunk_id"] for c in result["chunks"]] == [str(data["chunk_id"])]
    wi_ids = {w["entity_id"] for w in result["related_work_items"]}
    doc_ids = {d["entity_id"] for d in result["related_documents"]}
    assert str(data["work_item"].id) in wi_ids
    assert str(data["document"].id) in doc_ids
    # work_item 序列化字段含 project_id；document 不含
    assert "project_id" in result["related_work_items"][0]
    assert "project_id" not in result["related_documents"][0]
    # paths 含完整跳链
    assert result["paths"]
    path = result["paths"][0]
    assert path["chunk_id"] == str(data["chunk_id"])
    assert path["code_change_id"] == str(data["code_change"].id)
    assert path["tech_plan_id"] == str(data["tech_plan"].id)
    assert path["work_item_id"] == str(data["work_item"].id)
    assert path["document_id"] == str(data["document"].id)


async def test_reverse_lookup_dedups_work_items(repository) -> None:
    """两个 chunk 覆盖同一行、各自链到同一 work_item → related_work_items 去重。"""
    from knowledge.models import EdgeRelation, EntityKind

    def _setup():
        chunk1 = uuid.uuid4()
        chunk2 = uuid.uuid4()
        _make_chunk(repository, chunk_id=chunk1, file_path="src/a.py", chunk_index=0, line_start=1, line_end=50)
        _make_chunk(repository, chunk_id=chunk2, file_path="src/a.py", chunk_index=1, line_start=10, line_end=20)
        cc1 = _make_entity(EntityKind.CODE_CHANGE, title="变更1")
        cc2 = _make_entity(EntityKind.CODE_CHANGE, title="变更2")
        tech_plan = _make_entity(EntityKind.TECH_PLAN, title="方案")
        work_item = _make_entity(EntityKind.WORK_ITEM, title="需求A")
        _make_edge(cc1, target_chunk_id=chunk1, relation=EdgeRelation.MODIFIES_CHUNK)
        _make_edge(cc2, target_chunk_id=chunk2, relation=EdgeRelation.MODIFIES_CHUNK)
        _make_edge(tech_plan, target_entity=cc1, relation=EdgeRelation.IMPLEMENTED_BY)
        _make_edge(tech_plan, target_entity=cc2, relation=EdgeRelation.IMPLEMENTED_BY)
        _make_edge(work_item, target_entity=tech_plan, relation=EdgeRelation.HAS_PLAN)
        return work_item

    work_item = await sync_to_async(_setup)()
    result = await reverse_lookup(str(repository.id), file_path="src/a.py", line=15)
    wi_ids = [w["entity_id"] for w in result["related_work_items"]]
    assert wi_ids.count(str(work_item.id)) == 1


async def test_reverse_lookup_excludes_invalidated_modifies_edge(repository) -> None:
    """失效（invalid_at）MODIFIES_CHUNK 边默认当前视图不召回其 work_item。"""
    await sync_to_async(_build_full_chain)(repository, invalidate_modifies=True)
    result = await reverse_lookup(str(repository.id), file_path="src/a.py", line=15)
    assert result["chunks"]  # chunk 仍命中
    assert result["related_work_items"] == []
    assert result["related_documents"] == []
    assert result["paths"] == []


async def test_reverse_lookup_excluded_file_failclosed(repository) -> None:
    """被排除文件（.env）→ find_chunk_at fail-closed → 空结构，不泄漏。"""
    await sync_to_async(_build_full_chain)(repository, file_path=".env")
    result = await reverse_lookup(str(repository.id), file_path=".env", line=15)
    assert result["chunks"] == []
    assert result["related_work_items"] == []
    assert result["related_documents"] == []
    assert result["paths"] == []


async def test_reverse_lookup_chunk_id_direct_failclosed(repository) -> None:
    """chunk_id 直接入参：经 ChunkRegistry 复判 file_path 命中排除 → 空（不绕过边界）。"""
    from knowledge.models import EdgeRelation, EntityKind

    def _setup():
        chunk_id = uuid.uuid4()
        _make_chunk(repository, chunk_id=chunk_id, file_path=".env", line_start=1, line_end=5)
        cc = _make_entity(EntityKind.CODE_CHANGE)
        wi = _make_entity(EntityKind.WORK_ITEM)
        tp = _make_entity(EntityKind.TECH_PLAN)
        _make_edge(cc, target_chunk_id=chunk_id, relation=EdgeRelation.MODIFIES_CHUNK)
        _make_edge(tp, target_entity=cc, relation=EdgeRelation.IMPLEMENTED_BY)
        _make_edge(wi, target_entity=tp, relation=EdgeRelation.HAS_PLAN)
        return chunk_id

    chunk_id = await sync_to_async(_setup)()
    result = await reverse_lookup(str(repository.id), chunk_id=str(chunk_id))
    assert result["chunks"] == []
    assert result["related_work_items"] == []
    assert result["paths"] == []


async def test_reverse_lookup_chunk_id_direct_success(repository) -> None:
    """chunk_id 直接入参（未排除文件）→ 正常反查到 work_item。"""
    from knowledge.models import EdgeRelation, EntityKind

    def _setup():
        chunk_id = uuid.uuid4()
        _make_chunk(repository, chunk_id=chunk_id, file_path="src/a.py", line_start=10, line_end=30)
        cc = _make_entity(EntityKind.CODE_CHANGE)
        tp = _make_entity(EntityKind.TECH_PLAN)
        wi = _make_entity(EntityKind.WORK_ITEM)
        _make_edge(cc, target_chunk_id=chunk_id, relation=EdgeRelation.MODIFIES_CHUNK)
        _make_edge(tp, target_entity=cc, relation=EdgeRelation.IMPLEMENTED_BY)
        _make_edge(wi, target_entity=tp, relation=EdgeRelation.HAS_PLAN)
        return chunk_id, wi

    chunk_id, wi = await sync_to_async(_setup)()
    result = await reverse_lookup(str(repository.id), chunk_id=str(chunk_id))
    assert [c["chunk_id"] for c in result["chunks"]] == [str(chunk_id)]
    assert str(wi.id) in {w["entity_id"] for w in result["related_work_items"]}


async def test_reverse_lookup_partial_graph_no_upstream(repository) -> None:
    """只有 chunk、无上游图谱边 → chunks 非空、related_* 空，不抛。"""

    def _setup():
        chunk_id = uuid.uuid4()
        _make_chunk(repository, chunk_id=chunk_id, file_path="src/a.py", line_start=10, line_end=30)
        return chunk_id

    chunk_id = await sync_to_async(_setup)()
    result = await reverse_lookup(str(repository.id), file_path="src/a.py", line=15)
    assert [c["chunk_id"] for c in result["chunks"]] == [str(chunk_id)]
    assert result["related_work_items"] == []
    assert result["related_documents"] == []
    assert result["paths"] == []


async def test_reverse_lookup_no_params_returns_empty(repository) -> None:
    """两种入参都缺 → 空结构。"""
    result = await reverse_lookup(str(repository.id))
    assert result == {
        "chunks": [],
        "related_work_items": [],
        "related_documents": [],
        "paths": [],
    }


async def test_reverse_lookup_service_is_read_only() -> None:
    """纯读纪律：service 源码不含任何写接口调用（add_edge/invalidate/save/upsert）。"""
    import re
    from pathlib import Path

    import services.reverse_lookup as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"add_edge|invalidate_edge|\.asave\(|\.save\(|upsert|acreate|\.create\(", code)

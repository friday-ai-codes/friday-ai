"""project_doc RAG 摄取 source 守护测试（CTX-01/02，85-01）。

镜像 ``test_artifact_source``：5 文件正文（``last_synced_snapshot``）→ KnowledgeEntity(
document, source_kind=project_doc) + 文件→REFERENCES→项目图谱节点边 + 正文脱敏；文件不存在
返回空（不抛）。normalize 层断言（不跑 embedding），``--disable-socket`` 第二道保险。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import DocType, ProjectDoc
from initiatives.services.knowledge_graph import project_node_id
from knowledge.ingestion import IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin
from knowledge.sources import get_normalizer
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_doc(snapshot: str, doc_type: str = DocType.RESEARCH) -> ProjectDoc:
    from initiatives.models import Project

    space = Space.objects.create(name="S")
    project = Project.objects.create(space=space, name="P", feishu_project_key="ctx-k")
    return ProjectDoc.objects.create(
        project=project, doc_type=doc_type, last_synced_snapshot=snapshot
    )


async def test_project_doc_normalize_produces_document_event_with_edge() -> None:
    secret = "sk-ant-abcdefghij1234567890"
    doc = await _make_doc(f"# 调研\ntoken={secret}\n正文内容")
    normalize = get_normalizer("project_doc")

    events = await normalize(IngestionRequest("project_doc", str(doc.id), "test"))

    assert len(events) == 1
    event = events[0]
    assert event.kind == EntityKind.DOCUMENT
    assert event.origin == EntityOrigin.PROJECT
    assert event.source_kind == "project_doc"
    # KnowledgeEntity.space_id remains the owning Space FK; vector payload carries Project id.
    project = await sync_to_async(lambda: doc.project)()
    assert event.space_id == str(project.space_id)
    assert event.payload["project_id"] == str(project.id)
    assert event.repository_id is None
    # 脱敏不可绕过：正文不含明文 secret。
    assert secret not in event.content
    assert "正文内容" in event.content
    # 一条 REFERENCES 边指向项目图谱节点。
    assert len(event.edges) == 1
    edge = event.edges[0]
    assert edge.relation == EdgeRelation.REFERENCES
    assert edge.target_entity_id == project_node_id(project.id)


async def test_project_doc_normalize_missing_returns_empty() -> None:
    normalize = get_normalizer("project_doc")
    import uuid

    events = await normalize(IngestionRequest("project_doc", str(uuid.uuid4()), "test"))
    assert events == []


async def test_project_doc_normalize_empty_snapshot_still_produces_entity() -> None:
    """正文为空 fail-soft：仍产实体（缺段不缺实体）。"""
    doc = await _make_doc("")
    normalize = get_normalizer("project_doc")
    events = await normalize(IngestionRequest("project_doc", str(doc.id), "test"))
    assert len(events) == 1
    assert events[0].content == ""

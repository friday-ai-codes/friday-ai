"""project_memory RAG 摄取 source 守护测试（CTX-01/02，85-01）。

镜像 ``test_project_doc_source``：active 记忆正文 → KnowledgeEntity(document,
source_kind=project_memory) + 记忆→REFERENCES→项目图谱节点边 + 正文脱敏；记忆不存在或非
active 返回空（不抛、不摄取已废弃记忆）。normalize 层断言，``--disable-socket`` 第二道保险。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import ProjectMemory, ProjectMemoryStatus
from initiatives.services.knowledge_graph import project_node_id
from knowledge.ingestion import IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin
from knowledge.sources import get_normalizer
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


@sync_to_async
def _make_memory(
    content: str, status: str = ProjectMemoryStatus.ACTIVE
) -> ProjectMemory:
    from initiatives.models import Project

    space = Space.objects.create(name="S")
    project = Project.objects.create(space=space, name="P", feishu_project_key="ctx-m")
    return ProjectMemory.objects.create(
        project=project, content=content, status=status
    )


async def test_project_memory_normalize_produces_document_event_with_edge() -> None:
    secret = "sk-ant-abcdefghij1234567890"
    memory = await _make_memory(f"决策：token={secret}，用 PG 连接池")
    normalize = get_normalizer("project_memory")

    events = await normalize(IngestionRequest("project_memory", str(memory.id), "test"))

    assert len(events) == 1
    event = events[0]
    assert event.kind == EntityKind.DOCUMENT
    assert event.origin == EntityOrigin.PROJECT
    assert event.source_kind == "project_memory"
    project = await sync_to_async(lambda: memory.project)()
    assert event.space_id == str(project.space_id)
    assert event.payload["project_id"] == str(project.id)
    assert event.repository_id is None
    # 脱敏不可绕过。
    assert secret not in event.content
    assert "用 PG 连接池" in event.content
    assert len(event.edges) == 1
    edge = event.edges[0]
    assert edge.relation == EdgeRelation.REFERENCES
    assert edge.target_entity_id == project_node_id(project.id)


async def test_project_memory_normalize_missing_returns_empty() -> None:
    normalize = get_normalizer("project_memory")
    events = await normalize(
        IngestionRequest("project_memory", str(uuid.uuid4()), "test")
    )
    assert events == []


async def test_project_memory_normalize_superseded_returns_empty() -> None:
    """非 active 记忆不摄取（返回空，不抛）。"""
    memory = await _make_memory("废弃内容", status=ProjectMemoryStatus.SUPERSEDED)
    normalize = get_normalizer("project_memory")
    events = await normalize(IngestionRequest("project_memory", str(memory.id), "test"))
    assert events == []

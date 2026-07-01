"""工件 RAG 摄取 source 守护测试（ARTIFACT-04）。

- 文字载体（markdown）全文摄取 → KnowledgeEntity(document, source_kind=artifact)
  + 工件→REFERENCES→项目图谱节点边 + 正文脱敏。
- 飞书 doc 拉取失败 fail-soft：实体照常产出，正文空串（缺段不缺实体）。
- UI 稿图形外链（external_link / ragable=False）→ normalize 返回空（仅元数据，不强行 RAG）。

驱动方式镜像 test_ingestion：直接 ``await ingest(request)``（normalize → ingest_events），
Qdrant / embedding 全 mock（``mock_ensure`` / ``mock_embedding`` / ``mock_upsert``）；
``--disable-socket`` 第二道保险。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from initiatives.models import Artifact, ArtifactType, Project
from initiatives.services import ArtifactService
from initiatives.services.knowledge_graph import project_node_id
from knowledge.ingestion import IngestionRequest, ingest
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    KnowledgeEdge,
    KnowledgeEntity,
    KnowledgeEntityVersion,
    generate_entity_id,
)
from knowledge.sources import get_normalizer
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def mock_ensure(monkeypatch) -> AsyncMock:
    ensure = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", ensure)
    return ensure


@pytest.fixture
def mock_upsert(monkeypatch) -> list:
    from services.qdrant_service import QdrantService

    calls: list = []
    monkeypatch.setattr(
        QdrantService,
        "upsert_vectors_by_name",
        classmethod(lambda cls, name, pts: calls.append(pts) or True),
    )
    return calls


@sync_to_async
def _setup(carrier, ragable, key="src", url="", content_ref=""):
    space = Space.objects.create(name="S", feishu_project_key=f"src-{key}")
    project = Project.objects.create(space=space, name="P", feishu_project_key="")
    artifact_type = ArtifactType.objects.create(
        key=key, name=key, carrier=carrier, ragable=ragable
    )
    return space, project, artifact_type


async def _create_artifact(project, t, **kw) -> Artifact:
    with patch(
        "initiatives.services.artifact_service.ArtifactService._maybe_schedule_ingestion",
        new=AsyncMock(),
    ):
        return await ArtifactService().create_artifact(
            project_id=project.id, type_id=t.id, **kw
        )


async def test_markdown_artifact_ingested_with_redaction_and_edge(
    mock_ensure, mock_embedding, mock_upsert
) -> None:
    _space, project, t = await _setup("markdown", True, key="md")
    secret = "sk-ant-abcdefghij1234567890"
    artifact = await _create_artifact(
        project, t, title="研发 Spec", content_ref=f"# Spec\ntoken={secret}\n正文"
    )

    n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))
    assert n == 1

    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    entity = await KnowledgeEntity.objects.filter(id=entity_id).afirst()
    assert entity is not None
    assert entity.kind == EntityKind.DOCUMENT
    assert entity.title == "研发 Spec"
    assert str(entity.space_id) == str(project.space_id)
    payloads = [point["payload"] for batch in mock_upsert for point in batch]
    assert payloads
    assert {payload["project_id"] for payload in payloads} == {str(project.id)}

    version = await KnowledgeEntityVersion.objects.filter(
        entity_id=entity_id, is_latest=True
    ).afirst()
    assert version is not None
    # 脱敏不可绕过：正文不含明文 secret
    assert secret not in version.content
    assert "正文" in version.content

    # 工件→REFERENCES→项目图谱节点边
    pnode = project_node_id(project.id)
    assert await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        target_entity_id=pnode,
        relation=EdgeRelation.REFERENCES,
        invalid_at__isnull=True,
    ).aexists()


async def test_graphic_artifact_metadata_only_registered(
    mock_ensure, mock_embedding, mock_upsert
) -> None:
    """非 ragable（external_link）工件 → 元数据-only 登记：实体 + 边存在，零向量。"""
    _space, project, t = await _setup("external_link", False, key="ui")
    artifact = await _create_artifact(
        project, t, title="UI 稿", url="https://figma.com/file/x"
    )

    # produce 1 event（不再返回空）
    normalize = get_normalizer("artifact")
    events = await normalize(IngestionRequest("artifact", str(artifact.id), "test"))
    assert len(events) == 1
    assert events[0].vectorize is False

    # 经完整摄取后落库
    n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))
    assert n == 1

    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    entity = await KnowledgeEntity.objects.filter(id=entity_id).afirst()
    assert entity is not None
    assert entity.kind == EntityKind.DOCUMENT
    assert entity.title == "UI 稿"

    version = await KnowledgeEntityVersion.objects.filter(
        entity_id=entity_id, is_latest=True
    ).afirst()
    assert version is not None
    # 元数据-only：无向量点、vector_synced=True、payload 承载工件元数据
    assert version.qdrant_point_ids == []
    assert version.vector_synced is True
    assert version.payload["type"] == "ui"
    assert version.payload["carrier"] == "external_link"
    assert version.payload["url"] == "https://figma.com/file/x"

    # 工件→REFERENCES→项目图谱节点边存在
    pnode = project_node_id(project.id)
    assert await KnowledgeEdge.objects.filter(
        source_entity_id=entity_id,
        target_entity_id=pnode,
        relation=EdgeRelation.REFERENCES,
        invalid_at__isnull=True,
    ).aexists()

    # 无向量写入
    assert mock_upsert == []


async def test_feishu_doc_fetch_failure_fail_soft(
    mock_ensure, mock_embedding, mock_upsert
) -> None:
    _space, project, t = await _setup("feishu_doc", True, key="fd")
    artifact = await _create_artifact(
        project, t, title="需求", url="https://x.feishu.cn/docx/tok123"
    )
    with patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
        new=AsyncMock(side_effect=RuntimeError("无凭证")),
    ):
        n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))
    # fail-soft：缺正文不缺实体
    assert n == 1
    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    assert await KnowledgeEntity.objects.filter(id=entity_id).aexists()


async def test_feishu_doc_fetch_by_full_url_ingested(
    mock_ensure, mock_embedding, mock_upsert
) -> None:
    _space, project, t = await _setup("feishu_doc", True, key="fdok")
    artifact = await _create_artifact(
        project, t, title="旧版需求", url="https://x.feishu.cn/docs/doccn123"
    )
    mock_client = AsyncMock()
    mock_client.get_document_content_by_url = AsyncMock(return_value=("真实正文", []))

    with patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
        new=AsyncMock(return_value=mock_client),
    ):
        n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))

    assert n == 1
    mock_client.get_document_content_by_url.assert_awaited_once_with(
        "https://x.feishu.cn/docs/doccn123"
    )
    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    version = await KnowledgeEntityVersion.objects.filter(
        entity_id=entity_id, is_latest=True
    ).afirst()
    assert version is not None
    assert "真实正文" in version.content


async def test_bitable_without_table_id_lists_tables(
    mock_ensure, mock_embedding, mock_upsert
) -> None:
    _space, project, t = await _setup("feishu_bitable", True, key="bt")
    artifact = await _create_artifact(
        project, t, title="指标表", url="https://x.feishu.cn/base/appToken123"
    )
    mock_client = AsyncMock()
    mock_client.list_tables = AsyncMock(
        return_value={"items": [{"table_id": "tbl_a"}, {"table_id": "tbl_b"}]}
    )
    mock_client.list_records = AsyncMock(
        side_effect=[
            {"items": [{"fields": {"指标": "留存"}}], "has_more": False},
            {"items": [{"fields": {"指标": "转化"}}], "has_more": False},
        ]
    )

    with patch(
        "services.feishu_bitable.create_bitable_client_for_project",
        new=AsyncMock(return_value=mock_client),
    ):
        n = await ingest(IngestionRequest("artifact", str(artifact.id), "test"))

    assert n == 1
    mock_client.list_tables.assert_awaited_once_with("appToken123")
    assert mock_client.list_records.await_count == 2
    entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(artifact.id))
    version = await KnowledgeEntityVersion.objects.filter(
        entity_id=entity_id, is_latest=True
    ).afirst()
    assert version is not None
    assert "Table tbl_a" in version.content
    assert "留存" in version.content
    assert "Table tbl_b" in version.content
    assert "转化" in version.content

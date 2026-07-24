"""feishu_document normalizer 端到端守护测试（Plan 30-03 / DOC-02）。

覆盖：

- normalize 产出形状：work_item 锚事件（携 REFERENCES 出边）+ document 事件；
  REFERENCES EdgeSpec.target_entity_id == generate_entity_id("document","feishu_document",token)。
- 端到端入图（await ingest_events）：KnowledgeEntity(kind=document) +
  KnowledgeEdge(REFERENCES, work_item→document)。
- 操作态 Document/DocumentVersion 经 DocumentService 落库 + work_item FK + facet=complete。
- 降级（DOC-02 关键）：get_document_content 抛异常 → 正文空 → 不抛、document 事件 +
  REFERENCES 边仍在、Document 仍建（content 空）、facet=missing（缺段不缺实体）。
- hash 相等不翻版本：二次 normalize 同正文 → DocumentVersion 计数不变。
- INV-3：work_item 锚事件 content 与单独跑 feishu_work_item.normalize 一致（不 clobber）。

无真实网络：feishu client / doc client 全 monkeypatch，pytest-socket 第二保险；
embedding / qdrant / collection mock 复用 conftest。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    ContentStorage,
    Document,
    DocumentSourceKind,
    DocumentType,
    DocumentVersion,
    SyncFacet,
    SyncStatus,
    WorkItem,
    WorkItemOrigin,
    WorkItemSyncState,
)
from feishu.models import KeyFields
from knowledge.ingestion import IngestionRequest, ingest_events
from knowledge.models import (
    EdgeRelation,
    KnowledgeEdge,
    KnowledgeEntity,
    generate_entity_id,
)
from knowledge.sources import feishu_document, feishu_work_item
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

# DOMAIN §16 实测自然键 + 多租户深链
PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002
SOURCE_ID = f"{PROJECT_KEY}:story:{STORY_ID}"
PRD_TOKEN = "PrdDocToken123456"
TECH_TOKEN = "TechDocToken78901"
PRD_URL = f"https://acme.feishu.cn/docx/{PRD_TOKEN}"
TECH_URL = f"https://acme.feishu.cn/docx/{TECH_TOKEN}"
PRD_BODY = "# PRD 标题\n\nPRD 正文内容，验收点若干。"
TECH_BODY = "# 技术方案\n\n架构与接口设计。"


def _make_request() -> IngestionRequest:
    return IngestionRequest(
        source_kind="feishu_document",
        source_id=SOURCE_ID,
        trigger="test_feishu_document",
    )


async def _make_project() -> Space:
    return await Space.objects.acreate(name="测试项目", feishu_project_key=PROJECT_KEY)


async def _make_work_item() -> WorkItem:
    return await WorkItem.objects.acreate(
        feishu_project_key=PROJECT_KEY,
        work_item_type="story",
        work_item_id=STORY_ID,
        origin=WorkItemOrigin.MANUAL,
        title="测试需求",
    )


@pytest.fixture
def mock_ensure(monkeypatch) -> AsyncMock:
    """ensure_delivery_knowledge_collection 的 AsyncMock seam（不触 Qdrant）。"""
    ensure = AsyncMock()
    monkeypatch.setattr("knowledge.ingestion.ensure_delivery_knowledge_collection", ensure)
    return ensure


@pytest.fixture
def mock_upsert(monkeypatch) -> list[list[str]]:
    """upsert_vectors_by_name 计数 seam：记录每批 point id 列表并返回 True。"""
    from services.qdrant_service import QdrantService

    calls: list[list[str]] = []

    def _fake(cls, name, pts):
        calls.append([p["id"] for p in pts])
        return True

    monkeypatch.setattr(QdrantService, "upsert_vectors_by_name", classmethod(_fake))
    return calls


@pytest.fixture
def mock_feishu_clients(monkeypatch):
    """monkeypatch feishu client（get_work_item/relations）+ doc client（get_document_content）。

    返回可调配置对象：``set(prd_url, tech_doc_url, prd_body, tech_body, raise_doc=False)``。
    """

    cfg = SimpleNamespace(
        name="测试需求",
        description="需求描述",
        status="developing",
        prd_url=PRD_URL,
        tech_doc_url="",
        prd_body=PRD_BODY,
        tech_body=TECH_BODY,
        raise_doc=False,
    )

    class _FakeFeishuClient:
        async def get_work_item(self, *, project_key, work_item_id, work_item_type):
            return SimpleNamespace(
                name=cfg.name,
                description=cfg.description,
                status=cfg.status,
                fields={
                    KeyFields.PRD_URL: cfg.prd_url,
                    KeyFields.TECH_DOC_URL: cfg.tech_doc_url,
                },
            )

        async def get_work_item_relations(self, *, project_key, work_item_id, work_item_type):
            return []

    class _FakeDocClient:
        async def get_document_content(self, token):
            if cfg.raise_doc:
                raise RuntimeError("doc fetch boom")
            body = cfg.prd_body if token == PRD_TOKEN else cfg.tech_body
            return body, []

    fake_doc = _FakeDocClient()
    monkeypatch.setattr(
        feishu_work_item, "create_feishu_client_for_project", lambda project: _FakeFeishuClient()
    )
    doc_factory = AsyncMock(return_value=fake_doc)
    monkeypatch.setattr(feishu_work_item, "create_feishu_doc_client_for_project", doc_factory)
    monkeypatch.setattr(feishu_document, "create_feishu_doc_client_for_project", doc_factory)
    return cfg


# ============================================================================
# normalize 产出形状 + REFERENCES 边
# ============================================================================


async def test_normalize_shape_work_item_anchor_with_references_edge(mock_feishu_clients) -> None:
    """work_item 锚事件携 REFERENCES 出边 + document 事件；target id 经 generate_entity_id。"""
    await _make_project()
    await _make_work_item()

    events = await feishu_document.normalize(_make_request())

    # [wi 锚, prd document]
    assert len(events) == 2
    wi_event, doc_event = events[0], events[1]
    assert wi_event.kind == "work_item"
    assert wi_event.source_kind == "feishu_work_item"
    assert doc_event.kind == "document"
    assert doc_event.source_kind == "feishu_document"
    assert doc_event.source_id == PRD_TOKEN
    assert doc_event.content == PRD_BODY
    assert doc_event.payload["document_type"] == "prd"

    # work_item 锚携一条 REFERENCES 出边，target = document 实体 id
    assert len(wi_event.edges) == 1
    edge = wi_event.edges[0]
    assert edge.relation == EdgeRelation.REFERENCES
    assert edge.target_entity_id == generate_entity_id("document", "feishu_document", PRD_TOKEN)


async def test_normalize_both_prd_and_tech_produce_two_references(mock_feishu_clients) -> None:
    """prd_url + tech_doc_url 同时存在 → 两 document 事件 + 两 REFERENCES 出边。"""
    mock_feishu_clients.tech_doc_url = TECH_URL
    await _make_project()
    await _make_work_item()

    events = await feishu_document.normalize(_make_request())

    assert len(events) == 3  # wi 锚 + prd + tech
    wi_event = events[0]
    relations = {(e.relation, e.target_entity_id) for e in wi_event.edges}
    assert (
        EdgeRelation.REFERENCES,
        generate_entity_id("document", "feishu_document", PRD_TOKEN),
    ) in relations
    assert (
        EdgeRelation.REFERENCES,
        generate_entity_id("document", "feishu_document", TECH_TOKEN),
    ) in relations


# ============================================================================
# 端到端入图（ingest_events）：KnowledgeEntity(document) + KnowledgeEdge(REFERENCES)
# ============================================================================


async def test_end_to_end_ingest_builds_document_entity_and_references_edge(
    mock_feishu_clients, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """await ingest_events → document 实体 + REFERENCES 边（work_item→document）。"""
    await _make_project()
    await _make_work_item()

    events = await feishu_document.normalize(_make_request())
    await ingest_events(events)

    wi_entity_id = generate_entity_id("work_item", "feishu_work_item", SOURCE_ID)
    doc_entity_id = generate_entity_id("document", "feishu_document", PRD_TOKEN)

    doc_entity = await KnowledgeEntity.objects.aget(id=doc_entity_id)
    assert doc_entity.kind == "document"
    assert doc_entity.source_kind == "feishu_document"
    assert doc_entity.source_id == PRD_TOKEN

    edge = await KnowledgeEdge.objects.aget(relation=EdgeRelation.REFERENCES)
    assert edge.source_entity_id == wi_entity_id
    assert edge.target_entity_id == doc_entity_id
    assert edge.invalid_at is None


# ============================================================================
# 操作态 Document/DocumentVersion（经 DocumentService）
# ============================================================================


async def test_operational_document_persisted_via_service(mock_feishu_clients) -> None:
    """normalize 落操作态 Document(work_item, prd, both, external_ref=token) + v1 + facet complete。"""
    await _make_project()
    work_item = await _make_work_item()

    await feishu_document.normalize(_make_request())

    doc = await Document.objects.aget(external_ref=PRD_TOKEN)
    assert doc.document_type == DocumentType.PRD
    assert doc.source_kind == DocumentSourceKind.EXTERNAL_FEISHU
    assert doc.content_storage == ContentStorage.BOTH
    assert doc.work_item_id == work_item.id
    assert doc.feishu_tenant == "acme"

    cur = await DocumentVersion.objects.aget(pk=doc.current_version_id)
    assert cur.content == PRD_BODY

    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.PRD_BODY)
    assert state.status == SyncStatus.COMPLETE


# ============================================================================
# 降级（DOC-02 关键）：doc 拉取失败 → 缺段不缺实体，不抛不回滚
# ============================================================================


async def test_doc_fetch_failure_degrades_without_raise(mock_feishu_clients) -> None:
    """get_document_content 抛异常 → 正文空：normalize 不抛、document 事件 + REFERENCES 边仍在、
    Document 仍建（content 空）、facet=missing。"""
    mock_feishu_clients.raise_doc = True
    await _make_project()
    work_item = await _make_work_item()

    events = await feishu_document.normalize(_make_request())

    # 事件 + 边照常产出
    assert len(events) == 2
    wi_event, doc_event = events[0], events[1]
    assert doc_event.content == ""
    assert len(wi_event.edges) == 1
    assert wi_event.edges[0].relation == EdgeRelation.REFERENCES

    # Document 仍建（content 空），facet=missing
    doc = await Document.objects.aget(external_ref=PRD_TOKEN)
    cur = await DocumentVersion.objects.aget(pk=doc.current_version_id)
    assert cur.content == ""
    state = await WorkItemSyncState.objects.aget(work_item=work_item, facet=SyncFacet.PRD_BODY)
    assert state.status == SyncStatus.MISSING


# ============================================================================
# hash 相等不翻版本
# ============================================================================


async def test_hash_equal_second_normalize_no_new_version(mock_feishu_clients) -> None:
    """同 work item 二次 normalize（同正文）→ DocumentVersion 计数不变（复用 DocumentService 范式）。"""
    await _make_project()
    await _make_work_item()

    await feishu_document.normalize(_make_request())
    await feishu_document.normalize(_make_request())

    doc = await Document.objects.aget(external_ref=PRD_TOKEN)
    assert await DocumentVersion.objects.filter(document=doc).acount() == 1


# ============================================================================
# INV-3：work_item 锚事件 content 与既有 feishu_work_item 投影一致（不 clobber）
# ============================================================================


async def test_inv3_work_item_anchor_content_matches_feishu_work_item(mock_feishu_clients) -> None:
    """work_item 锚事件 content 与单独跑 feishu_work_item.normalize 一致（hash 相等不 clobber 既有快照）。"""
    await _make_project()
    await _make_work_item()

    doc_events = await feishu_document.normalize(_make_request())
    wi_only_events = await feishu_work_item.normalize(_make_request())

    assert doc_events[0].content == wi_only_events[0].content
    assert doc_events[0].title == wi_only_events[0].title


# ============================================================================
# 无文档：work_item 锚事件原样返回（缺段不缺实体）
# ============================================================================


async def test_no_doc_token_returns_anchor_only(mock_feishu_clients) -> None:
    """prd_url / tech_doc_url 均空 → 仅返回 work_item 锚事件（无 document、无 REFERENCES 边）。"""
    mock_feishu_clients.prd_url = ""
    mock_feishu_clients.tech_doc_url = ""
    await _make_project()
    await _make_work_item()

    events = await feishu_document.normalize(_make_request())

    assert len(events) == 1
    assert events[0].kind == "work_item"
    assert events[0].edges == ()
    assert await Document.objects.acount() == 0

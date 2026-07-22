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


# ---- KNOW-06（Phase 102）：STATE 文档 live API 清单 ----


@sync_to_async
def _make_state_apis(project_id, rows: list[tuple[str, str, str]]) -> None:
    from initiatives.models import ProjectStateApi

    for method, path, api_status in rows:
        ProjectStateApi.objects.create(
            project_id=project_id, method=method, path=path, status=api_status
        )


async def test_state_doc_content_includes_live_api_rows() -> None:
    """STATE 文档 normalize 追加 live「METHOD path — status」API 行（snapshot 不含 API 行）。"""
    doc = await _make_doc("# 项目状态\n人工区备注", doc_type=DocType.STATE)
    project = await sync_to_async(lambda: doc.project)()
    await _make_state_apis(
        project.id,
        [("GET", "/api/x", "implemented"), ("POST", "/api/y", "planned")],
    )
    normalize = get_normalizer("project_doc")

    events = await normalize(IngestionRequest("project_doc", str(doc.id), "test"))

    assert len(events) == 1
    content = events[0].content
    assert "## API 清单" in content
    assert "GET /api/x — implemented" in content
    assert "POST /api/y — planned" in content
    # snapshot 人工区内容保留（追加而非覆盖）。
    assert "人工区备注" in content


async def test_non_state_doc_content_unchanged() -> None:
    """非 STATE 文档零变化：同项目存在 ProjectStateApi 行也不拼入 content（仅 snapshot）。"""
    doc = await _make_doc("# 项目记忆\n记忆正文", doc_type=DocType.MEMORY)
    project = await sync_to_async(lambda: doc.project)()
    await _make_state_apis(project.id, [("GET", "/api/x", "implemented")])
    normalize = get_normalizer("project_doc")

    events = await normalize(IngestionRequest("project_doc", str(doc.id), "test"))

    assert len(events) == 1
    content = events[0].content
    assert "GET /api/x" not in content
    assert "## API 清单" not in content
    assert "记忆正文" in content


async def test_report_to_search_content_chain() -> None:
    """验收链（CI 无 Qdrant 的诚实边界）：上报 → 物化调度捕获 → normalize 内容含 API 行。

    向量入库与 search_project_context 命中由既有 ingestion/search_similar 测试与
    include_document_kind 路径（Phase 85 CTX-01 用例）覆盖；本链断言到「摄取内容包含
    API 清单」这一确定性环节。
    """
    from unittest.mock import AsyncMock, patch

    from initiatives.services import ProjectDocService

    doc = await _make_doc("# 项目状态\n", doc_type=DocType.STATE)
    project = await sync_to_async(lambda: doc.project)()

    mock_schedule = AsyncMock()
    with patch("knowledge.ingestion.aschedule_ingestion", mock_schedule):
        await ProjectDocService().upsert_state_api(
            project_id=project.id, method="GET", path="/api/chain", status="implemented"
        )

    mock_schedule.assert_awaited()
    captured_request = mock_schedule.await_args_list[-1].args[0]
    assert captured_request.source_kind == "project_doc"
    assert captured_request.source_id == str(doc.id)

    normalize = get_normalizer("project_doc")
    events = await normalize(captured_request)

    assert len(events) == 1
    assert events[0].kind == EntityKind.DOCUMENT
    assert "GET /api/chain — implemented" in events[0].content

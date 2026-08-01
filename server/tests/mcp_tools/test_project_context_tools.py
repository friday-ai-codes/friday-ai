"""项目上下文读半 MCP 工具守护测试（Phase 85-02，CTX-01/02）。

覆盖三个新工具（search_project_context / grep_project / read_project_doc）：

- **members_only 零泄漏安全门**（Task 1，真实 PASS 非 xfail）：非成员对 members_only 项目内容
  经三工具一律零结果零正文；search_similar 维度亦零召回。
- **public_org 非成员可读 / 成员任意 visibility 可读**（visibility 对称）。
- grep 命中 ProjectDoc 正文 + 记忆正文（CTX-01 可 grep 正文）+ locator。
- read_project_doc 渲染 + blocks + trace 含 duration_ms；doc 不存在返回空文档不报错。
- RetrievalTrace 两链覆盖（MCP 链本工具 + AI 对话链既有 packer，CTX-02）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from initiatives.models import DocSection, DocType, ProjectVisibility
from initiatives.services import MemoryService, ProjectDocService, ProjectService
from interactions.models import RetrievalTrace
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

_SEARCH_URL = "/api/mcp/tools/search_project_context/"
_GREP_URL = "/api/mcp/tools/grep_project/"
_READ_URL = "/api/mcp/tools/read_project_doc/"


@sync_to_async
def _make_user(username: str):
    return User.objects.create_user(username=username, password="x")


async def _make_project(created_by, *, key, visibility=ProjectVisibility.PUBLIC_ORG):
    """建 space + project（owner=created_by → ProjectMember），按需设 visibility（夹具直写）。"""
    space = await sync_to_async(Space.objects.create)(name="S", feishu_project_key=f"{key}-sp")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=created_by
    )
    if visibility != ProjectVisibility.PUBLIC_ORG:
        project.visibility = visibility
        await project.asave(update_fields=["visibility"])
    return project


async def _add_doc(project, *, doc_type=DocType.STATE, snapshot=""):
    return await ProjectDocService().upsert_doc(
        project_id=project.id, doc_type=doc_type, last_synced_snapshot=snapshot
    )


def _mock_search_result(project_id: str) -> SearchResultDTO:
    return SearchResultDTO(
        score=0.88,
        vector_score=0.88,
        recency_score=0.5,
        entity=EntityMetadata(
            entity_id=uuid.uuid4(),
            entity_kind="document",
            version=1,
            title="项目文档命中",
            valid_at=None,
            invalid_at=None,
            source_kind="project_doc",
            source_id="doc-1",
            origin="project",
            event_time=None,
            space_id=project_id,
            repository_id=None,
            provenance=ProvenanceLinks(),
        ),
    )


@sync_to_async
def _traces_with_source(source: str) -> list[RetrievalTrace]:
    return [t for t in RetrievalTrace.objects.all() if (t.payload or {}).get("source") == source]


# ---------------------------------------------------------------------------
# Task 1 安全门：members_only 非成员零泄漏（真实 PASS，非 xfail）
# ---------------------------------------------------------------------------


async def test_members_only_non_member_search_scope_zero_leak(mcp_client, access_user):
    """members_only + 非成员 → search_project_context 零召回（gate fail-closed）。"""
    client, _ = mcp_client
    owner = await _make_user("mo-search-owner")
    project = await _make_project(owner, key="mo-search", visibility=ProjectVisibility.MEMBERS_ONLY)
    resp = await sync_to_async(client.post)(
        _SEARCH_URL, {"project_id": str(project.id), "query": "登录"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["total"] == 0


async def test_members_only_non_member_grep_zero_leak(mcp_client, access_user):
    """members_only + 非成员 → grep_project 零结果（不泄漏正文，即便正文含关键词）。"""
    client, _ = mcp_client
    owner = await _make_user("mo-grep-owner")
    project = await _make_project(owner, key="mo-grep", visibility=ProjectVisibility.MEMBERS_ONLY)
    await _add_doc(project, snapshot="机密接口设计 secretpattern 必须仅成员可见")
    await MemoryService().append(
        project_id=project.id,
        content="机密记忆 secretpattern",
        contributor=owner,
        _skip_member_check=True,
    )
    resp = await sync_to_async(client.post)(
        _GREP_URL, {"project_id": str(project.id), "query": "secretpattern"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] == []
    assert body["total"] == 0


async def test_members_only_non_member_read_zero_leak(mcp_client, access_user):
    """members_only + 非成员 → read_project_doc 返回空文档（不泄漏正文/存在性）。"""
    client, _ = mcp_client
    owner = await _make_user("mo-read-owner")
    project = await _make_project(owner, key="mo-read", visibility=ProjectVisibility.MEMBERS_ONLY)
    await _add_doc(project, doc_type=DocType.STATE, snapshot="机密状态正文 secretbody")
    resp = await sync_to_async(client.post)(
        _READ_URL, {"project_id": str(project.id), "doc_type": "state"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rendered_markdown"] == ""
    assert body["blocks"] == []
    assert "secretbody" not in str(body)


# ---------------------------------------------------------------------------
# visibility 对称：public_org 非成员可读 / 成员任意 visibility 可读
# ---------------------------------------------------------------------------


async def test_public_org_non_member_grep_readable(mcp_client, access_user):
    """public_org + 非成员 → grep_project 可读（命中 ProjectDoc 正文）。"""
    client, _ = mcp_client
    owner = await _make_user("po-grep-owner")
    project = await _make_project(owner, key="po-grep", visibility=ProjectVisibility.PUBLIC_ORG)
    await _add_doc(project, snapshot="公开接口 publicmarker 全员可读")
    resp = await sync_to_async(client.post)(
        _GREP_URL, {"project_id": str(project.id), "query": "publicmarker"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(r["kind"] == "project_doc" for r in body["results"])


async def test_public_org_non_member_read_readable(mcp_client, access_user):
    """public_org + 非成员 → read_project_doc 可读正文。"""
    client, _ = mcp_client
    owner = await _make_user("po-read-owner")
    project = await _make_project(owner, key="po-read", visibility=ProjectVisibility.PUBLIC_ORG)
    await _add_doc(project, doc_type=DocType.STATE, snapshot="公开状态正文 publicbody")
    resp = await sync_to_async(client.post)(
        _READ_URL, {"project_id": str(project.id), "doc_type": "state"}, format="json"
    )
    assert resp.status_code == 200
    assert "publicbody" in resp.json()["rendered_markdown"]


async def test_member_members_only_grep_readable(mcp_client, access_user):
    """成员（owner）+ members_only → grep_project 仍可读（不回退）。"""
    client, _ = mcp_client
    project = await _make_project(
        access_user, key="mem-mo", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    await _add_doc(project, snapshot="成员可见正文 memvisible")
    resp = await sync_to_async(client.post)(
        _GREP_URL, {"project_id": str(project.id), "query": "memvisible"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


# ---------------------------------------------------------------------------
# Task 2 search_project_context：召回 + RetrievalTrace（含 duration_ms）+ 校验
# ---------------------------------------------------------------------------


async def test_search_project_context_member_hits_and_trace(mcp_client, access_user, monkeypatch):
    """成员调用命中（mock search_similar）→ results/total/run_id + RetrievalTrace 含 duration_ms。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="sp-hit")

    from mcp_tools import views as views_module

    monkeypatch.setattr(
        views_module._delivery_knowledge_service,
        "search_similar",
        AsyncMock(return_value=[_mock_search_result(str(project.space_id))]),
    )
    resp = await sync_to_async(client.post)(
        _SEARCH_URL,
        {"project_id": str(project.id), "query": "登录态", "top_k": 5},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == str(project.id)
    assert body["query"] == "登录态"
    assert body["total"] == 1
    assert body["run_id"]
    assert body["results"][0]["title"] == "项目文档命中"

    traces = await _traces_with_source("mcp_search_project_context")
    assert len(traces) == 1
    payload = traces[0].payload
    assert "duration_ms" in payload
    assert payload["result_count"] == 1
    assert payload["project_id"] == str(project.id)


async def test_search_project_context_recalls_document_kind(mcp_client, access_user, monkeypatch):
    """CTX-01：search_project_context 读路径纳入 DOCUMENT 召回（物化项目文档可被向量 RAG 返回）。

    断言：调用 search_similar 时透传 ``include_document_kind=True``（widen 到 DOCUMENT 实体），
    且返回的物化项目文档命中出现在结果里（不绕过 visibility/access 闸）。
    """
    client, _ = mcp_client
    project = await _make_project(access_user, key="sp-doc")

    from mcp_tools import views as views_module

    captured: dict = {}

    async def _fake_search_similar(query, **kwargs):
        captured.update(kwargs)
        return [_mock_search_result(str(project.space_id))]

    monkeypatch.setattr(
        views_module._delivery_knowledge_service,
        "search_similar",
        _fake_search_similar,
    )
    resp = await sync_to_async(client.post)(
        _SEARCH_URL,
        {"project_id": str(project.id), "query": "项目文档"},
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    # 读路径必须 widen 到 DOCUMENT 召回（否则项目物化文档/记忆向量 RAG 返回空）。
    assert captured.get("include_document_kind") is True
    assert body["total"] == 1
    assert body["results"][0]["title"] == "项目文档命中"


async def test_search_project_context_missing_query_400(mcp_client, access_user):
    client, _ = mcp_client
    project = await _make_project(access_user, key="sp-400")
    resp = await sync_to_async(client.post)(
        _SEARCH_URL, {"project_id": str(project.id)}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_params"


async def test_search_project_context_missing_project_id_400(mcp_client, access_user):
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(_SEARCH_URL, {"query": "q"}, format="json")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Task 3 grep（ProjectDoc / 记忆正文）+ read_project_doc
# ---------------------------------------------------------------------------


async def test_grep_hits_project_doc_body_with_locator(mcp_client, access_user):
    """grep 命中 ProjectDoc 正文关键词 → 返回 project_doc 命中带 locator（含 project 归属）。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="grep-doc")
    await _add_doc(project, doc_type=DocType.RESEARCH, snapshot="调研结论 grepdocmark 值得采纳")
    resp = await sync_to_async(client.post)(
        _GREP_URL, {"project_id": str(project.id), "query": "grepdocmark"}, format="json"
    )
    assert resp.status_code == 200
    hits = [r for r in resp.json()["results"] if r["kind"] == "project_doc"]
    assert hits
    assert hits[0]["locator"]["project_id"] == str(project.id)


async def test_grep_hits_memory_body(mcp_client, access_user):
    """grep 命中 active 记忆正文关键词。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="grep-mem")
    await MemoryService().append(
        project_id=project.id,
        content="记忆要点 grepmemmark",
        contributor=access_user,
        _skip_member_check=True,
    )
    resp = await sync_to_async(client.post)(
        _GREP_URL, {"project_id": str(project.id), "query": "grepmemmark"}, format="json"
    )
    assert resp.status_code == 200
    assert any(r["kind"] == "memory" for r in resp.json()["results"])


async def test_grep_missing_query_400(mcp_client, access_user):
    client, _ = mcp_client
    project = await _make_project(access_user, key="grep-400")
    resp = await sync_to_async(client.post)(
        _GREP_URL, {"project_id": str(project.id)}, format="json"
    )
    assert resp.status_code == 400


async def test_grep_project_not_found_404(mcp_client, access_user):
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _GREP_URL, {"project_id": str(uuid.uuid4()), "query": "x"}, format="json"
    )
    assert resp.status_code == 404


async def test_read_project_doc_renders_blocks_and_trace(mcp_client, access_user):
    """read_project_doc 渲染 markdown + blocks（section/editable）+ trace 含 duration_ms。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="read-doc")
    doc = await _add_doc(project, doc_type=DocType.STATE, snapshot="状态正文 readbody")
    await ProjectDocService().upsert_block_map(
        doc_id=doc.id,
        feishu_block_id="blk-human-1",
        db_ref="",
        section=DocSection.HUMAN,
    )
    resp = await sync_to_async(client.post)(
        _READ_URL, {"project_id": str(project.id), "doc_type": "state"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "readbody" in body["rendered_markdown"]
    assert any(b["section"] == DocSection.HUMAN and b["editable"] for b in body["blocks"])

    traces = await _traces_with_source("mcp_read_project_doc")
    assert len(traces) == 1
    assert "duration_ms" in traces[0].payload


async def test_read_project_doc_missing_returns_empty(mcp_client, access_user):
    """doc 不存在 → 返回空文档不报错（不泄漏存在性）。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="read-missing")
    resp = await sync_to_async(client.post)(
        _READ_URL, {"project_id": str(project.id), "doc_type": "milestones"}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rendered_markdown"] == ""
    assert body["blocks"] == []


async def test_read_project_doc_missing_doc_type_400(mcp_client, access_user):
    client, _ = mcp_client
    project = await _make_project(access_user, key="read-400")
    resp = await sync_to_async(client.post)(
        _READ_URL, {"project_id": str(project.id)}, format="json"
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# CTX-02 RetrievalTrace 两链覆盖（MCP 链 + AI 对话链）
# ---------------------------------------------------------------------------


async def test_retrieval_trace_two_chains_covered(mcp_client, access_user, monkeypatch):
    """MCP 链（search_project_context）+ AI 对话链（pack_project_context）各写一条 trace。"""
    client, _ = mcp_client
    project = await _make_project(access_user, key="two-chain")
    await MemoryService().append(
        project_id=project.id,
        content="两链召回记忆",
        contributor=access_user,
        _skip_member_check=True,
    )

    from mcp_tools import views as views_module

    monkeypatch.setattr(
        views_module._delivery_knowledge_service,
        "search_similar",
        AsyncMock(return_value=[]),
    )
    # MCP 链
    resp = await sync_to_async(client.post)(
        _SEARCH_URL, {"project_id": str(project.id), "query": "记忆"}, format="json"
    )
    assert resp.status_code == 200

    # AI 对话链（既有 packer 写 chat_project_context trace）
    from services.project_context_packer import pack_project_context

    await pack_project_context(project, access_user, query="记忆")

    mcp_traces = await _traces_with_source("mcp_search_project_context")
    chat_traces = await sync_to_async(
        lambda: list(RetrievalTrace.objects.filter(source="chat_project_context"))
    )()
    assert mcp_traces, "MCP 链 RetrievalTrace 缺失"
    assert chat_traces, "AI 对话链 RetrievalTrace 缺失"

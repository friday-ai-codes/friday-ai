"""chat 知识读工具测试（Phase 102 KNOW-05）。

范式照抄 ``test_delivery_knowledge_tools.py``：service / 底层函数 monkeypatch AsyncMock，
不触 Qdrant（``--disable-socket`` 第二道保险）。覆盖：

- 注册 / 白名单：三工具进 ``_tool_registry``，且挂进 chat_runner 对应白名单常量；
- 三工具正反路径：fail-closed（无效会话 / 非成员非 public_org）与成功路径；
- 参数透传：hints / limit / project_ids / include_document_kind；
- trace best-effort：``arecord_retrieval_trace`` 抛异常时工具仍 success。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from agents.tools.base import _tool_registry
from agents.tools.knowledge_read_tools import (
    read_project_doc,
    search_learning_cases,
    search_project_context,
)
from chat.models import Conversation
from initiatives.models import ProjectVisibility
from initiatives.services import ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


# ---- 注册 / 白名单 ----


def test_tools_registered_and_whitelisted() -> None:
    from agents.chat_runner import _INDEXED_TOOL_NAMES, _PROJECT_READ_TOOL_NAMES

    assert "search_learning_cases" in _INDEXED_TOOL_NAMES
    assert {"search_project_context", "read_project_doc"} <= set(_PROJECT_READ_TOOL_NAMES)
    assert {
        "search_learning_cases",
        "search_project_context",
        "read_project_doc",
    } <= set(_tool_registry)


# ---- fixtures / helpers ----


@sync_to_async
def _make_user(username: str):
    return User.objects.create_user(username=username, password="x")


async def _make_project_with_owner(
    *, key: str, visibility: str = ProjectVisibility.PUBLIC_ORG
):
    """建项目 + owner 成员；visibility 夹具直写（仅测试用，不进生产写路径）。"""
    space = await sync_to_async(Space.objects.create)(name=f"S-{key}")
    owner = await _make_user(f"owner-{key}")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=owner
    )
    if visibility != ProjectVisibility.PUBLIC_ORG:
        project.visibility = visibility
        await project.asave(update_fields=["visibility"])
    return project, owner


async def _make_conversation(*, created_by, bound_project=None):
    return await sync_to_async(Conversation.objects.create)(
        title="t", created_by=created_by, bound_project=bound_project
    )


# ---- search_learning_cases ----


async def test_search_learning_cases_invalid_conversation_fail_closed() -> None:
    result = await search_learning_cases(query="q", conversation_id="")
    assert result.success is False
    assert "fail-closed" in (result.error or "")


async def test_search_learning_cases_passes_through_to_service() -> None:
    owner = await _make_user("lc-owner")
    conversation = await _make_conversation(created_by=owner)
    mock_search = AsyncMock(return_value=[{"score": 0.9}, {"score": 0.8}])
    with patch("mcp_tools.learning_case_service.search_learning_cases", mock_search):
        result = await search_learning_cases(
            query="登录优化",
            work_item_type="story",
            repo_hints=["repo-a"],
            file_hints=["a.py"],
            symbol_hints=["login"],
            limit=7,
            conversation_id=str(conversation.id),
        )
    assert result.success is True
    assert result.output["total"] == 2
    mock_search.assert_awaited_once()
    kwargs = mock_search.await_args.kwargs
    assert kwargs["user"].id == owner.id
    assert kwargs["repo_hints"] == ["repo-a"]
    assert kwargs["file_hints"] == ["a.py"]
    assert kwargs["symbol_hints"] == ["login"]
    assert kwargs["limit"] == 7
    assert kwargs["work_item_type"] == "story"


async def test_search_learning_cases_clamps_oversized_limit() -> None:
    """102-REVIEW LO-02：LLM 直出 limit=10000 → 钳到上界 20，防 Qdrant 放大打击。"""
    owner = await _make_user("lc-clamp")
    conversation = await _make_conversation(created_by=owner)
    mock_search = AsyncMock(return_value=[])
    with patch("mcp_tools.learning_case_service.search_learning_cases", mock_search):
        result = await search_learning_cases(
            query="q", limit=10000, conversation_id=str(conversation.id)
        )
    assert result.success is True
    assert mock_search.await_args.kwargs["limit"] == 20


# ---- search_project_context ----


async def test_search_project_context_clamps_oversized_top_k() -> None:
    """102-REVIEW LO-02：LLM 直出 top_k=99999 → 钳到上界 20（对齐 MCP serializer）。"""
    project, owner = await _make_project_with_owner(key="spc-clamp")
    conversation = await _make_conversation(created_by=owner, bound_project=project)
    mock_search = AsyncMock(return_value=[])
    with patch(
        "agents.tools.knowledge_read_tools._service.search_similar", mock_search
    ):
        result = await search_project_context(
            query="q", top_k=99999, conversation_id=str(conversation.id)
        )
    assert result.success is True
    assert mock_search.await_args.kwargs["top_k"] == 20


async def test_search_project_context_non_member_fail_closed() -> None:
    project, _owner = await _make_project_with_owner(
        key="spc-mo", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    stranger = await _make_user("spc-stranger")
    conversation = await _make_conversation(created_by=stranger, bound_project=project)
    result = await search_project_context(
        query="q", conversation_id=str(conversation.id)
    )
    assert result.success is False
    assert "fail-closed" in (result.error or "")


async def test_search_project_context_member_passes_scope() -> None:
    project, owner = await _make_project_with_owner(key="spc-mem")
    conversation = await _make_conversation(created_by=owner, bound_project=project)
    mock_search = AsyncMock(return_value=[])
    with patch(
        "agents.tools.knowledge_read_tools._service.search_similar", mock_search
    ):
        result = await search_project_context(
            query="项目上下文", conversation_id=str(conversation.id)
        )
    assert result.success is True
    assert result.output["results"] == []
    assert result.output["project_id"] == str(project.id)
    mock_search.assert_awaited_once()
    kwargs = mock_search.await_args.kwargs
    assert kwargs["project_ids"] == [str(project.id)]
    assert kwargs["include_document_kind"] is True


# ---- read_project_doc ----


async def test_read_project_doc_returns_render() -> None:
    project, owner = await _make_project_with_owner(key="rpd-mem")
    conversation = await _make_conversation(created_by=owner, bound_project=project)
    with patch(
        "initiatives.services.doc_content_service.DocContentService.get_doc_render",
        new=AsyncMock(return_value={"rendered_markdown": "# STATE", "blocks": []}),
    ):
        result = await read_project_doc(
            doc_type="state", conversation_id=str(conversation.id)
        )
    assert result.success is True
    assert result.output["project_id"] == str(project.id)
    assert result.output["doc_type"] == "state"
    assert result.output["rendered_markdown"] == "# STATE"
    assert result.output["blocks"] == []


async def test_read_project_doc_missing_doc_fails() -> None:
    project, owner = await _make_project_with_owner(key="rpd-miss")
    conversation = await _make_conversation(created_by=owner, bound_project=project)
    with patch(
        "initiatives.services.doc_content_service.DocContentService.get_doc_render",
        new=AsyncMock(return_value=None),
    ):
        result = await read_project_doc(
            doc_type="state", conversation_id=str(conversation.id)
        )
    assert result.success is False
    assert "不存在" in (result.error or "")


# ---- trace best-effort ----


async def test_trace_failure_does_not_break_tool() -> None:
    """留痕 best-effort：arecord_retrieval_trace 抛异常，工具仍 success（绝不反噬）。"""
    project, owner = await _make_project_with_owner(key="trace-be")
    conversation = await _make_conversation(created_by=owner, bound_project=project)
    with (
        patch(
            "agents.tools.knowledge_read_tools._service.search_similar",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "interactions.ledger.arecord_retrieval_trace",
            new=AsyncMock(side_effect=RuntimeError("留痕炸了")),
        ),
    ):
        result = await search_project_context(
            query="q", conversation_id=str(conversation.id)
        )
    assert result.success is True

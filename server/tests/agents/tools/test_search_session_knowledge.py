"""Chat ``search_session_knowledge`` 共享 helper 与留痕 RED 契约（Phase 144 Wave 0）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from agents.tools.base import _tool_registry
from chat.models import Conversation

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()
_FORBIDDEN_TRACE_KEYS = {"query", "title", "text", "question", "answer", "essence"}


@sync_to_async
def _make_user(username: str):
    return User.objects.create_user(username=username, password="x")


async def _make_conversation(user) -> Conversation:
    return await sync_to_async(Conversation.objects.create)(title="capture", created_by=user)


def _tool():
    from agents.tools.knowledge_read_tools import search_session_knowledge

    return search_session_knowledge


def test_tool_registered_and_indexed_with_repository_required() -> None:
    from agents.chat_runner import _INDEXED_TOOL_NAMES

    assert "search_session_knowledge" in _tool_registry
    assert "search_session_knowledge" in _INDEXED_TOOL_NAMES
    schema = _tool_registry["search_session_knowledge"].parameters
    assert set(schema["required"]) >= {"query", "repository_id", "conversation_id"}
    assert "project_id" in schema["properties"]


async def test_invalid_conversation_owner_fails_closed() -> None:
    result = await _tool()(
        query="q",
        repository_id="repo-id",
        conversation_id="",
    )

    assert result.success is False
    assert "fail-closed" in (result.error or "")


async def test_delegates_repository_and_optional_project_to_shared_helper() -> None:
    user = await _make_user("session-search-owner")
    conversation = await _make_conversation(user)
    search = AsyncMock(return_value=[])

    with patch(
        "knowledge.session_capture_retrieval.search_session_knowledge",
        search,
    ):
        result = await _tool()(
            query="部署失败",
            repository_id="repo-1",
            project_id="project-1",
            top_k=9,
            conversation_id=str(conversation.id),
        )

    assert result.success is True
    kwargs = search.await_args.kwargs
    assert kwargs["query"] == "部署失败"
    assert kwargs["repository_id"] == "repo-1"
    assert kwargs["project_id"] == "project-1"
    assert kwargs["top_k"] == 9
    assert kwargs["user"].id == user.id


async def test_top_k_is_clamped_to_twenty() -> None:
    user = await _make_user("session-search-clamp")
    conversation = await _make_conversation(user)
    search = AsyncMock(return_value=[])

    with patch(
        "knowledge.session_capture_retrieval.search_session_knowledge",
        search,
    ):
        result = await _tool()(
            query="q",
            repository_id="repo-1",
            top_k=99999,
            conversation_id=str(conversation.id),
        )

    assert result.success is True
    assert search.await_args.kwargs["top_k"] == 20


async def test_empty_result_records_scalar_trace_without_body() -> None:
    user = await _make_user("session-search-trace")
    conversation = await _make_conversation(user)
    search = AsyncMock(return_value=[])
    record = AsyncMock()

    with (
        patch(
            "knowledge.session_capture_retrieval.search_session_knowledge",
            search,
        ),
        patch("interactions.ledger.arecord_retrieval_trace", record),
    ):
        result = await _tool()(
            query="不得进入留痕的查询",
            repository_id="repo-1",
            project_id="project-1",
            conversation_id=str(conversation.id),
        )

    assert result.success is True
    payload = record.await_args.kwargs["payload"]
    assert payload["result_count"] == 0
    assert payload["repository_id"] == "repo-1"
    assert payload["project_id"] == "project-1"
    assert payload["source_kind"] == "session_capture"
    assert not (_FORBIDDEN_TRACE_KEYS & set(payload))


async def test_trace_failure_does_not_break_chat_tool() -> None:
    user = await _make_user("session-search-trace-failure")
    conversation = await _make_conversation(user)

    with (
        patch(
            "knowledge.session_capture_retrieval.search_session_knowledge",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "interactions.ledger.arecord_retrieval_trace",
            new=AsyncMock(side_effect=RuntimeError("trace unavailable")),
        ),
    ):
        result = await _tool()(
            query="q",
            repository_id="repo-1",
            conversation_id=str(conversation.id),
        )

    assert result.success is True
    assert result.output["results"] == []
    assert result.output["total"] == 0

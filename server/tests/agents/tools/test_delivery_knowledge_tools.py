"""delivery knowledge chat tools 测试（Phase 16-02）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from pydantic import ValidationError

from agents.tools.delivery_knowledge_tools import (
    get_entity_timeline,
    get_related_entities,
    search_delivery_knowledge,
)
from agents.tools.langchain_adapter import build_langchain_tools
from agents.tools.registry import ToolRegistry
from agents.tools.schemas.delivery_knowledge import (
    ProvenanceOutput,
    SearchDeliveryKnowledgeInput,
    SearchDeliveryKnowledgeOutput,
    SearchResultItemOutput,
)
from chat.models import Conversation
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO

pytestmark = pytest.mark.django_db


@pytest.fixture
def conversation(project, user):
    return Conversation.objects.create(space=project, title="交付知识测试", created_by=user)


def test_schema_search_input_requires_query() -> None:
    with pytest.raises(ValidationError):
        SearchDeliveryKnowledgeInput.model_validate({"query": ""})


def test_schema_search_output_provenance_nested() -> None:
    out = SearchDeliveryKnowledgeOutput(
        query="q",
        results=[
            SearchResultItemOutput(
                entity_id=uuid.uuid4(),
                kind="work_item",
                title="t",
                version=1,
                score=0.9,
                provenance=ProvenanceOutput(feishu_url="https://x"),
            )
        ],
        total=1,
    )
    assert out.results[0].provenance.feishu_url == "https://x"


def test_schema_as_of_optional() -> None:
    inp = SearchDeliveryKnowledgeInput.model_validate({"query": "q"})
    assert inp.as_of is None


@pytest.mark.asyncio
async def test_search_mock_service(conversation, user) -> None:
    hit = SearchResultDTO(
        score=0.9,
        vector_score=0.9,
        recency_score=0.5,
        entity=EntityMetadata(
            entity_id=uuid.uuid4(),
            entity_kind="work_item",
            version=1,
            title="历史",
            valid_at=None,
            invalid_at=None,
            source_kind="feishu_work_item",
            source_id="1",
            origin="feishu",
            event_time=None,
            space_id=None,
            repository_id=None,
            provenance=ProvenanceLinks(),
        ),
    )
    with (
        patch(
            "agents.tools.delivery_knowledge_tools._resolve_conversation_user",
            new=AsyncMock(return_value=user),
        ),
        patch(
            "agents.tools.delivery_knowledge_tools._service.search_similar",
            new=AsyncMock(return_value=[hit]),
        ),
    ):
        result = await search_delivery_knowledge(
            query="登录", conversation_id=str(conversation.id)
        )
    assert result.success is True
    assert result.output["total"] == 1


@pytest.mark.asyncio
async def test_search_no_user_fail_closed() -> None:
    result = await search_delivery_knowledge(query="q", conversation_id="")
    assert result.success is False


@pytest.mark.asyncio
async def test_search_invalid_as_of(conversation, user) -> None:
    with patch(
        "agents.tools.delivery_knowledge_tools._resolve_conversation_user",
        new=AsyncMock(return_value=user),
    ):
        result = await search_delivery_knowledge(
            query="q", as_of="invalid", conversation_id=str(conversation.id)
        )
    assert result.success is False
    assert "as_of" in (result.error or "")


def test_tool_registry_has_search() -> None:
    from agents.tools import delivery_knowledge_tools  # noqa: F401

    assert ToolRegistry.get_tool("search_delivery_knowledge") is not None


def test_build_langchain_tools_search() -> None:
    from agents.tools import delivery_knowledge_tools  # noqa: F401

    tools = build_langchain_tools(
        ["search_delivery_knowledge"],
        injected_values={"conversation_id": "c1"},
    )
    assert len(tools) == 1


@pytest.mark.asyncio
async def test_search_cross_project_empty(conversation, other_user, project) -> None:
    with (
        patch(
            "agents.tools.delivery_knowledge_tools._resolve_conversation_user",
            new=AsyncMock(return_value=other_user),
        ),
        patch(
            "agents.tools.delivery_knowledge_tools._service.search_similar",
            new=AsyncMock(return_value=[]),
        ) as mock_search,
    ):
        result = await search_delivery_knowledge(
            query="q",
            project_ids=[str(project.id)],
            conversation_id=str(conversation.id),
        )
    assert result.success is True
    assert result.output["results"] == []
    mock_search.assert_awaited_once()

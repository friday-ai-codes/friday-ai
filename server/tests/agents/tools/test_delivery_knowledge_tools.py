"""delivery knowledge chat tools 测试（Phase 16-02）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from agents.tools.delivery_knowledge_tools import (
    get_entity_timeline,
    get_related_entities,
    search_delivery_knowledge,
)
from agents.tools.langchain_adapter import build_langchain_tools
from agents.tools.registry import ToolRegistry
from agents.tools.schemas.delivery_knowledge import SearchDeliveryKnowledgeInput
from chat.models import Conversation
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO

pytestmark = pytest.mark.django_db


@pytest.fixture
def conversation(project, user):
    return Conversation.objects.create(space=project, title="交付知识测试", created_by=user)


def test_schema_search_input_requires_query() -> None:
    with pytest.raises(ValidationError):
        SearchDeliveryKnowledgeInput.model_validate({"query": ""})


def test_schema_as_of_optional() -> None:
    inp = SearchDeliveryKnowledgeInput.model_validate({"query": "q"})
    assert inp.as_of is None


class TestRuntimeInputValidation:
    """入参边界必须在 tool 运行时生效，而不是只写在 JSON Schema 声明里。

    这三个工具的参数由 LLM 生成。接入 schema 前它们只做了 UUID / as_of 的手工
    校验，top_k、max_hops、direction 一路裸传到检索服务与图遍历——LLM 传
    max_hops=99 就真的按 99 跳走。

    与本文件既有异步用例一致：patch 掉 `_resolve_conversation_user`，避免异步
    上下文直读 DB 触发 SQLite 表锁。
    """

    @staticmethod
    def _patch_user(user):
        return patch(
            "agents.tools.delivery_knowledge_tools._resolve_conversation_user",
            new=AsyncMock(return_value=user),
        )

    @pytest.mark.asyncio
    async def test_search_rejects_top_k_over_upper_bound(self, user) -> None:
        with self._patch_user(user):
            result = await search_delivery_knowledge(query="q", top_k=10_000, conversation_id="c")
        assert result.success is False
        assert "top_k" in result.error

    @pytest.mark.asyncio
    async def test_search_rejects_empty_query(self, user) -> None:
        with self._patch_user(user):
            result = await search_delivery_knowledge(query="", conversation_id="c")
        assert result.success is False
        assert "query" in result.error

    @pytest.mark.asyncio
    async def test_related_rejects_max_hops_over_upper_bound(self, user) -> None:
        with self._patch_user(user):
            result = await get_related_entities(
                entity_id=str(uuid.uuid4()), max_hops=99, conversation_id="c"
            )
        assert result.success is False
        assert "max_hops" in result.error

    @pytest.mark.asyncio
    async def test_related_rejects_unknown_direction(self, user) -> None:
        with self._patch_user(user):
            result = await get_related_entities(
                entity_id=str(uuid.uuid4()), direction="sideways", conversation_id="c"
            )
        assert result.success is False
        assert "direction" in result.error

    @pytest.mark.asyncio
    async def test_timeline_rejects_bad_entity_id(self, user) -> None:
        with self._patch_user(user):
            result = await get_entity_timeline(entity_id="not-a-uuid", conversation_id="c")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_valid_bounds_still_pass_through(self, user) -> None:
        """边界内的调用不能被误伤——校验只收窄非法值，不改变既有成功路径。"""
        with (
            self._patch_user(user),
            patch(
                "agents.tools.delivery_knowledge_tools._service.search_similar",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await search_delivery_knowledge(query="q", top_k=20, conversation_id="c")
        assert result.success is True


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

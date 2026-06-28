"""delivery_knowledge_search 节点测试（Phase 16-03）。

注：原 ``ai_plan_generation`` 节点（``AIPlanGenerationNode``）已随底盘重构删除，相关
注入相似历史的 hook 测试同步移除；本文件聚焦 DeliveryKnowledgeSearchNode 检索节点。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO
from workflows.nodes.ai.delivery_knowledge_search import DeliveryKnowledgeSearchNode
from workflows.nodes.base import ExecutionContext

pytestmark = pytest.mark.django_db


def _ctx(**kwargs: Any) -> ExecutionContext:
    defaults = {
        "execution_id": "exec-1",
        "node_id": "n1",
        "node_config": {},
        "input_data": {},
        "workflow_context": {},
        "previous_outputs": {},
    }
    defaults.update(kwargs)
    return ExecutionContext(**defaults)


def _hit() -> SearchResultDTO:
    return SearchResultDTO(
        score=0.9,
        vector_score=0.9,
        recency_score=0.5,
        entity=EntityMetadata(
            entity_id=uuid.uuid4(),
            entity_kind="work_item",
            version=1,
            title="历史需求",
            valid_at=None,
            invalid_at=None,
            source_kind="feishu_work_item",
            source_id="1",
            origin="feishu",
            event_time=None,
            space_id="p1",
            repository_id=None,
            provenance=ProvenanceLinks(feishu_url="https://x"),
        ),
    )


@pytest.mark.asyncio
async def test_delivery_node_search_success() -> None:
    node = DeliveryKnowledgeSearchNode()
    mock_user = MagicMock()
    with (
        patch(
            "workflows.nodes.ai.delivery_knowledge_search._get_workflow_user",
            new=AsyncMock(return_value=mock_user),
        ),
        patch(
            "workflows.nodes.ai.delivery_knowledge_search._service.search_similar",
            new=AsyncMock(return_value=[_hit(), _hit()]),
        ),
    ):
        result = await node.execute(
            _ctx(node_config={"query": "登录优化", "top_k": 5})
        )
    assert result.status == "completed"
    assert result.output["total"] == 2
    assert "相似历史交付" in result.output["formatted_context"]


@pytest.mark.asyncio
async def test_delivery_node_search_exception_degrades() -> None:
    node = DeliveryKnowledgeSearchNode()
    with (
        patch(
            "workflows.nodes.ai.delivery_knowledge_search._get_workflow_user",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "workflows.nodes.ai.delivery_knowledge_search._service.search_similar",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        result = await node.execute(_ctx(node_config={"query": "q"}))
    assert result.status == "completed"
    assert result.output["formatted_context"] == ""


@pytest.mark.asyncio
async def test_delivery_node_as_of_passthrough() -> None:
    node = DeliveryKnowledgeSearchNode()
    mock_search = AsyncMock(return_value=[])
    with (
        patch(
            "workflows.nodes.ai.delivery_knowledge_search._get_workflow_user",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "workflows.nodes.ai.delivery_knowledge_search._service.search_similar",
            new=mock_search,
        ),
    ):
        await node.execute(
            _ctx(
                node_config={
                    "query": "q",
                    "as_of": "2026-05-01T00:00:00+08:00",
                }
            )
        )
    assert mock_search.await_args.kwargs["as_of"] is not None


@pytest.mark.asyncio
async def test_delivery_node_empty_query_failed() -> None:
    node = DeliveryKnowledgeSearchNode()
    result = await node.execute(_ctx(node_config={"query": "  "}))
    assert result.status == "failed"

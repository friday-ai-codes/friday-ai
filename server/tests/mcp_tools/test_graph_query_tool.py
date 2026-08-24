"""Django MCP graph_query 薄壳与 RetrievalTrace。"""

from __future__ import annotations

import pytest

from interactions.models import RetrievalTrace

pytestmark = pytest.mark.django_db


def _result() -> dict:
    return {
        "contract_version": "graph-query-tool/v1",
        "manifest_hash": "a" * 64,
        "response_version": "graph-query/v1",
        "ranking_version": "rrf-v1",
        "scope": {
            "repository_id": "00000000-0000-4000-8000-000000000001",
            "branch_name": "main",
            "commit_sha": "abc",
            "index_key": "sig",
        },
        "partial": False,
        "warnings": [],
        "capabilities": {},
        "symbols": {"matched_count": 1, "returned_count": 1, "items": []},
        "communities": {"matched_count": 0, "returned_count": 0, "items": []},
        "processes": {"matched_count": 1, "returned_count": 1, "items": []},
        "impact": {"status": "not_requested", "summary": None},
        "truncated": False,
        "truncated_reasons": [],
        "continuation_hint": "",
    }


def test_graph_query_mcp_calls_service_and_records_redacted_summary(
    mcp_client, monkeypatch
) -> None:
    client, _plaintext = mcp_client
    captured = {}

    async def fake_query(self, query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return _result()

    monkeypatch.setattr(
        "services.code_graph.query_service.GraphQueryService.query",
        fake_query,
    )
    response = client.post(
        "/api/mcp/tools/graph_query/",
        {
            "repository_id": "00000000-0000-4000-8000-000000000001",
            "query": "订单调用链",
            "branch": "main",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["response_version"] == "graph-query/v1"
    assert captured["query"] == "订单调用链"
    assert captured["user"].is_authenticated
    trace = RetrievalTrace.objects.get(kind=RetrievalTrace.Kind.EDGE)
    assert trace.payload["source"] == "mcp_graph_query"
    assert "query" not in trace.payload


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_chat_graph_query_calls_same_service_and_records_trace(
    project, access_user, monkeypatch
) -> None:
    from agents.tools.graph_query import graph_query
    from chat.models import Conversation

    conversation = await Conversation.objects.acreate(
        space=project,
        title="graph-query-chat",
        created_by=access_user,
    )

    async def fake_query(self, query, **kwargs):
        assert query == "订单调用链"
        assert kwargs["user"].id == access_user.id
        return _result()

    monkeypatch.setattr(
        "services.code_graph.query_service.GraphQueryService.query",
        fake_query,
    )
    tool_result = await graph_query(
        repository_id="00000000-0000-4000-8000-000000000001",
        query="订单调用链",
        conversation_id=str(conversation.id),
    )

    assert tool_result.success is True
    assert tool_result.output["data"]["response_version"] == "graph-query/v1"
    trace = await RetrievalTrace.objects.aget(source="chat")
    assert trace.payload["source"] == "chat_graph_query"
    assert "query" not in trace.payload

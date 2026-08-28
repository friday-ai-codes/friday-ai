"""MCP ``search_session_knowledge`` 仓库优先召回 RED 契约（Phase 144 Wave 0）。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from interactions.models import RetrievalTrace
from knowledge.retrieval_types import EntityMetadata, ProvenanceLinks, SearchResultDTO

pytestmark = pytest.mark.django_db

_URL = "/api/mcp/tools/search_session_knowledge/"
_TRACE_KEYS = {
    "source",
    "repository_id",
    "project_id",
    "source_kind",
    "result_count",
    "scores",
    "top_score",
    "duration_ms",
}
_FORBIDDEN_TRACE_KEYS = {"query", "title", "text", "question", "answer", "essence"}


def _result(repository_id: str, project_id: str | None = None) -> SearchResultDTO:
    return SearchResultDTO(
        score=0.91,
        vector_score=0.9,
        recency_score=0.5,
        entity=EntityMetadata(
            entity_id=uuid.uuid4(),
            entity_kind="document",
            version=1,
            title="会话精华",
            valid_at=None,
            invalid_at=None,
            source_kind="session_capture",
            source_id="capture-1",
            origin="session_capture",
            event_time=None,
            space_id=project_id,
            repository_id=repository_id,
            provenance=ProvenanceLinks(),
        ),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "部署失败"},
        {"repository_id": str(uuid.uuid4())},
        {"repository_id": str(uuid.uuid4()), "query": ""},
        {"repository_id": str(uuid.uuid4()), "query": " \t "},
        {"repository_id": str(uuid.uuid4()), "query": "部署失败", "top_k": 0},
        {"repository_id": str(uuid.uuid4()), "query": "部署失败", "top_k": 21},
    ],
)
def test_invalid_repository_query_or_top_k_returns_400(mcp_client, payload) -> None:
    client, _ = mcp_client

    response = client.post(_URL, payload, format="json")

    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_params"


def test_repository_and_project_are_forwarded_as_and_filters(
    mcp_client,
    repository_in_user_space,
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缺失 helper/路由必须显式 RED，不得用 skip 掩盖。"""
    from knowledge import session_capture_retrieval

    project_id = str(project.id)
    repository = repository_in_user_space
    search = AsyncMock(return_value=[_result(str(repository.id), project_id)])
    monkeypatch.setattr(session_capture_retrieval, "search_session_knowledge", search)
    client, _ = mcp_client

    response = client.post(
        _URL,
        {
            "repository_id": str(repository.id),
            "project_id": project_id,
            "query": "部署失败",
            "top_k": 7,
        },
        format="json",
    )

    assert response.status_code == 200
    kwargs = search.await_args.kwargs
    assert kwargs["repository_id"] == str(repository.id)
    assert kwargs["project_id"] == project_id
    assert kwargs["query"] == "部署失败"
    assert kwargs["top_k"] == 7


def test_unauthorized_repository_is_neutral_empty_result(
    mcp_client,
    repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge import session_capture_retrieval

    search = AsyncMock(side_effect=AssertionError("未授权仓不得进入向量召回"))
    monkeypatch.setattr(session_capture_retrieval, "search_session_knowledge", search)
    client, _ = mcp_client

    response = client.post(
        _URL,
        {"repository_id": str(repository.id), "query": "敏感知识"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["total"] == 0
    search.assert_not_awaited()


def test_empty_results_still_record_scalar_only_trace(
    mcp_client,
    repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge import session_capture_retrieval

    monkeypatch.setattr(
        session_capture_retrieval,
        "search_session_knowledge",
        AsyncMock(return_value=[]),
    )
    client, _ = mcp_client

    response = client.post(
        _URL,
        {"repository_id": str(repository.id), "query": "没有命中的正文"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["results"] == []
    trace = RetrievalTrace.objects.get(
        tool_call__tool_name="search_session_knowledge",
        kind=RetrievalTrace.Kind.CHUNK,
    )
    assert set(trace.payload) == _TRACE_KEYS
    assert not (_FORBIDDEN_TRACE_KEYS & set(trace.payload))
    assert trace.payload["repository_id"] == str(repository.id)
    assert trace.payload["project_id"] == ""
    assert trace.payload["source_kind"] == "session_capture"
    assert trace.payload["result_count"] == 0
    assert trace.payload["scores"] == []
    assert trace.payload["top_score"] == 0
    assert isinstance(trace.payload["duration_ms"], int)


def test_trace_failure_does_not_change_success_response(
    mcp_client,
    repository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge import session_capture_retrieval

    monkeypatch.setattr(
        session_capture_retrieval,
        "search_session_knowledge",
        AsyncMock(return_value=[]),
    )

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("trace database unavailable")

    monkeypatch.setattr(RetrievalTrace.objects, "create", _boom)
    client, _ = mcp_client

    response = client.post(
        _URL,
        {"repository_id": str(repository.id), "query": "仍应成功"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["total"] == 0
    assert response.json()["run_id"]

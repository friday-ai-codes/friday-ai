"""Phase 140：GraphQueryService caller 生命周期与无正文契约。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import networkx as nx
import pytest
import structlog

from common.log_context import bind_request_context, clear_request_context
from services.code_graph.query_service import GraphQueryService


class _GraphService:
    async def get_graph(self, *_args, **_kwargs):
        return SimpleNamespace(
            meta=SimpleNamespace(built_signature="sig-1"),
            graph=nx.MultiDiGraph(),
        )


def _install(monkeypatch, *, graph_error: Exception | None = None) -> None:
    graph_service = _GraphService()
    if graph_error is not None:

        async def failed_graph(*_args, **_kwargs):
            raise graph_error

        graph_service.get_graph = failed_graph

    async def symbol_search(*_args, **_kwargs):
        return SimpleNamespace(
            status="ok",
            error="",
            items=[{"score": 0.9, "payload": {"symbol_id": "s1", "name": "safe"}}],
        )

    async def process_search(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        "services.code_graph.query_service.get_graph_service",
        lambda: graph_service,
    )
    monkeypatch.setattr(
        "services.code_graph.query_service._load_query_facts",
        lambda _repo, _branch: {
            "repository_id": "repo",
            "branch_name": "main",
            "commit_sha": "sha-1",
            "communities": [],
        },
    )
    monkeypatch.setattr(
        "services.code_graph.query_service.search_rag",
        symbol_search,
    )
    monkeypatch.setattr(
        "services.code_graph.query_service.search_process_index",
        process_search,
    )


def _events(captured: list[dict], *names: str) -> list[dict]:
    allowed = set(names)
    return [event for event in captured if event.get("event") in allowed]


@pytest.mark.asyncio
async def test_success_emits_one_attributed_caller_lifecycle(monkeypatch) -> None:
    _install(monkeypatch)
    bind_request_context(
        request_id="req-140",
        trace_id="trace-140",
        source="rest",
        user_id="user-140",
    )
    try:
        with structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars]
        ) as captured:
            await GraphQueryService().query(
                "sentinel-natural-language-query",
                repository_id="repo",
                branch_name="main",
                initiated_by_user_id="user-140",
            )
    finally:
        clear_request_context()

    lifecycle = _events(
        captured,
        "code_graph_query_started",
        "code_graph_query_completed",
        "code_graph_query_failed",
    )
    assert [event["event"] for event in lifecycle] == [
        "code_graph_query_started",
        "code_graph_query_completed",
    ]
    for event in lifecycle:
        assert event["category"] == "caller"
        assert event["component"] == "code_graph"
        assert event["repository_id"] == "repo"
        assert event["branch_name"] == "main"
        assert event["initiated_by_user_id"] == "user-140"
        assert event["request_id"] == "req-140"
        assert event["trace_id"] == "trace-140"
        assert event["source"] == "rest"
    assert "duration_ms" not in lifecycle[0]
    assert lifecycle[1]["duration_ms"] >= 0

    serialized = json.dumps(captured, ensure_ascii=False)
    assert "sentinel-natural-language-query" not in serialized


@pytest.mark.asyncio
async def test_success_emits_symbol_and_process_sampling_summaries(monkeypatch) -> None:
    _install(monkeypatch)
    recorded: list[dict] = []

    class _RecordingLogger:
        def info(self, event, **kwargs):
            recorded.append({"event": event, **kwargs})

        def warning(self, event, **kwargs):
            recorded.append({"event": event, **kwargs})

        def debug(self, event, **kwargs):
            recorded.append({"event": event, **kwargs})

    monkeypatch.setattr("services.code_graph.query_service.logger", _RecordingLogger())
    await GraphQueryService().query("query", repository_id="repo", branch_name="main")

    lane_events = _events(
        recorded,
        "code_graph_query_symbol_lane_completed",
        "code_graph_query_process_lane_completed",
    )
    assert [event["lane"] for event in lane_events] == ["symbol", "process"]
    for event in lane_events:
        assert event["category"] == "sampling"
        assert event["component"] == "code_graph"
        assert event["status"] == "used"
        assert event["returned"] >= 0
        assert event["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_failure_emits_redacted_failed_and_preserves_exception(monkeypatch) -> None:
    token = "sk-" + ("a" * 24)
    original = RuntimeError(f"upstream rejected {token}")
    _install(monkeypatch, graph_error=original)

    with structlog.testing.capture_logs() as captured:
        with pytest.raises(RuntimeError) as raised:
            await GraphQueryService().query(
                "failure-query-sentinel",
                repository_id="repo",
                branch_name="main",
                initiated_by_user_id="actor",
            )

    assert raised.value is original
    lifecycle = _events(
        captured,
        "code_graph_query_started",
        "code_graph_query_completed",
        "code_graph_query_failed",
    )
    assert [event["event"] for event in lifecycle] == [
        "code_graph_query_started",
        "code_graph_query_failed",
    ]
    assert lifecycle[1]["duration_ms"] >= 0
    serialized = json.dumps(captured, ensure_ascii=False)
    assert "failure-query-sentinel" not in serialized
    assert token not in serialized
    assert "***REDACTED***" in serialized


@pytest.mark.asyncio
async def test_blank_query_emits_no_lifecycle_event(monkeypatch) -> None:
    _install(monkeypatch)
    with structlog.testing.capture_logs() as captured:
        with pytest.raises(ValueError, match="不能为空"):
            await GraphQueryService().query("  ", repository_id="repo")
    assert _events(
        captured,
        "code_graph_query_started",
        "code_graph_query_completed",
        "code_graph_query_failed",
    ) == []


@pytest.mark.asyncio
async def test_logger_failure_does_not_change_success_or_partial_schema(monkeypatch) -> None:
    _install(monkeypatch)
    service = GraphQueryService()
    expected = await service.query("baseline", repository_id="repo", branch_name="main")

    def broken_log(*_args, **_kwargs):
        raise RuntimeError("logger unavailable")

    monkeypatch.setattr("services.code_graph.query_service.logger.info", broken_log)
    monkeypatch.setattr("services.code_graph.query_service.logger.debug", broken_log)
    actual = await service.query("baseline", repository_id="repo", branch_name="main")

    assert actual == expected
    assert actual["partial"] is False
    assert actual["warnings"] == []
    assert actual["capabilities"] == expected["capabilities"]


@pytest.mark.asyncio
async def test_logger_failure_preserves_original_business_exception(monkeypatch) -> None:
    original = RuntimeError("business failure")
    _install(monkeypatch, graph_error=original)

    def broken_log(*_args, **_kwargs):
        raise RuntimeError("logger unavailable")

    monkeypatch.setattr("services.code_graph.query_service.logger.info", broken_log)
    monkeypatch.setattr("services.code_graph.query_service.logger.warning", broken_log)
    with pytest.raises(RuntimeError) as raised:
        await GraphQueryService().query("query", repository_id="repo")
    assert raised.value is original

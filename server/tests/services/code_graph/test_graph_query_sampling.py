"""Phase 140：resolver、Process、lane 与 impact sampling 行为契约。"""

from __future__ import annotations

from types import SimpleNamespace

import networkx as nx
import pytest

from codegraph.resolver.base import ResolveResult
from codegraph.resolver.symbol_resolver import SymbolResolver
from services.code_graph.impact import analyze_impact
from services.code_graph.process_index import search_process_index


class _RecordingLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def debug(self, event, **kwargs):
        self.events.append({"event": event, **kwargs})

    def info(self, event, **kwargs):
        self.events.append({"event": event, **kwargs})

    def warning(self, event, **kwargs):
        self.events.append({"event": event, **kwargs})


def test_resolver_backfill_emits_one_grouped_sampling_summary(monkeypatch) -> None:
    edges = [
        SimpleNamespace(
            id=index,
            callee_symbol_id=None,
            callee_file=None,
            is_cross_file=False,
        )
        for index in range(3)
    ]
    manager = SimpleNamespace(
        filter=lambda **_kwargs: edges,
        bulk_update=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("codegraph.models.CallEdge.objects", manager)
    resolver = SymbolResolver(SimpleNamespace(), {}, {})
    outcomes = iter(
        [
            ResolveResult(
                "symbol-1",
                "target.py",
                True,
                status="resolved",
                language="python",
                call_shape="member",
            ),
            ResolveResult(
                None,
                None,
                False,
                status="ambiguous",
                language="python",
                call_shape="member",
            ),
            ResolveResult(
                None,
                None,
                False,
                status="unresolved",
                language="typescript",
                call_shape="receiver",
            ),
        ]
    )
    monkeypatch.setattr(resolver, "resolve_call", lambda _edge: next(outcomes))
    recording = _RecordingLogger()
    monkeypatch.setattr("codegraph.resolver.symbol_resolver.logger", recording)

    resolver.backfill("repo", branch_name="main", initiated_by_user_id="42")

    summaries = [
        event
        for event in recording.events
        if event["event"] == "code_graph_symbol_resolve_batch_completed"
    ]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["category"] == "sampling"
    assert summary["component"] == "codegraph"
    assert summary["initiated_by_user_id"] == "42"
    assert summary["duration_ms"] >= 0
    assert summary["cells"] == [
        {
            "language": "python",
            "call_shape": "member",
            "resolved": 1,
            "ambiguous": 1,
            "unresolved": 0,
        },
        {
            "language": "typescript",
            "call_shape": "receiver",
            "resolved": 0,
            "ambiguous": 0,
            "unresolved": 1,
        },
    ]


@pytest.mark.asyncio
async def test_process_search_emits_one_sampling_summary_without_query(
    monkeypatch,
) -> None:
    async def fake_embed(_query):
        return SimpleNamespace(primary=[0.1, 0.2])

    monkeypatch.setattr("services.query_embedding.embed_query", fake_embed)
    monkeypatch.setattr(
        "services.sparse_encoder.SparseEncoderService.encode",
        lambda _query: {"indices": [1], "values": [1.0]},
    )
    monkeypatch.setattr(
        "services.qdrant_service.QdrantService.hybrid_search_by_name",
        lambda *_args, **_kwargs: [{"score": 0.9, "payload": {"process_key": "p1"}}],
    )
    recording = _RecordingLogger()
    monkeypatch.setattr("services.code_graph.process_index.logger", recording)

    rows = await search_process_index(
        "sensitive-query",
        repository_id="repo",
        branch_name="main",
        commit_sha="sha-1",
    )

    summaries = [
        event
        for event in recording.events
        if event["event"] == "code_graph_process_index_search_completed"
    ]
    assert len(summaries) == 1
    assert summaries[0]["category"] == "sampling"
    assert summaries[0]["component"] == "code_graph"
    assert summaries[0]["status"] == "used"
    assert summaries[0]["returned"] == len(rows) == 1
    assert summaries[0]["duration_ms"] >= 0
    assert "sensitive-query" not in repr(recording.events)


def test_impact_emits_one_sampling_summary_without_symbol_content(monkeypatch) -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("seed", name="secret-seed", file_path="secret.py")
    recording = _RecordingLogger()
    monkeypatch.setattr("services.code_graph.impact.logger", recording)

    result = analyze_impact(graph, "seed")

    assert result["summary"]["returned"] == 0
    assert recording.events == [
        {
            "event": "code_graph_impact_analyzed",
            "component": "code_graph",
            "category": "sampling",
            "depth": 3,
            "returned": 0,
            "total_found": 0,
            "duration_ms": recording.events[0]["duration_ms"],
        }
    ]
    assert recording.events[0]["duration_ms"] >= 0
    assert "secret-seed" not in repr(recording.events)
    assert "secret.py" not in repr(recording.events)

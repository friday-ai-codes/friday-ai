"""Phase 137：GraphQueryService 统一融合契约。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.code_graph.query_service import GraphQueryService


class _GraphService:
    def __init__(self) -> None:
        self.calls = 0

    async def get_graph(self, *_args, **_kwargs):
        self.calls += 1
        return SimpleNamespace(meta=SimpleNamespace(built_signature="sig-1"))


def _facts(*, community_sha: str = "sha-1") -> dict:
    return {
        "repository_id": "repo",
        "branch_name": "main",
        "commit_sha": "sha-1",
        "communities": [
            {
                "community_key": "c1",
                "summary": "订单域",
                "members": [{"symbol_id": "s1"}],
                "top_files": ["orders/api.py"],
                "built_at_sha": community_sha,
            }
        ],
    }


async def _symbol_search(*_args, **_kwargs):
    return SimpleNamespace(
        status="ok",
        error="",
        items=[
            {
                "score": 0.9,
                "payload": {
                    "symbol_id": "s1",
                    "name": "create_order",
                    "content": "large source body",
                },
            },
            {
                "score": 0.8,
                "payload": {"symbol_id": "s2", "name": "validate_order"},
            },
        ],
    )


async def _process_search(*_args, **_kwargs):
    return [
        {
            "process_key": "POST:/orders",
            "name": "创建订单流程",
            "content": "process body",
            "steps": [
                {
                    "symbol_id": "s1",
                    "file_path": "orders/api.py",
                    "start_line": 10,
                    "end_line": 20,
                }
            ],
            "score": 0.9,
            "lane": "hybrid",
        }
    ]


def _install(monkeypatch, graph_service: _GraphService, *, facts=None) -> None:
    monkeypatch.setattr(
        "services.code_graph.query_service.get_graph_service",
        lambda: graph_service,
    )
    monkeypatch.setattr(
        "services.code_graph.query_service._load_query_facts",
        lambda _repo, _branch: facts or _facts(),
    )
    monkeypatch.setattr(
        "services.code_graph.query_service.search_rag",
        _symbol_search,
    )
    monkeypatch.setattr(
        "services.code_graph.query_service.search_process_index",
        _process_search,
    )


@pytest.mark.asyncio
async def test_blank_query_rejected_before_graph_or_retrieval(monkeypatch) -> None:
    graph_service = _GraphService()
    _install(monkeypatch, graph_service)
    with pytest.raises(ValueError, match="不能为空"):
        await GraphQueryService().query(
            "   ",
            repository_id="repo",
            branch_name="main",
        )
    assert graph_service.calls == 0


@pytest.mark.asyncio
async def test_deterministic_fusion_keeps_process_membership(monkeypatch) -> None:
    graph_service = _GraphService()
    _install(monkeypatch, graph_service)
    service = GraphQueryService()

    first = await service.query("创建订单", repository_id="repo", branch_name="main")
    second = await service.query("创建订单", repository_id="repo", branch_name="main")

    assert first == second
    assert first["scope"]["commit_sha"] == "sha-1"
    assert first["symbols"]["items"][0]["symbol_id"] == "s1"
    assert first["symbols"]["items"][0]["process_memberships"][0]["process_key"] == (
        "POST:/orders"
    )
    ledger = first["symbols"]["items"][0]["ledger"]
    assert set(ledger) == {
        "lane",
        "lane_rank",
        "lane_contribution",
        "community_contribution",
        "final_score",
        "ranking_version",
    }
    assert first["impact"]["status"] == "not_requested"


@pytest.mark.asyncio
async def test_mixed_community_watermark_degrades_without_mixing(monkeypatch) -> None:
    graph_service = _GraphService()
    _install(monkeypatch, graph_service, facts=_facts(community_sha="sha-old"))

    result = await GraphQueryService().query(
        "创建订单",
        repository_id="repo",
        branch_name="main",
    )

    assert result["partial"] is True
    assert result["communities"]["items"] == []
    assert "community_watermark_mismatch" in result["warnings"]
    assert result["capabilities"]["community"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_budget_preserves_schema_and_counts(monkeypatch) -> None:
    graph_service = _GraphService()
    _install(monkeypatch, graph_service)

    result = await GraphQueryService().query(
        "创建订单",
        repository_id="repo",
        branch_name="main",
        max_symbols=1,
        max_processes=1,
        budget_chars=1,
    )

    assert result["symbols"]["matched_count"] == 2
    assert result["symbols"]["returned_count"] == 1
    assert result["truncated"] is True
    assert set(result["truncated_reasons"]) == {"symbol_limit", "content_budget"}
    assert "content" not in result["symbols"]["items"][0]["payload"]
    assert result["scope"]["index_key"] == "sig-1"


@pytest.mark.asyncio
async def test_process_lane_failure_is_schema_preserving_partial(monkeypatch) -> None:
    graph_service = _GraphService()
    _install(monkeypatch, graph_service)

    async def failed_process(*_args, **_kwargs):
        raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(
        "services.code_graph.query_service.search_process_index",
        failed_process,
    )
    result = await GraphQueryService().query(
        "创建订单",
        repository_id="repo",
        branch_name="main",
    )

    assert result["partial"] is True
    assert result["processes"] == {
        "matched_count": 0,
        "returned_count": 0,
        "items": [],
    }
    assert result["capabilities"]["process_enrichment"]["status"] == "degraded"

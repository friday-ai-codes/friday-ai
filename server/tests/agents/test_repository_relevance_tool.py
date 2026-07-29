"""``analyze_repository_relevance`` 工具单测。

测试范围（≥ 12 条）：

1. **注册 / schema snapshot**
   - tool 已注册 + ToolCategory.RETRIEVAL
   - input schema required 字段 == [query, space_id, conversation_id]
   - JSON Schema 与 fixture 一致（snapshot 守门）

2. **错误路径（success=False）**
   - space_id 不存在
   - conversation_id 不存在
   - 空间下无 indexed repository
   - HybridSearchService raise → 不抛异常

3. **happy path / level 三档**
   - 三个 score 分别 high/medium/low
   - 按 score 倒序 + 长度 ≤ top_k
   - selected_by_ai 按 threshold 切分
   - selected_by_ai == selected_by_user_final（初次写入）

4. **evidence 三段 fallback**
   - 有 file_path 命中
   - 无 file_path 但有 CrossRepoApiCall
   - 都无 → score fallback

5. **trace 写入**
   - 一行 chat_tool trace + agent_session=None
   - trace_id 出现在 ToolResult.output['data']

6. **chat_runner 集成**
   - _INDEXED_TOOL_NAMES 含 analyze_repository_relevance
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.tools.base import ToolCategory
from agents.tools.registry import ToolRegistry
from agents.tools.repository_relevance import (
    _analyze_relevance_core,
    _score_to_level,
    analyze_repository_relevance,
)
from agents.tools.schemas.repository_relevance import RepositoryRelevanceInput
from chat.models import Conversation, RepositoryRoutingTrace
from projects.models import Space
from repositories.models import Repository
from services.retrieval.types import LayerSnapshot, RagSearchResult


pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_with_repos(db):
    project = Space.objects.create(
        name=f"relev-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"k-{uuid.uuid4().hex[:6]}",
    )
    repos = []
    for i in range(3):
        repo = Repository.objects.create(
            name=f"repo-{i}",
            git_url=f"https://github.com/test/repo-{i}.git",
            git_platform="github",
            default_branch="main",
            index_status="indexed",
        )
        project.repositories.add(repo)
        repos.append(repo)
    return project, repos


@pytest.fixture
def conversation(db, project_with_repos):
    project, _ = project_with_repos
    return Conversation.objects.create(space=project, title="relev-conv")


def _make_rag_result(*, items_by_repo: dict[str, list[dict[str, Any]]]) -> RagSearchResult:
    """构造一个 L3 命中分布在多 repo 的 RagSearchResult。"""
    items: list[dict[str, Any]] = []
    for rid, hits in items_by_repo.items():
        for h in hits:
            items.append({**h, "repository_id": rid})
    layer = LayerSnapshot(
        layer="L3",
        status="ok",
        result_count=len(items),
        items=items,
    )
    return RagSearchResult(
        query="q",
        repository_ids=list(items_by_repo.keys()),
        layers=[layer],
        final_context="",
        total_tokens=0,
    )


def _patch_hybrid_search(monkeypatch, return_value: RagSearchResult | Exception) -> AsyncMock:
    mock = AsyncMock()
    if isinstance(return_value, Exception):
        mock.search = AsyncMock(side_effect=return_value)
    else:
        mock.search = AsyncMock(return_value=return_value)
    monkeypatch.setattr(
        "agents.tools.repository_relevance.HybridSearchService",
        lambda _provider: mock,
    )
    return mock


# ---------------------------------------------------------------------------
# 1. 注册 / schema snapshot
# ---------------------------------------------------------------------------


async def test_tool_registered():
    tool = ToolRegistry.get_tool("analyze_repository_relevance")
    assert tool is not None
    assert tool.category == ToolCategory.RETRIEVAL


async def test_input_schema_required_fields():
    tool = ToolRegistry.get_tool("analyze_repository_relevance")
    assert tool is not None
    assert sorted(tool.parameters["required"]) == sorted(
        ["query", "space_id", "conversation_id"]
    )


async def test_input_schema_snapshot():
    fixture_path = (
        Path(__file__).parent / "fixtures" / "repository_relevance_input_schema.json"
    )
    assert fixture_path.exists()
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    actual = RepositoryRelevanceInput.model_json_schema()
    assert actual == expected, (
        f"Schema drift detected. Regenerate fixture if intentional:\n"
        f"diff: expected={expected}\nactual={actual}"
    )


# ---------------------------------------------------------------------------
# 2. 错误路径
# ---------------------------------------------------------------------------


async def test_space_not_found(conversation, monkeypatch):
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo={}))
    result = await analyze_repository_relevance(
        query="x",
        space_id=str(uuid.uuid4()),
        conversation_id=str(conversation.id),
    )
    assert result.success is False
    assert "Space not found" in (result.error or "")


async def test_conversation_not_found(project_with_repos, monkeypatch):
    project, _ = project_with_repos
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo={}))
    result = await analyze_repository_relevance(
        query="x",
        space_id=str(project.id),
        conversation_id=str(uuid.uuid4()),
    )
    assert result.success is False
    assert "Conversation not found" in (result.error or "")


async def test_no_indexed_repositories(monkeypatch):
    project = await Space.objects.acreate(
        name=f"empty-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"k-{uuid.uuid4().hex[:6]}",
    )
    conv = await Conversation.objects.acreate(space=project, title="x")
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo={}))
    result = await analyze_repository_relevance(
        query="x",
        space_id=str(project.id),
        conversation_id=str(conv.id),
    )
    assert result.success is False
    assert "No indexed repositories" in (result.error or "")


async def test_hybrid_service_raises_is_swallowed(
    project_with_repos, conversation, monkeypatch
):
    project, _ = project_with_repos
    _patch_hybrid_search(monkeypatch, RuntimeError("qdrant down"))
    result = await analyze_repository_relevance(
        query="x",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is False
    assert "HybridSearchService failed" in (result.error or "")


# ---------------------------------------------------------------------------
# 3. happy path / level 三档
# ---------------------------------------------------------------------------


async def test_happy_returns_three_candidates_sorted_with_level_buckets_and_thresholds(
    project_with_repos, conversation, monkeypatch
):
    project, repos = project_with_repos
    items_by_repo = {
        str(repos[0].id): [
            {"score": 0.92, "payload": {"file_path": "a.py"}},
        ],
        str(repos[1].id): [
            {"score": 0.55, "payload": {"file_path": "b.py"}},
        ],
        str(repos[2].id): [
            {"score": 0.20, "payload": {"file_path": "c.py"}},
        ],
    }
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo=items_by_repo))

    result = await analyze_repository_relevance(
        query="cross",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
        top_k=5,
        threshold=0.5,
    )
    assert result.success is True
    cands = result.output["data"]["candidates"]
    assert len(cands) == 3
    # 倒序：0.92 → 0.55 → 0.20
    assert cands[0]["score"] >= cands[1]["score"] >= cands[2]["score"]
    assert cands[0]["level"] == "high"
    assert cands[1]["level"] == "medium"
    assert cands[2]["level"] == "low"
    # 阈值切分
    assert cands[0]["selected_by_ai"] is True
    assert cands[1]["selected_by_ai"] is True
    assert cands[2]["selected_by_ai"] is False
    # 首次写入 user_final == ai
    for c in cands:
        assert c["selected_by_ai"] == c["selected_by_user_final"]


def test_score_to_level_thresholds():
    assert _score_to_level(0.91) == "high"
    assert _score_to_level(0.70) == "high"
    assert _score_to_level(0.55) == "medium"
    assert _score_to_level(0.40) == "medium"
    assert _score_to_level(0.39) == "low"
    assert _score_to_level(0.0) == "low"


# ---------------------------------------------------------------------------
# 4. evidence 三段 fallback
# ---------------------------------------------------------------------------


async def test_evidence_uses_filenames_when_chunks_match(
    project_with_repos, conversation, monkeypatch
):
    project, repos = project_with_repos
    items_by_repo = {
        str(repos[0].id): [
            {"score": 0.9, "payload": {"file_path": "src/a.py"}},
            {"score": 0.8, "payload": {"file_path": "src/b.py"}},
        ],
    }
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo=items_by_repo))
    result = await analyze_repository_relevance(
        query="x",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True
    cand = result.output["data"]["candidates"][0]
    assert "命中" in cand["evidence"] or "相关文件" in cand["evidence"]


async def test_evidence_falls_back_to_score_when_no_signals(
    project_with_repos, conversation, monkeypatch
):
    project, repos = project_with_repos
    items_by_repo = {
        str(repos[0].id): [
            {"score": 0.6, "payload": {}},  # 无 file_path
        ],
    }
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo=items_by_repo))
    result = await analyze_repository_relevance(
        query="x",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True
    cand = result.output["data"]["candidates"][0]
    assert "语义相关度" in cand["evidence"]


# ---------------------------------------------------------------------------
# 5. trace 写入（chat_tool 路径）
# ---------------------------------------------------------------------------


async def test_trace_persisted_with_chat_tool_trigger(
    project_with_repos, conversation, monkeypatch
):
    project, repos = project_with_repos
    items_by_repo = {
        str(repos[0].id): [{"score": 0.8, "payload": {"file_path": "x.py"}}],
    }
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo=items_by_repo))

    result = await analyze_repository_relevance(
        query="trace query",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
        threshold=0.5,
    )
    assert result.success is True

    trace = await RepositoryRoutingTrace.objects.filter(
        conversation_id=conversation.id
    ).afirst()
    assert trace is not None
    assert trace.triggered_by == RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL
    assert trace.threshold == 0.5
    assert trace.query == "trace query"
    assert trace.agent_session_id is None
    assert len(trace.candidates) == 1
    # trace_id 透传
    assert result.output["data"]["trace_id"] == str(trace.id)
    assert result.output["metadata"]["trace_id"] == str(trace.id)


async def test_deep_analysis_path_writes_trace_with_session(
    project_with_repos, conversation, monkeypatch
):
    """覆盖 plan 复用路径：deep_analysis_completion + agent_session_id。"""
    from agents.models import AgentSession

    project, repos = project_with_repos
    items_by_repo = {
        str(repos[0].id): [{"score": 0.85, "payload": {"file_path": "x.py"}}],
    }
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo=items_by_repo))

    agent_session = await AgentSession.objects.acreate(
        session_id=f"as-{uuid.uuid4().hex[:8]}"
    )

    candidates, trace_id = await _analyze_relevance_core(
        query="deep",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
        triggered_by=RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION,
        agent_session_id=str(agent_session.id),
    )
    assert len(candidates) >= 1
    trace = await RepositoryRoutingTrace.objects.aget(id=trace_id)
    assert (
        trace.triggered_by
        == RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION
    )
    assert trace.agent_session_id == agent_session.id


# ---------------------------------------------------------------------------
# 6. chat_runner 集成
# ---------------------------------------------------------------------------


def test_chat_runner_includes_tool_in_indexed_set():
    from agents.chat_runner import _INDEXED_TOOL_NAMES

    assert "analyze_repository_relevance" in _INDEXED_TOOL_NAMES


# ---------------------------------------------------------------------------
# 7. breakdown 透传（ROUTE-07 / 105-06）
# ---------------------------------------------------------------------------


def test_candidate_breakdown_defaults_to_empty_dict():
    """新字段带默认值——legacy 构造 / 历史 trace 反序列化零破坏。"""
    from agents.tools.schemas.repository_relevance import RepositoryRelevanceCandidate

    cand = RepositoryRelevanceCandidate(
        repository_id="r",
        repository_name="n",
        score=0.5,
        level="low",
        evidence="",
        selected_by_ai=False,
        selected_by_user_final=False,
    )
    assert cand.breakdown == {}


def _make_v2_result(repos):
    """构造 v2 fake：候选携带 breakdown 且 Σ贡献 == score。"""
    from codegraph.services.repo_router_v2 import (
        RepoRouteCandidateV2,
        RepoRouteResultV2,
    )

    candidates = [
        RepoRouteCandidateV2(
            repo_id=str(repos[0].id),
            repo_name=repos[0].name,
            score=0.92,
            confidence="high",
            reasoning="树推理命中",
            matched_node_paths=["auth/登录"],
            breakdown={"text": 0.5, "breadth": 0.25, "activity": 0.17},
        ),
        RepoRouteCandidateV2(
            repo_id=str(repos[1].id),
            repo_name=repos[1].name,
            score=0.55,
            confidence="medium",
            reasoning="部分命中",
            breakdown={"text": 0.3, "breadth": 0.15, "activity": 0.1},
        ),
        RepoRouteCandidateV2(
            repo_id=str(repos[2].id),
            repo_name=repos[2].name,
            score=0.3,
            confidence="medium",
            reasoning="弱命中",
            breakdown={"text": 0.2, "breadth": 0.1},
        ),
    ]
    return RepoRouteResultV2(
        candidates=candidates,
        router_version="v2",
        auto_selected=True,
    )


async def test_v2_path_trace_candidates_carry_breakdown_sum_equals_score(
    project_with_repos, conversation, monkeypatch
):
    """v2 路径：trace candidates JSON 含非空 breakdown 且 Σ值 ≈ score（1e-6）；
    selected = high or (medium and score >= threshold) 行为断言。"""
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    monkeypatch.setattr(
        RepoRouterV2, "route", AsyncMock(return_value=_make_v2_result(repos))
    )

    result = await analyze_repository_relevance(
        query="v2 breakdown",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
        threshold=0.5,
    )
    assert result.success is True

    trace = await RepositoryRoutingTrace.objects.filter(
        conversation_id=conversation.id
    ).afirst()
    assert trace is not None
    assert trace.router_version == "v2"
    assert len(trace.candidates) == 3
    for cand in trace.candidates:
        assert cand["breakdown"], "v2 候选 breakdown 必须非空"
        assert abs(sum(cand["breakdown"].values()) - cand["score"]) < 1e-6

    # selected = high or (medium and score >= threshold)：
    # margin 达标（confidence=high）→ selected=True（编排解锁行为）
    by_score = sorted(trace.candidates, key=lambda c: c["score"], reverse=True)
    assert by_score[0]["level"] == "high"
    assert by_score[0]["selected_by_ai"] is True
    # medium + score >= threshold → True
    assert by_score[1]["selected_by_ai"] is True
    # medium + score < threshold → False
    assert by_score[2]["selected_by_ai"] is False


async def test_legacy_path_trace_candidates_breakdown_empty(
    project_with_repos, conversation, monkeypatch
):
    """legacy 聚合路径不赋值 breakdown → trace candidates 里为空 dict。"""
    project, repos = project_with_repos
    items_by_repo = {
        str(repos[0].id): [{"score": 0.8, "payload": {"file_path": "x.py"}}],
    }
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo=items_by_repo))

    result = await analyze_repository_relevance(
        query="legacy breakdown",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True

    trace = await RepositoryRoutingTrace.objects.filter(
        conversation_id=conversation.id
    ).afirst()
    assert trace is not None
    assert len(trace.candidates) == 1
    assert trace.candidates[0]["breakdown"] == {}

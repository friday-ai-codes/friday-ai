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
from unittest.mock import AsyncMock

import pytest

from agents.tools.base import ToolCategory
from agents.tools.registry import ToolRegistry
from agents.tools.repository_relevance import (
    _analyze_relevance_core,
    _score_to_level,
    analyze_repository_relevance,
)
from agents.tools.schemas.repository_relevance import (
    RepositoryRelevanceInput,
    RepositoryRelevanceOutput,
)
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


def test_output_schema_snapshot():
    """输出 schema snapshot —— **与前端契约测试共用同一份 fixture**（BL-02 的契约锚）。

    前端 ``routing.test.ts`` 从同一个文件取键名来构造 tool-output payload。这样后端
    一旦把某个结果级字段从输出模型里拿掉，后端 snapshot 与前端解析用例会同时打红；
    在此之前前端是**手写 payload 伪造**这四键的，而后端从不产生那个形状——用例全绿
    却掩盖了契约缺口（假阳性守护）。
    """
    fixture_path = (
        Path(__file__).parent / "fixtures" / "repository_relevance_output_schema.json"
    )
    assert fixture_path.exists()
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    actual = RepositoryRelevanceOutput.model_json_schema()
    assert actual == expected, (
        f"Output schema drift detected. Regenerate fixture if intentional:\n"
        f"diff: expected={expected}\nactual={actual}"
    )


def test_output_schema_carries_result_level_facts():
    """输出模型必须含四个结果级事实，且全部带默认值（additive，legacy 形状不变）。"""
    props = RepositoryRelevanceOutput.model_json_schema()["properties"]
    assert {"router_version", "degraded", "degrade_reason", "block_order"} <= set(props)
    # 带默认值 → 不进 required，历史/legacy 构造零破坏
    required = set(RepositoryRelevanceOutput.model_json_schema().get("required", []))
    assert not (
        {"router_version", "degraded", "degrade_reason", "block_order"} & required
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

    analysis = await _analyze_relevance_core(
        query="deep",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
        triggered_by=RepositoryRoutingTrace.TriggeredBy.DEEP_ANALYSIS_COMPLETION,
        agent_session_id=str(agent_session.id),
    )
    assert len(analysis.candidates) >= 1
    trace = await RepositoryRoutingTrace.objects.aget(id=analysis.trace_id)
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


# ---------------------------------------------------------------------------
# 9. 分组事实透传（ROUTE-01/02，107-07 Task 3）
# ---------------------------------------------------------------------------


def _bare_candidate():
    """按 105 期字段集构造 pydantic 候选（新字段必须全部有默认值）。"""
    from agents.tools.schemas.repository_relevance import RepositoryRelevanceCandidate

    return RepositoryRelevanceCandidate(
        repository_id="r",
        repository_name="n",
        score=0.5,
        level="high",
        evidence="e",
        selected_by_ai=False,
        selected_by_user_final=False,
    )


def test_presentation_fields_default_to_empty_and_none():
    """group / trust 缺省空串、score_ranked 缺省 None（历史 trace 反序列化零破坏）。"""
    cand = _bare_candidate()
    assert cand.group == ""
    assert cand.trust == ""
    assert cand.score_ranked is None


def test_model_dump_key_set_includes_presentation_fields():
    """model_dump 键集合含三个新键（经 trace.candidates JSON 自动到达前端）。"""
    dumped = _bare_candidate().model_dump()
    assert {"group", "trust", "score_ranked"} <= set(dumped)


def test_model_dump_keeps_score_ranked_none_as_none():
    """score_ranked 为 None 时原样输出 None（**不**被转成 0.0——前端据此回退 score）。"""
    assert _bare_candidate().model_dump()["score_ranked"] is None


def _make_v2_result_with_presentation(repos):
    """构造带呈现字段的 v2 fake（group / trust / score_ranked 三者都非缺省）。"""
    from codegraph.services.repo_router_v2 import (
        RepoRouteCandidateV2,
        RepoRouteResultV2,
    )

    return RepoRouteResultV2(
        candidates=[
            RepoRouteCandidateV2(
                repo_id=str(repos[0].id),
                repo_name=repos[0].name,
                score=0.92,
                confidence="high",
                reasoning="树推理命中",
                group="global",
                trust="needs_confirmation",
                score_ranked=0.42,
            )
        ],
        router_version="v2",
        auto_selected=True,
        block_order=["global", "in_project"],
    )


async def test_v2_presentation_fields_mapped_to_pydantic_candidate(
    project_with_repos, conversation, monkeypatch
):
    """router 候选的 group / trust / score_ranked 逐字映射到 pydantic 候选。"""
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    monkeypatch.setattr(
        RepoRouterV2,
        "route",
        AsyncMock(return_value=_make_v2_result_with_presentation(repos)),
    )

    candidates = (
        await _analyze_relevance_core(
            query="presentation mapping",
            space_id=str(project.id),
            conversation_id=str(conversation.id),
        )
    ).candidates
    assert len(candidates) == 1
    assert candidates[0].group == "global"
    assert candidates[0].trust == "needs_confirmation"
    assert candidates[0].score_ranked == pytest.approx(0.42)


async def test_trace_candidates_json_carries_presentation_fields(
    project_with_repos, conversation, monkeypatch
):
    """RepositoryRoutingTrace.candidates JSON 每个元素含三个新键（model_dump 透传）。"""
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    monkeypatch.setattr(
        RepoRouterV2,
        "route",
        AsyncMock(return_value=_make_v2_result_with_presentation(repos)),
    )

    result = await analyze_repository_relevance(
        query="presentation trace",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True

    trace = await RepositoryRoutingTrace.objects.filter(
        conversation_id=conversation.id
    ).afirst()
    assert trace is not None
    for cand in trace.candidates:
        assert cand["group"] == "global"
        assert cand["trust"] == "needs_confirmation"
        assert cand["score_ranked"] == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# 8. D-1 候选范围语义（107-07）：项目关联仓改走分组依据
# ---------------------------------------------------------------------------


async def test_v2_route_receives_grouping_not_hard_filter(
    project_with_repos, conversation, monkeypatch
):
    """chat 入口：repository_ids 放开为 None，空间仓改经 grouping_repository_ids 传入。"""
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    spy = AsyncMock(return_value=_make_v2_result(repos))
    monkeypatch.setattr(RepoRouterV2, "route", spy)

    result = await analyze_repository_relevance(
        query="grouping kwargs",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True

    kwargs = spy.await_args.kwargs
    assert kwargs["repository_ids"] is None
    assert kwargs["grouping_repository_ids"] == sorted(str(r.id) for r in repos)


async def test_v2_cross_group_candidate_is_not_dropped_in_mapping(
    project_with_repos, conversation, monkeypatch
):
    """全库召回后跨组候选不在 repo_by_id 里 → 用候选自带 repo_name 兜底，不被丢弃。

    继续沿用「查不到就跳过」的旧写法会让 global 分区在映射阶段被清空——与硬过滤
    同一个后果（Pitfall 2 的第二个入口）。
    """
    from codegraph.services.repo_router_v2 import (
        RepoRouteCandidateV2,
        RepoRouteResultV2,
        RepoRouterV2,
    )

    project, repos = project_with_repos
    stub = RepoRouteResultV2(
        candidates=[
            RepoRouteCandidateV2(
                repo_id="repo-outside-space",
                repo_name="外部仓",
                score=0.95,
                confidence="high",
                reasoning="正确实现在空间关联范围之外",
                group="global",
                trust="needs_confirmation",
            ),
            RepoRouteCandidateV2(
                repo_id=str(repos[0].id),
                repo_name=repos[0].name,
                score=0.40,
                confidence="medium",
                reasoning="空间内弱命中",
                group="in_project",
                trust="trusted",
            ),
        ],
        router_version="v2",
        auto_selected=True,
        block_order=["global", "in_project"],
    )
    monkeypatch.setattr(RepoRouterV2, "route", AsyncMock(return_value=stub))

    result = await analyze_repository_relevance(
        query="cross group mapping",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True

    cands = result.output["data"]["candidates"]
    by_id = {c["repository_id"]: c for c in cands}
    assert "repo-outside-space" in by_id, "跨组候选被映射阶段丢弃即命中 Pitfall 2"
    assert by_id["repo-outside-space"]["repository_name"] == "外部仓"
    assert by_id[str(repos[0].id)]["repository_name"] == repos[0].name


# ---------------------------------------------------------------------------
# 10. trace 写入侧接线（107-08 Task 1）：degrade_reason / block_order 两列
#
# 这三条用例守护的不是「模型有列」（那是模型测试的事），而是「写入侧真的在写」。
# 只测模型与 payload 时，写入侧漏填会让全套测试保持全绿而生产两列恒为列默认值：
# 降级原因行永不出现（RELY-03 落空）、block_order 恒空导致前端永远平铺。
# ---------------------------------------------------------------------------


def _make_degraded_v2_result(repos):
    """构造降级的 v2 fake：router_version + 两个结果级字段全部非默认值。"""
    from codegraph.services.repo_router_v2 import (
        RepoRouteCandidateV2,
        RepoRouteResultV2,
    )

    return RepoRouteResultV2(
        candidates=[
            RepoRouteCandidateV2(
                repo_id=str(repos[0].id),
                repo_name=repos[0].name,
                score=0.88,
                confidence="high",
                reasoning="Stage 0 节点检索命中（Stage 1 超时未参与）",
                group="in_project",
                trust="trusted",
            )
        ],
        router_version="v2_stage0_only",
        auto_selected=True,
        degraded=True,
        block_order=["global", "in_project"],
        degrade_reason="timeout",
    )


async def test_trace_write_persists_degrade_reason_and_block_order(
    project_with_repos, conversation, monkeypatch
):
    """经工具真实调用路径落 trace 后，从 DB 取回的两列**非**列默认值。

    断言方向刻意写成「!= 默认值」+ 「== router 结果值」两段：前者检出「写入侧漏填」
    这一类会让其余测试全绿的缺陷，后者锁定值来自 router 而非硬编码。
    """
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    monkeypatch.setattr(
        RepoRouterV2, "route", AsyncMock(return_value=_make_degraded_v2_result(repos))
    )

    result = await analyze_repository_relevance(
        query="trace write degrade",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True

    trace = await RepositoryRoutingTrace.objects.filter(
        conversation_id=conversation.id
    ).afirst()
    assert trace is not None
    assert trace.degrade_reason != "", "写入侧未填 degrade_reason → 降级原因行永不出现"
    assert trace.block_order != [], "写入侧未填 block_order → 前端永远平铺"
    assert trace.degrade_reason == "timeout"
    assert trace.block_order == ["global", "in_project"]
    assert trace.router_version == "v2_stage0_only"


async def test_trace_write_undegraded_v2_leaves_degrade_reason_empty(
    project_with_repos, conversation, monkeypatch
):
    """router_version="v2"（未降级）→ degrade_reason 落空串，block_order 仍照落。"""
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    monkeypatch.setattr(
        RepoRouterV2,
        "route",
        AsyncMock(return_value=_make_v2_result_with_presentation(repos)),
    )

    result = await analyze_repository_relevance(
        query="trace write undegraded",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True

    trace = await RepositoryRoutingTrace.objects.filter(
        conversation_id=conversation.id
    ).afirst()
    assert trace is not None
    assert trace.router_version == "v2"
    assert trace.degrade_reason == ""
    assert trace.block_order == ["global", "in_project"]


async def test_trace_write_legacy_path_keeps_column_defaults(
    project_with_repos, conversation, monkeypatch
):
    """legacy 聚合路径（legacy_hybrid）两列留列默认值——历史行渲染不变。"""
    project, repos = project_with_repos
    items_by_repo = {
        str(repos[0].id): [{"score": 0.8, "payload": {"file_path": "x.py"}}],
    }
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo=items_by_repo))

    result = await analyze_repository_relevance(
        query="legacy defaults",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True

    trace = await RepositoryRoutingTrace.objects.filter(
        conversation_id=conversation.id
    ).afirst()
    assert trace is not None
    assert trace.router_version == "legacy_hybrid"
    assert trace.degrade_reason == ""
    assert trace.block_order == []


# ---------------------------------------------------------------------------
# 10b. 按组配额截断（MN-03）：top_k 较小时不得把某一组整组截空
# ---------------------------------------------------------------------------


def _cand(rid: str, *, group: str, score: float) -> Any:
    from agents.tools.schemas.repository_relevance import RepositoryRelevanceCandidate

    return RepositoryRelevanceCandidate(
        repository_id=rid,
        repository_name=rid,
        score=score,
        level="medium",
        evidence="ev",
        selected_by_ai=False,
        selected_by_user_final=False,
        group=group,
        score_ranked=score,
    )


def test_group_quota_truncation_keeps_one_per_group() -> None:
    """全局组分数整体占优时，in_project 组仍保留至少 1 条（否则分区被前端过滤掉）。"""
    from agents.tools.repository_relevance import _truncate_by_group_quota

    ordered = [
        _cand("g1", group="global", score=0.95),
        _cand("g2", group="global", score=0.9),
        _cand("g3", group="global", score=0.85),
        _cand("ip1", group="in_project", score=0.4),
    ]
    kept = _truncate_by_group_quota(ordered, 3)

    assert len(kept) == 3
    assert {c.group for c in kept} == {"global", "in_project"}
    assert [c.repository_id for c in kept] == ["g1", "g2", "ip1"]


def test_group_quota_truncation_preserves_global_descending_order() -> None:
    """截断只做取舍不重排：输出仍是输入的相对顺序（全局 score_ranked 降序）。"""
    from agents.tools.repository_relevance import _truncate_by_group_quota

    ordered = [
        _cand("ip1", group="in_project", score=0.9),
        _cand("g1", group="global", score=0.8),
        _cand("ip2", group="in_project", score=0.7),
    ]
    kept = _truncate_by_group_quota(ordered, 2)

    assert [c.repository_id for c in kept] == ["ip1", "g1"]


def test_group_quota_truncation_is_noop_when_under_budget() -> None:
    from agents.tools.repository_relevance import _truncate_by_group_quota

    ordered = [_cand("a", group="global", score=0.5)]
    assert _truncate_by_group_quota(ordered, 5) == ordered
    assert _truncate_by_group_quota(ordered, 0) == []


async def test_tool_truncation_keeps_both_groups_present(
    project_with_repos, conversation, monkeypatch
):
    """经真实工具路径：top_k=2 且全局组占优时，返回结果里两个组都还在。"""
    from codegraph.services.repo_router_v2 import (
        RepoRouteCandidateV2,
        RepoRouteResultV2,
        RepoRouterV2,
    )

    project, repos = project_with_repos

    def _v2(rid: str, name: str, group: str, score: float) -> RepoRouteCandidateV2:
        return RepoRouteCandidateV2(
            repo_id=rid,
            repo_name=name,
            score=score,
            confidence="medium",
            reasoning="",
            group=group,
            score_ranked=score,
        )

    monkeypatch.setattr(
        RepoRouterV2,
        "route",
        AsyncMock(
            return_value=RepoRouteResultV2(
                candidates=[
                    _v2("out-1", "外部仓1", "global", 0.95),
                    _v2("out-2", "外部仓2", "global", 0.9),
                    _v2(str(repos[0].id), repos[0].name, "in_project", 0.4),
                ],
                router_version="v2",
                auto_selected=False,
                block_order=["global", "in_project"],
            )
        ),
    )

    result = await analyze_repository_relevance(
        query="group quota truncation",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
        top_k=2,
    )
    data = result.output["data"]
    assert len(data["candidates"]) == 2
    assert {c["group"] for c in data["candidates"]} == {"global", "in_project"}
    # block_order 报长度 2，候选里两个组也都在 —— 前端不会出现「分组开着只有一个区」
    assert data["block_order"] == ["global", "in_project"]


# ---------------------------------------------------------------------------
# 11. 出参侧接线（BL-02）：结果级四件套必须随 ToolResult.output['data'] 出参
#
# 前端在 SSE part_completed 时解析的就是这个 dict。缺任一键 → 该键在生产恒
# undefined：降级横幅不出现（RELY-03 落空）、block_order 缺失让分组呈现退回平铺
# （ROUTE-01/02 在「正确仓在跨组」这类最需要分组的查询上恰好不生效）。用户只有刷新
# 页面或改一次勾选才能看到——也就是在对话进行中完全看不到。
# ---------------------------------------------------------------------------


async def test_tool_output_carries_result_level_facts_from_router(
    project_with_repos, conversation, monkeypatch
):
    """降级 v2 路径：ToolResult data 的四键值 == router 结果值（非默认值）。"""
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    monkeypatch.setattr(
        RepoRouterV2, "route", AsyncMock(return_value=_make_degraded_v2_result(repos))
    )

    result = await analyze_repository_relevance(
        query="realtime degrade facts",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    assert result.success is True

    data = result.output["data"]
    assert {"router_version", "degraded", "degrade_reason", "block_order"} <= set(data)
    assert data["router_version"] == "v2_stage0_only"
    assert data["degraded"] is True, "出参未带 degraded → 对话进行中无降级横幅"
    assert data["degrade_reason"] == "timeout"
    assert data["block_order"] == ["global", "in_project"], "出参未带 block_order → 前端退回平铺"


async def test_tool_output_degraded_matches_detail_payload_derivation(
    project_with_repos, conversation, monkeypatch
):
    """实时出参与 detail payload 共用同一个 degraded 派生点（刷新前后不得不一致）。"""
    from chat.models import derive_routing_degraded
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    monkeypatch.setattr(
        RepoRouterV2,
        "route",
        AsyncMock(return_value=_make_v2_result_with_presentation(repos)),
    )

    result = await analyze_repository_relevance(
        query="degraded derivation parity",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    data = result.output["data"]
    trace = await RepositoryRoutingTrace.objects.aget(id=data["trace_id"])
    assert data["degraded"] == derive_routing_degraded(trace.router_version)
    assert data["degraded"] is False  # router_version == "v2" 未降级


async def test_tool_output_block_order_matches_persisted_trace(
    project_with_repos, conversation, monkeypatch
):
    """出参 block_order/degrade_reason 与落库 trace 同值（实时链路与刷新后一致）。"""
    from codegraph.services.repo_router_v2 import RepoRouterV2

    project, repos = project_with_repos
    monkeypatch.setattr(
        RepoRouterV2, "route", AsyncMock(return_value=_make_degraded_v2_result(repos))
    )

    result = await analyze_repository_relevance(
        query="realtime vs persisted parity",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    data = result.output["data"]
    trace = await RepositoryRoutingTrace.objects.aget(id=data["trace_id"])
    assert data["block_order"] == trace.block_order
    assert data["degrade_reason"] == trace.degrade_reason
    assert data["router_version"] == trace.router_version


async def test_legacy_path_tool_output_keeps_neutral_result_level_facts(
    project_with_repos, conversation, monkeypatch
):
    """legacy 聚合路径出参四键取中性默认值 → 历史渲染不变（无横幅、平铺）。"""
    project, repos = project_with_repos
    items_by_repo = {
        str(repos[0].id): [{"score": 0.8, "payload": {"file_path": "x.py"}}],
    }
    _patch_hybrid_search(monkeypatch, _make_rag_result(items_by_repo=items_by_repo))

    result = await analyze_repository_relevance(
        query="legacy neutral facts",
        space_id=str(project.id),
        conversation_id=str(conversation.id),
    )
    data = result.output["data"]
    assert data["router_version"] == "legacy_hybrid"
    assert data["degraded"] is False
    assert data["degrade_reason"] == ""
    assert data["block_order"] == []


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

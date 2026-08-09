"""RepoAssociationService 守护测试（Phase 88，REPO-01，88-02）。

覆盖（COMBINED 选仓复用 RepoRouterV2 + 观测埋点 + 落 proposed + 多轮 refine）：
- propose 调 ``RepoRouterV2.route`` 且 ``repository_ids`` == Space.repositories 集合
  （范围限定，绝不 None/全库）。
- route 调用处于 ``use_call_source(AUX_REPO_ROUTER)`` 作用域（捕获 get_call_source）。
- route 后 ``arecord_retrieval_trace(kind="routing")`` 被调一次，payload 含 query+candidates。
- 候选落 ``RepoAssociation(status="proposed")``，字段从 RepoRouteCandidateV2 正确映射。
- 空 features / 空 Space.repositories → 返回空提案、绝不调 route（防全库噪声）。
- refine 把 extra_instruction 并进 query 重 route，各轮独立写一条 RetrievalTrace。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agents.call_source import get_call_source
from codegraph.services.repo_router_v2 import RepoRouteCandidateV2, RepoRouteResultV2
from initiatives.models import (
    Project,
    RepoAssociation,
    RepoAssociationStatus,
)
from initiatives.services.repo_association_service import RepoAssociationService
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

_SVC_MOD = "initiatives.services.repo_association_service"
_ROUTER = "codegraph.services.repo_router_v2.RepoRouterV2"

_FEATURES = [
    {"module": "鉴权", "name": "登录", "description": "支持飞书扫码登录"},
    {"module": "鉴权", "name": "登出", "description": "清理会话"},
]


def _make_space_with_repos(n: int = 2) -> tuple[Space, Project, list[Repository]]:
    space = Space.objects.create(name="AssocSvcSpace", feishu_project_key="svc-k")
    project = Project.objects.create(space=space, name="P", feishu_project_key="")
    repos: list[Repository] = []
    for i in range(n):
        repo = Repository.objects.create(
            name=f"repo{i}", git_url=f"https://git/repo{i}.git"
        )
        space.repositories.add(repo)
        repos.append(repo)
    return space, project, repos


def _result_for(repos: list[Repository]) -> RepoRouteResultV2:
    candidates = [
        RepoRouteCandidateV2(
            repo_id=str(repo.id),
            repo_name=repo.name,
            score=0.9 - 0.1 * idx,
            confidence="high" if idx == 0 else "medium",
            reasoning=f"命中能力节点 {repo.name}",
            matched_node_paths=[f"{repo.name}/auth"],
        )
        for idx, repo in enumerate(repos)
    ]
    return RepoRouteResultV2(
        candidates=candidates, router_version="v2", auto_selected=True
    )


def _patch_route(capture: dict, result: RepoRouteResultV2):
    # **kwargs 兜住 route() 后续新增的 keyword 参数（如 corpus_kind）——
    # 本替身只关心 propose/refine 传下来的选仓语义，不锁死路由器签名。
    async def _fake_route(query, *, top_k, repository_ids, use_llm, **kwargs):
        capture["query"] = query
        capture["repository_ids"] = repository_ids
        capture["top_k"] = top_k
        capture["use_llm"] = use_llm
        capture["corpus_kind"] = kwargs.get("corpus_kind")
        capture["call_source"] = get_call_source()
        return result

    return patch(f"{_ROUTER}.route", _fake_route)


# ===========================================================================
# propose — COMBINED 选仓 + 范围限定 + 落 proposed
# ===========================================================================


async def test_propose_combined_persists_proposed() -> None:
    space, project, repos = await _aprep(2)
    capture: dict = {}
    trace = AsyncMock(return_value=None)
    with (
        _patch_route(capture, _result_for(repos)),
        patch(f"{_SVC_MOD}.arecord_retrieval_trace", trace),
    ):
        result = await RepoAssociationService().propose(
            space=space, features_flat=_FEATURES, project=project,
            initiated_by_user_id="u-1",
        )

    # 返回形态
    assert result["router_version"] == "v2"
    assert result["auto_selected"] is True
    assert result["query_len"] > 0
    assert len(result["candidates"]) == 2
    first = result["candidates"][0]
    assert set(first) == {
        "repo_id", "repo_name", "score", "confidence", "reason", "matched_node_paths"
    }

    # 候选落 RepoAssociation(proposed)，字段映射正确
    rows = await _aload_associations(project)
    assert len(rows) == 2
    by_repo = {r.repository_id: r for r in rows}
    top = by_repo[repos[0].id]
    assert top.status == RepoAssociationStatus.PROPOSED
    assert top.source == "router_v2"
    assert top.confidence == "high"
    assert top.routed_reason == f"命中能力节点 {repos[0].name}"
    assert top.matched_node_paths == [f"{repos[0].name}/auth"]
    assert top.initiated_by_user_id == "u-1"


async def test_propose_scope_limited_to_space_repos() -> None:
    space, project, repos = await _aprep(2)
    capture: dict = {}
    with (
        _patch_route(capture, _result_for(repos)),
        patch(f"{_SVC_MOD}.arecord_retrieval_trace", AsyncMock()),
    ):
        await RepoAssociationService().propose(
            space=space, features_flat=_FEATURES, project=project,
        )
    # repository_ids 必须限定 Space.repositories（不为 None/全库）
    assert capture["repository_ids"] is not None
    assert set(capture["repository_ids"]) == {str(r.id) for r in repos}


async def test_propose_observability_call_source_and_trace() -> None:
    space, project, repos = await _aprep(1)
    capture: dict = {}
    trace = AsyncMock(return_value=None)
    with (
        _patch_route(capture, _result_for(repos)),
        patch(f"{_SVC_MOD}.arecord_retrieval_trace", trace),
    ):
        await RepoAssociationService().propose(
            space=space, features_flat=_FEATURES, project=project,
        )
    # route 在 aux_repo_router 作用域内
    assert capture["call_source"] == "aux_repo_router"
    # arecord_retrieval_trace(kind="routing") 被调一次，payload 含 query+candidates
    trace.assert_awaited_once()
    kwargs = trace.await_args.kwargs
    assert kwargs["kind"] == "routing"
    assert "query" in kwargs["payload"]
    assert "candidates" in kwargs["payload"]
    assert kwargs["payload"].get("signal_fusion") == "charter+history"
    assert kwargs["source"] == "repo_association"


async def test_propose_fuses_charter_and_history_signals() -> None:
    """章程 + 历史融合后候选带 breakdown，且按融合分排序。"""
    space, project, repos = await _aprep(2)
    capture: dict = {}
    fused = [
        {
            "repo_id": str(repos[1].id),
            "repo_name": repos[1].name,
            "score": 0.88,
            "confidence": "high",
            "reason": "history boost",
            "matched_node_paths": ["x"],
            "breakdown": {
                "router_base": 0.3,
                "charter_match": 0.4,
                "history_match": 0.18,
                "total": 0.88,
            },
        },
        {
            "repo_id": str(repos[0].id),
            "repo_name": repos[0].name,
            "score": 0.55,
            "confidence": "medium",
            "reason": "router only",
            "matched_node_paths": ["y"],
            "breakdown": {
                "router_base": 0.55,
                "charter_match": 0.0,
                "history_match": 0.0,
                "total": 0.55,
            },
        },
    ]
    with (
        _patch_route(capture, _result_for(repos)),
        patch(f"{_SVC_MOD}.arecord_retrieval_trace", AsyncMock()),
        patch(f"{_SVC_MOD}.RepoAssociationService._fuse_extended_signals", AsyncMock(return_value=fused)),
    ):
        result = await RepoAssociationService().propose(
            space=space, features_flat=_FEATURES, project=project,
        )
    assert result["candidates"][0]["repo_id"] == str(repos[1].id)
    assert result["candidates"][0]["breakdown"]["history_match"] == 0.18


async def test_propose_empty_features_skips_route() -> None:
    space, project, _repos = await _aprep(2)
    capture: dict = {}
    trace = AsyncMock()
    with (
        _patch_route(capture, _result_for([])),
        patch(f"{_SVC_MOD}.arecord_retrieval_trace", trace),
    ):
        result = await RepoAssociationService().propose(
            space=space, features_flat=[], project=project,
        )
    assert result["candidates"] == []
    assert result["router_version"] == "skipped"
    # 空 query → 绝不调 route
    assert "query" not in capture
    trace.assert_not_awaited()


async def test_propose_no_space_repos_no_full_library() -> None:
    """Space.repositories 为空 → 返回空提案，绝不全库 route（Pitfall 6）。"""
    space = await _acreate_empty_space()
    project = await _acreate_project(space)
    capture: dict = {}
    with (
        _patch_route(capture, _result_for([])),
        patch(f"{_SVC_MOD}.arecord_retrieval_trace", AsyncMock()),
    ):
        result = await RepoAssociationService().propose(
            space=space, features_flat=_FEATURES, project=project,
        )
    assert result["router_version"] == "skipped"
    assert "repository_ids" not in capture  # route 未被调用


# ===========================================================================
# refine — 多轮重 route（extra_instruction 并进 query）
# ===========================================================================


async def test_refine_reroute_includes_extra_instruction() -> None:
    space, project, repos = await _aprep(2)
    capture: dict = {}
    trace = AsyncMock(return_value=None)
    with (
        _patch_route(capture, _result_for(repos)),
        patch(f"{_SVC_MOD}.arecord_retrieval_trace", trace),
    ):
        result = await RepoAssociationService().refine(
            space=space, project=project, features_flat=_FEATURES,
            extra_instruction="只看后端仓库", initiated_by_user_id="u-9",
        )
    # query 含 extra_instruction 约束文本
    assert "只看后端仓库" in capture["query"]
    # 重 route + 落库 + 各轮一条 trace
    assert result["router_version"] == "v2"
    trace.assert_awaited_once()
    rows = await _aload_associations(project)
    assert len(rows) == 2


# ===========================================================================
# sync ORM helpers（async 测试经 sync_to_async 包）
# ===========================================================================


from asgiref.sync import sync_to_async  # noqa: E402


@sync_to_async
def _aprep(n: int):
    return _make_space_with_repos(n)


@sync_to_async
def _acreate_empty_space() -> Space:
    return Space.objects.create(name="EmptySpace", feishu_project_key="empty-k")


@sync_to_async
def _acreate_project(space: Space) -> Project:
    return Project.objects.create(space=space, name="P", feishu_project_key="")


@sync_to_async
def _aload_associations(project: Project) -> list[RepoAssociation]:
    return list(RepoAssociation.objects.filter(project=project))

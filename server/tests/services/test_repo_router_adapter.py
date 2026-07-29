"""RepoRouterV2Adapter 测试（ROUTE-01）+ _h_route 快照 payload 落盘（ROUTE-09，105-07）。

覆盖结果映射 / 空 query 跳过 / 候选范围三档优先级解析（include_repos → project
仓库 → 全库）/ degraded·snapshot 透传 / repo.routing 快照 payload 组装。
RepoRouterV2.route 全程 mock，不触真实向量检索。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async

from codegraph.services.repo_router_v2 import (
    RepoRouteCandidateV2,
    RepoRouteResultV2,
)
from delivery.models import ConvergenceSession, ConvergenceSessionEntrypoint
from services.process_runtime import RepoRouterV2Adapter
from services.process_runtime.builtin_processes import _h_route

# transaction=True：本文件 async 用例经 sync_to_async 桥接在独立线程连接建数据
# （含 Repository），普通 @pytest.mark.django_db（rollback）无法回滚跨线程连接的提交，
# 会泄漏 Repository 行污染后续全仓计数用例。TransactionTestCase teardown TRUNCATE 全表。
pytestmark = pytest.mark.django_db(transaction=True)


def _route_result() -> RepoRouteResultV2:
    return RepoRouteResultV2(
        candidates=[
            RepoRouteCandidateV2(
                repo_id="r1",
                repo_name="N",
                score=0.9,
                confidence="high",
                reasoning="x",
            )
        ],
        router_version="v2",
        auto_selected=True,
    )


@pytest.mark.asyncio
async def test_maps_router_result(monkeypatch) -> None:
    """RepoRouterV2 结果映射为精简 dict（repo_id/confidence/repository_name + version/auto）。"""
    mock_route = AsyncMock(return_value=_route_result())
    monkeypatch.setattr(
        "services.process_runtime.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = ConvergenceSession(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        stage_state={"decomposition": {"requirement_text": "做一个登录页"}},
    )
    result = await RepoRouterV2Adapter().route(session)
    assert result["candidates"][0] == {
        "repo_id": "r1",
        "confidence": "high",
        "repository_name": "N",
    }
    assert result["router_version"] == "v2"
    assert result["auto_selected"] is True


@pytest.mark.asyncio
async def test_empty_query_skips(monkeypatch) -> None:
    """空 requirement_text → 返回 skipped 空候选，不调 RepoRouterV2.route。"""
    mock_route = AsyncMock(return_value=_route_result())
    monkeypatch.setattr(
        "services.process_runtime.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = ConvergenceSession(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        stage_state={},
    )
    result = await RepoRouterV2Adapter().route(session)
    assert result == {"candidates": [], "router_version": "skipped", "auto_selected": False}
    mock_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_scope_include_repos_precedence(monkeypatch) -> None:
    """include_repos 显式指定 → repository_ids 取之（最高优先级）。"""
    mock_route = AsyncMock(return_value=_route_result())
    monkeypatch.setattr(
        "services.process_runtime.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="route",
        stage_state={"decomposition": {"requirement_text": "x", "include_repos": ["rX"]}},
    )
    await RepoRouterV2Adapter().route(session)
    assert mock_route.await_args.kwargs["repository_ids"] == ["rX"]


@pytest.mark.asyncio
async def test_scope_project_repos_fallback(monkeypatch) -> None:
    """无 include_repos 时回退 work_item.space 仓库 id 列表。"""
    mock_route = AsyncMock(return_value=_route_result())
    monkeypatch.setattr(
        "services.process_runtime.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    repo_id = await _make_work_item_with_repo()
    work_item = await _latest_work_item()
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="route",
        work_item=work_item,
        stage_state={"decomposition": {"requirement_text": "x"}},
    )
    await RepoRouterV2Adapter().route(session)
    assert mock_route.await_args.kwargs["repository_ids"] == [repo_id]


@pytest.mark.asyncio
async def test_scope_no_work_item_full_repo(monkeypatch) -> None:
    """无 include_repos 且无 work_item → repository_ids=None（全库）。"""
    mock_route = AsyncMock(return_value=_route_result())
    monkeypatch.setattr(
        "services.process_runtime.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="route",
        stage_state={"decomposition": {"requirement_text": "x"}},
    )
    await RepoRouterV2Adapter().route(session)
    assert mock_route.await_args.kwargs["repository_ids"] is None


def _snapshot_material() -> dict:
    """构造 RepoRouteResultV2.snapshot 形状的快照材料（_build_snapshot 产物形态）。"""
    return {
        "stage0": {
            "query": "做一个登录页",
            "node_hits": [
                {
                    "node_id": "n1",
                    "repository_id": "r1",
                    "score": 0.9,
                    "node_path": "auth/login",
                    "activity_facet": "活跃开发",
                }
            ],
        },
        "stage1": {"skipped_reason": "use_llm_false"},
        "candidates": [
            {
                "repo_id": "r1",
                "repo_name": "N",
                "score": 0.9,
                "confidence": "high",
                "reasoning": "x",
                "sub_project": "",
                "sub_project_paths": [],
                "matched_node_paths": ["auth/login"],
                "breakdown": {"text": 0.7, "breadth": 0.1, "activity": 0.1},
            }
        ],
        "versions": {"weight_set_version": "phase105-v1", "index_version": "abc"},
    }


@pytest.mark.asyncio
async def test_adapter_dict_carries_degraded_and_snapshot(monkeypatch) -> None:
    """adapter dict 透传 degraded 标志与 snapshot 材料（105-07 Task 1）。"""
    stub = RepoRouteResultV2(
        candidates=[
            RepoRouteCandidateV2(
                repo_id="r1", repo_name="N", score=0.9, confidence="high", reasoning="x"
            )
        ],
        router_version="v2_stage0_only",
        auto_selected=True,
        degraded=True,
        snapshot=_snapshot_material(),
    )
    monkeypatch.setattr(
        "services.process_runtime.repo_router_adapter.RepoRouterV2.route",
        AsyncMock(return_value=stub),
    )
    session = ConvergenceSession(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        stage_state={"decomposition": {"requirement_text": "做一个登录页"}},
    )
    result = await RepoRouterV2Adapter().route(session)
    assert result["degraded"] is True
    assert result["snapshot"] == _snapshot_material()
    # candidates 精简 dict 保持现有三键不变（下游 clarify/confirm 读法零破坏）
    assert result["candidates"][0] == {
        "repo_id": "r1",
        "confidence": "high",
        "repository_name": "N",
    }


def _mock_engine_with_routing(routing: dict) -> SimpleNamespace:
    """构造 _h_route 需要的 engine mock（router 返回给定 dict，emit 可捕获）。"""
    return SimpleNamespace(
        deps=SimpleNamespace(router=SimpleNamespace(route=AsyncMock(return_value=routing))),
        session_service=SimpleNamespace(_emit_event=AsyncMock()),
    )


@pytest.mark.asyncio
async def test_h_route_emits_snapshot_payload_and_strips_snapshot_from_routing() -> None:
    """带 snapshot 的路由结果：emit 完整快照 payload；session.routing 剔除 snapshot 键。"""
    routing = {
        "candidates": [{"repo_id": "r1", "confidence": "high", "repository_name": "N"}],
        "router_version": "v2_stage0_only",
        "auto_selected": True,
        "degraded": True,
        "snapshot": _snapshot_material(),
    }
    engine = _mock_engine_with_routing(routing)
    session = SimpleNamespace(id="s1")

    outcome = await _h_route(session, engine)

    payload = engine.session_service._emit_event.call_args.args[2]
    assert payload["candidates"][0]["breakdown"] == {
        "text": 0.7,
        "breadth": 0.1,
        "activity": 0.1,
    }
    assert payload["candidates"][0]["score"] == 0.9
    assert payload["versions"]["weight_set_version"] == "phase105-v1"
    assert payload["stage0"]["query"] == "做一个登录页"
    assert payload["stage1"] == {"skipped_reason": "use_llm_false"}
    assert payload["degraded"] is True
    assert payload["auto_selected"] is True
    assert payload["router_version"] == "v2_stage0_only"
    # session.routing（stage_state_update）保持精简：不含 snapshot 键
    assert "snapshot" not in outcome.stage_state_update["routing"]
    assert outcome.stage_state_update["routing"]["degraded"] is True


@pytest.mark.asyncio
async def test_h_route_without_snapshot_keeps_minimal_payload() -> None:
    """snapshot 缺失（stub router / skipped）→ 优雅降级为现状精简 payload。"""
    routing = {
        "candidates": [{"repo_id": "r1", "confidence": "high", "repository_name": "N"}],
        "router_version": "v2",
        "auto_selected": True,
    }
    engine = _mock_engine_with_routing(routing)
    outcome = await _h_route(SimpleNamespace(id="s1"), engine)

    payload = engine.session_service._emit_event.call_args.args[2]
    assert payload == {"candidates": [{"repo_id": "r1", "confidence": "high"}]}
    assert "snapshot" not in outcome.stage_state_update["routing"]


@sync_to_async
def _make_work_item_with_repo() -> str:
    """建 project + repository（关联）+ work_item，返回 repository id 字符串。"""
    from delivery.models import WorkItem, WorkItemOrigin
    from projects.models import Space
    from repositories.models import Repository

    project = Space.objects.create(name="P")
    repo = Repository.objects.create(name="R", git_url="https://example.com/r.git")
    project.repositories.add(repo)
    WorkItem.objects.create(
        feishu_project_key="pk",
        work_item_type="story",
        work_item_id=1,
        origin=WorkItemOrigin.MANUAL,
        space=project,
        title="t",
    )
    return str(repo.id)


@sync_to_async
def _latest_work_item():
    from delivery.models import WorkItem

    return WorkItem.objects.order_by("-created_at").first()

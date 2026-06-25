"""RepoRouterV2Adapter 测试（ROUTE-01）。

覆盖结果映射 / 空 query 跳过 / 候选范围三档优先级解析（include_repos → project
仓库 → 全库）。RepoRouterV2.route 全程 mock，不触真实向量检索。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async

from codegraph.services.repo_router_v2 import (
    RepoRouteCandidateV2,
    RepoRouteResultV2,
)
from delivery.models import PlanSession, PlanSessionEntrypoint, PlanSessionStatus
from services.plan_orchestration import RepoRouterV2Adapter

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
        "services.plan_orchestration.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = PlanSession(
        entrypoint=PlanSessionEntrypoint.CHAT,
        decomposition={"requirement_text": "做一个登录页"},
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
        "services.plan_orchestration.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = PlanSession(entrypoint=PlanSessionEntrypoint.CHAT, decomposition={})
    result = await RepoRouterV2Adapter().route(session)
    assert result == {"candidates": [], "router_version": "skipped", "auto_selected": False}
    mock_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_scope_include_repos_precedence(monkeypatch) -> None:
    """include_repos 显式指定 → repository_ids 取之（最高优先级）。"""
    mock_route = AsyncMock(return_value=_route_result())
    monkeypatch.setattr(
        "services.plan_orchestration.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.ROUTING,
        decomposition={"requirement_text": "x", "include_repos": ["rX"]},
    )
    await RepoRouterV2Adapter().route(session)
    assert mock_route.await_args.kwargs["repository_ids"] == ["rX"]


@pytest.mark.asyncio
async def test_scope_project_repos_fallback(monkeypatch) -> None:
    """无 include_repos 时回退 work_item.space 仓库 id 列表。"""
    mock_route = AsyncMock(return_value=_route_result())
    monkeypatch.setattr(
        "services.plan_orchestration.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    repo_id = await _make_work_item_with_repo()
    work_item = await _latest_work_item()
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW,
        status=PlanSessionStatus.ROUTING,
        work_item=work_item,
        decomposition={"requirement_text": "x"},
    )
    await RepoRouterV2Adapter().route(session)
    assert mock_route.await_args.kwargs["repository_ids"] == [repo_id]


@pytest.mark.asyncio
async def test_scope_no_work_item_full_repo(monkeypatch) -> None:
    """无 include_repos 且无 work_item → repository_ids=None（全库）。"""
    mock_route = AsyncMock(return_value=_route_result())
    monkeypatch.setattr(
        "services.plan_orchestration.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.ROUTING,
        decomposition={"requirement_text": "x"},
    )
    await RepoRouterV2Adapter().route(session)
    assert mock_route.await_args.kwargs["repository_ids"] is None


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

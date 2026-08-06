"""固定路由（repo binding pin）测试：项目手动绑定仓库+分支时跳过自动仓库路由。

守四件事：

1. **解析语义**：只认 ``source=manual``；同仓多条取最新；project_id 直取与
   work_item → space → project 两条解析路径等价；无绑定/无上下文返回空。
2. **旧链短路**：``RepoRouterV2Adapter`` 在项目有手动绑定时返回
   ``router_version="project_binding"``、绑定仓全量候选，**不调 RepoRouterV2**。
3. **蓝图链短路**：``BlueprintRouteAdapter`` 同上（契约摘要形状逐键在场），并尊重
   reroute 的 ``exclude_repository_ids``（固定项目不补新仓）。
4. **分支固定**：``apinned_branch_for`` 取该仓绑定分支（调研容器 checkout 依据）。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from delivery.models import ConvergenceSession, ConvergenceSessionEntrypoint
from services.process_runtime import RepoRouterV2Adapter
from services.process_runtime.blueprint_route import BlueprintRouteAdapter
from services.process_runtime.repo_binding_pin import (
    PINNED_ROUTER_VERSION,
    apinned_branch_for,
    aresolve_pinned_bindings,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ── 工厂（tests/ 不在 INV-6 扫描范围内，直接 ORM 建绑定行） ────────────────


@sync_to_async
def _make_project_with_bindings() -> dict:
    """建 Space + Project + 两仓 + 手动/自动绑定，返回各 id 字符串。"""
    from delivery.models import WorkItem, WorkItemOrigin
    from initiatives.models import BranchSource, Project, ProjectBranch
    from projects.models import Space
    from repositories.models import Repository

    space = Space.objects.create(name="S")
    project = Project.objects.create(space=space, name="P")
    repo_a = Repository.objects.create(
        name="repo-a", git_url="https://example.com/a.git", default_branch="main"
    )
    repo_b = Repository.objects.create(
        name="repo-b", git_url="https://example.com/b.git", default_branch="main"
    )
    # repo_a：两条手动绑定（取最新 feature/new）+ 一条 coding 自动绑定（必须被忽略）
    ProjectBranch.objects.create(
        project=project, repository=repo_a, branch_name="feature/old", source=BranchSource.MANUAL
    )
    ProjectBranch.objects.create(
        project=project, repository=repo_a, branch_name="feature/new", source=BranchSource.MANUAL
    )
    ProjectBranch.objects.create(
        project=project, repository=repo_a, branch_name="auto/coding", source=BranchSource.CODING
    )
    # repo_b：一条手动绑定
    ProjectBranch.objects.create(
        project=project, repository=repo_b, branch_name="develop", source=BranchSource.MANUAL
    )
    work_item = WorkItem.objects.create(
        feishu_project_key="pk",
        work_item_type="story",
        work_item_id=1,
        origin=WorkItemOrigin.MANUAL,
        space=space,
        title="t",
    )
    return {
        "project_id": str(project.id),
        "work_item_id": work_item.id,
        "repo_a": str(repo_a.id),
        "repo_b": str(repo_b.id),
    }


@sync_to_async
def _make_project_without_bindings() -> dict:
    from initiatives.models import Project
    from projects.models import Space

    space = Space.objects.create(name="S2")
    project = Project.objects.create(space=space, name="P2")
    return {"project_id": str(project.id)}


# ── 解析语义 ───────────────────────────────────────────────────────────────


async def test_resolver_manual_only_and_latest_per_repo() -> None:
    """只认 manual 来源；同仓多条手动绑定取最新创建的那条。"""
    ctx = await _make_project_with_bindings()
    bindings = await aresolve_pinned_bindings(project_id=ctx["project_id"])
    by_repo = {b["repository_id"]: b for b in bindings}
    assert set(by_repo) == {ctx["repo_a"], ctx["repo_b"]}
    assert by_repo[ctx["repo_a"]]["branch_name"] == "feature/new"
    assert by_repo[ctx["repo_b"]]["branch_name"] == "develop"
    assert by_repo[ctx["repo_a"]]["repository_name"] == "repo-a"


async def test_resolver_work_item_path_equals_project_path() -> None:
    """work_item → space → project 解析路径与 project_id 直取等价。"""
    ctx = await _make_project_with_bindings()
    via_project = await aresolve_pinned_bindings(project_id=ctx["project_id"])
    via_work_item = await aresolve_pinned_bindings(work_item_id=ctx["work_item_id"])
    assert via_work_item == via_project
    assert len(via_work_item) == 2


async def test_resolver_no_bindings_and_no_context() -> None:
    """无手动绑定 / 无上下文 / 非法 id 一律空列表，绝不抛。"""
    ctx = await _make_project_without_bindings()
    assert await aresolve_pinned_bindings(project_id=ctx["project_id"]) == []
    assert await aresolve_pinned_bindings() == []
    assert await aresolve_pinned_bindings(project_id="not-a-uuid") == []


async def test_pinned_branch_for_repo() -> None:
    """apinned_branch_for：取该仓绑定分支；未绑定仓返回空串。"""
    ctx = await _make_project_with_bindings()
    session = SimpleNamespace(
        decomposition={"project_id": ctx["project_id"]},
        work_item_id=None,
    )
    assert await apinned_branch_for(session, ctx["repo_a"]) == "feature/new"
    assert await apinned_branch_for(session, "00000000-0000-0000-0000-000000000000") == ""


# ── 旧链（technical_plan）短路 ─────────────────────────────────────────────


async def test_legacy_adapter_pins_and_skips_router(monkeypatch) -> None:
    """项目有手动绑定 → 候选=绑定仓、router_version=project_binding，不调 RepoRouterV2。"""
    ctx = await _make_project_with_bindings()
    mock_route = AsyncMock()
    monkeypatch.setattr(
        "services.process_runtime.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="route",
        work_item_id=ctx["work_item_id"],
        stage_state={"decomposition": {"requirement_text": "做一个登录页"}},
    )
    result = await RepoRouterV2Adapter().route(session)

    mock_route.assert_not_awaited()
    assert result["router_version"] == PINNED_ROUTER_VERSION
    assert result["auto_selected"] is True
    assert result["degraded"] is False
    by_repo = {c["repo_id"]: c for c in result["candidates"]}
    assert set(by_repo) == {ctx["repo_a"], ctx["repo_b"]}
    cand = by_repo[ctx["repo_a"]]
    assert cand["confidence"] == "high"
    assert cand["group"] == "in_project"
    assert cand["trust"] == "trusted"
    assert cand["pinned_branch"] == "feature/new"


async def test_legacy_adapter_without_bindings_falls_through(monkeypatch) -> None:
    """项目无手动绑定 → 走既有自动路由（RepoRouterV2 被调）。"""
    from codegraph.services.repo_router_v2 import RepoRouteResultV2

    mock_route = AsyncMock(
        return_value=RepoRouteResultV2(candidates=[], router_version="v2", auto_selected=False)
    )
    monkeypatch.setattr(
        "services.process_runtime.repo_router_adapter.RepoRouterV2.route", mock_route
    )
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="route",
        stage_state={"decomposition": {"requirement_text": "做一个登录页"}},
    )
    result = await RepoRouterV2Adapter().route(session)
    mock_route.assert_awaited_once()
    assert result["router_version"] == "v2"


# ── 蓝图链（technical_blueprint）短路 ──────────────────────────────────────

_TOP_LEVEL_KEYS = {
    "router_version",
    "auto_selected",
    "intent",
    "weights_used",
    "charter_supplement_count",
    "unjustified_boundary_hit_count",
    "candidates",
    "citations",
}
_CANDIDATE_KEYS = {
    "repository_id",
    "repository_name",
    "role_suggestion",
    "confidence",
    "total",
    "breakdown",
    "evidence",
}


def _bp_spec() -> dict:
    return {
        "goal": [{"block_id": "blk_goal", "type": "paragraph", "text": "登录页改造"}],
        "feature_points": [
            {
                "id": "fp_01",
                "title": "登录页",
                "intent": "brownfield",
                "description": [
                    {"block_id": "blk_fp_01", "type": "paragraph", "text": "改造既有登录页。"}
                ],
            }
        ],
    }


async def _make_blueprint_session(project_id: str) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="route",
        stage_state={
            "blueprint": {"requirement_spec": _bp_spec()},
            "decomposition": {"requirement_text": "登录页改造", "project_id": project_id},
        },
    )


async def test_blueprint_adapter_pins_and_skips_router() -> None:
    """蓝图链短路：候选=绑定仓（direct/high），契约键逐键在场，路由器不被调。"""
    ctx = await _make_project_with_bindings()
    router = SimpleNamespace(route=AsyncMock())
    session = await _make_blueprint_session(ctx["project_id"])

    summary = await BlueprintRouteAdapter(router=router).route(session)

    router.route.assert_not_awaited()
    assert _TOP_LEVEL_KEYS <= set(summary)
    assert summary["router_version"] == PINNED_ROUTER_VERSION
    assert summary["auto_selected"] is True
    assert summary["intent"] == "brownfield"
    by_repo = {c["repository_id"]: c for c in summary["candidates"]}
    assert set(by_repo) == {ctx["repo_a"], ctx["repo_b"]}
    cand = by_repo[ctx["repo_a"]]
    assert _CANDIDATE_KEYS <= set(cand)
    assert cand["role_suggestion"] == "direct"
    assert cand["confidence"] == "high"
    assert cand["pinned_branch"] == "feature/new"
    assert cand["evidence"]["router_version"] == PINNED_ROUTER_VERSION


async def test_pinned_route_plan_drafted_carries_router_version_and_branch() -> None:
    """⭐ 固定路由必须**在事件里自证身份**：`route.plan_drafted` 带 `router_version` 与
    `pinned_branch`。

    为什么这是硬要求：固定路由下自动打分整段没跑 ⇒ `total` 恒 1.0、章程/历史分量与全部证据
    计数恒 0。前端的阶段全景只能从 `router_version == "project_binding"` 判断「这是没跑」
    而不是「跑出来是 0」——缺了这个键，那张全 0 的适配度表在用户眼里就是数据链路坏了。
    """
    ctx = await _make_project_with_bindings()
    session = await _make_blueprint_session(ctx["project_id"])

    with patch(
        "delivery.services.convergence_session_service.ConvergenceSessionService.aemit_event",
        new=AsyncMock(),
    ) as emit:
        await BlueprintRouteAdapter(router=SimpleNamespace(route=AsyncMock())).route(session)

    drafted = [
        call for call in emit.call_args_list if call.args[0] == "blueprint.route.plan_drafted"
    ]
    assert len(drafted) == 1
    payload = drafted[0].args[2]
    assert payload["router_version"] == PINNED_ROUTER_VERSION
    assert payload["repository_count"] == 2
    by_repo = {row["repository_id"]: row for row in payload["repositories"]}
    assert by_repo[ctx["repo_a"]]["pinned_branch"] == "feature/new"

    # scored 侧同样带 router_version（前端两条事件任一命中即可判定固定路由）
    scored = [call for call in emit.call_args_list if call.args[0] == "blueprint.route.scored"]
    assert scored and scored[0].args[2]["router_version"] == PINNED_ROUTER_VERSION


async def test_blueprint_adapter_pin_respects_exclusions() -> None:
    """reroute 排除集生效：被排除的绑定仓剔除；全排除时候选为空但仍固定（不补新仓）。"""
    ctx = await _make_project_with_bindings()
    router = SimpleNamespace(route=AsyncMock())
    session = await _make_blueprint_session(ctx["project_id"])

    adapter = BlueprintRouteAdapter(router=router)
    partial = await adapter.route(session, exclude_repository_ids={ctx["repo_a"]})
    assert [c["repository_id"] for c in partial["candidates"]] == [ctx["repo_b"]]

    exhausted = await adapter.route(session, exclude_repository_ids={ctx["repo_a"], ctx["repo_b"]})
    assert exhausted["router_version"] == PINNED_ROUTER_VERSION
    assert exhausted["candidates"] == []
    router.route.assert_not_awaited()

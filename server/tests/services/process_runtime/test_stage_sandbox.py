"""蓝图环节单跑层（stage_sandbox）测试。

守四件事（.planning/quick/20260806-blueprint-stage-runner/DESIGN.md）：

1. **ignore_pin**：项目有手动绑定时默认固定路由短路不变；``ignore_pin=True`` 绕过短路
   走完整自动路由（对比「人工绑定 vs 自动路由」的能力测试口）。
2. **route 单跑装配**：stub session 的 ``stage_state`` 形状（requirement_spec /
   include_repos / decomposition.project_id）与 adapter 入参透传；project 范围解析。
3. **spec 单跑**：直采功能点 + intent 分类补齐 + 四维打分；打分不可得 fail-closed
   （保守全 1.0 + above_threshold）。
4. **research 沙箱**：indirect 轻量合成闭环（建沙箱会话 → 任务 done → 结论可轮询）；
   创建者之外中性不可见；空仓库集报 ValueError。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from delivery.models import ConvergenceSession, ConvergenceSessionEntrypoint
from services.process_runtime.blueprint_route import BlueprintRouteAdapter
from services.process_runtime.repo_binding_pin import PINNED_ROUTER_VERSION
from services.process_runtime.stage_sandbox import (
    SANDBOX_PROCESS_TYPE,
    aget_research_sandbox,
    arun_route_stage,
    arun_spec_stage,
    astart_research_sandbox,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_DIMENSIONS = ("goal", "boundary", "constraint", "acceptance")


# ── 工厂 ───────────────────────────────────────────────────────────────────


@sync_to_async
def _make_project(*, with_binding: bool) -> dict:
    from initiatives.models import BranchSource, Project, ProjectBranch
    from projects.models import Space
    from repositories.models import IndexStatus, Repository

    space = Space.objects.create(name="S-sandbox")
    project = Project.objects.create(space=space, name="P-sandbox")
    repo = Repository.objects.create(
        name="repo-sandbox",
        git_url="https://example.com/sandbox.git",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )
    space.repositories.add(repo)
    if with_binding:
        ProjectBranch.objects.create(
            project=project, repository=repo, branch_name="feature/x", source=BranchSource.MANUAL
        )
    return {"project_id": str(project.id), "repo_id": str(repo.id)}


def _spec() -> dict:
    return {
        "goal": [{"block_id": "blk_goal", "type": "paragraph", "text": "登录页改造"}],
        "feature_points": [{"id": "fp_1", "title": "登录页", "intent": "brownfield"}],
    }


async def _make_blueprint_session(project_id: str) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="route",
        stage_state={
            "blueprint": {"requirement_spec": _spec()},
            "decomposition": {"requirement_text": "登录页改造", "project_id": project_id},
        },
    )


# ── ignore_pin ─────────────────────────────────────────────────────────────


async def test_route_adapter_ignore_pin_bypasses_binding() -> None:
    """默认固定路由短路不变；ignore_pin=True 时走自动路由（路由器被调）。"""
    ctx = await _make_project(with_binding=True)
    router = SimpleNamespace(
        route=AsyncMock(
            return_value=SimpleNamespace(
                candidates=[], router_version="v2-test", auto_selected=False
            )
        )
    )
    session = await _make_blueprint_session(ctx["project_id"])
    adapter = BlueprintRouteAdapter(router=router)

    pinned = await adapter.route(session)
    router.route.assert_not_awaited()
    assert pinned["router_version"] == PINNED_ROUTER_VERSION
    assert [c["repository_id"] for c in pinned["candidates"]] == [ctx["repo_id"]]

    with (
        patch(
            "services.process_runtime.initiative_profile.build_profile",
            new=AsyncMock(
                return_value={"status": "ok", "profile": {"change_kind": "brownfield"}, "degrade_reason": ""}
            ),
        ),
        patch(
            "services.process_runtime.team_gate.filter_indexed_repository_ids",
            new=AsyncMock(return_value=[ctx["repo_id"]]),
        ),
    ):
        bypassed = await adapter.route(session, ignore_pin=True)
    router.route.assert_awaited_once()
    assert bypassed["router_version"] == "v2-test"


# ── route 单跑装配 ─────────────────────────────────────────────────────────


class _RecordingRouteAdapter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def route(self, session, *, exclude_repository_ids=None, ignore_pin=False):
        self.calls.append(
            {
                "session": session,
                "exclude": exclude_repository_ids,
                "ignore_pin": ignore_pin,
            }
        )
        return {"router_version": "stub", "candidates": []}


async def test_arun_route_stage_seeds_stub_session() -> None:
    """stage_state 装配（spec / include_repos / decomposition）与入参透传。"""
    adapter = _RecordingRouteAdapter()
    include = "11111111-1111-1111-1111-111111111111"
    exclude = "22222222-2222-2222-2222-222222222222"
    summary = await arun_route_stage(
        requirement_text="做一个登录页",
        include_repository_ids=[include],
        exclude_repository_ids=[exclude],
        ignore_pin=True,
        route_adapter=adapter,
    )
    assert summary["router_version"] == "stub"
    call = adapter.calls[0]
    session = call["session"]
    assert session.stage_state["requirement_spec"]["goal"] == "做一个登录页"
    assert session.stage_state["include_repos"] == [include]
    assert "decomposition" not in session.stage_state
    assert call["exclude"] == {exclude}
    assert call["ignore_pin"] is True


async def test_arun_route_stage_resolves_project_scope() -> None:
    """未显式给候选范围时按 project 所属 space 仓库集收窄，并带 project_id 供 pin 解析。"""
    ctx = await _make_project(with_binding=False)
    adapter = _RecordingRouteAdapter()
    await arun_route_stage(
        requirement_text="登录页改造",
        project_id=ctx["project_id"],
        route_adapter=adapter,
    )
    session = adapter.calls[0]["session"]
    assert session.stage_state["include_repos"] == [ctx["repo_id"]]
    assert session.decomposition == {"project_id": ctx["project_id"]}


async def test_arun_route_stage_accepts_upstream_spec() -> None:
    """显式 requirement_spec（上游产物）优先于 requirement_text。"""
    adapter = _RecordingRouteAdapter()
    include = "11111111-1111-1111-1111-111111111111"
    await arun_route_stage(
        requirement_spec=_spec(),
        include_repository_ids=[include],
        route_adapter=adapter,
    )
    session = adapter.calls[0]["session"]
    assert session.stage_state["requirement_spec"] == _spec()


# ── stub session 的发起用户（历史分量按 created_by 做权限 fail-closed）──────


async def test_stub_session_exposes_created_by_from_initiated_user() -> None:
    """``initiated_by_user_id`` 必须能经 ``session.created_by`` 解析成真实 User。

    历史分量读的是 ``session.created_by``；stub 曾不定义该属性 ⇒ AttributeError 被
    调用方宽 except 吞成 ``retrieval_error``——「没有发起用户」伪装成「检索出错」，
    把 ``no_acting_user`` 这个专门的降级取值架空。
    """
    user = await _make_user("sandbox-actor")
    adapter = _RecordingRouteAdapter()
    # 显式 include 越过漏斗 missing_team 短路，专注验证 created_by 绑定。
    await arun_route_stage(
        requirement_text="登录页改造",
        include_repository_ids=["11111111-1111-1111-1111-111111111111"],
        initiated_by_user_id=str(user.id),
        route_adapter=adapter,
    )
    session = adapter.calls[0]["session"]
    assert str(session.created_by_id) == str(user.id)
    resolved = await sync_to_async(lambda: session.created_by)()
    assert resolved is not None
    assert str(resolved.id) == str(user.id)


async def test_stub_session_created_by_is_none_without_initiated_user() -> None:
    """无发起用户 → created_by 为 None（落 no_acting_user），绝不伪造 actor 提权。"""
    adapter = _RecordingRouteAdapter()
    await arun_route_stage(
        requirement_text="登录页改造",
        include_repository_ids=["11111111-1111-1111-1111-111111111111"],
        route_adapter=adapter,
    )
    session = adapter.calls[0]["session"]
    assert session.created_by_id is None
    assert await sync_to_async(lambda: session.created_by)() is None


# ── spec 单跑 ──────────────────────────────────────────────────────────────


def _clear_scores() -> dict:
    return {
        "dimensions": {d: {"score": 0.0, "reason": "清晰"} for d in _DIMENSIONS},
        "questions": [],
    }


async def test_arun_spec_stage_provided_points_and_intent_fill() -> None:
    """直采功能点：缺 intent 的点走分类器补齐，已带合法 intent 的点不动。"""

    async def scorer(**kwargs):
        return _clear_scores()

    async def classifier(*, feature_points, session_id=""):
        return {p["id"]: "fix" for p in feature_points}

    result = await arun_spec_stage(
        requirement_text="修复登录闪退",
        feature_points=[
            {"title": "登录闪退修复"},
            {"title": "登录页新增记住我", "intent": "greenfield"},
        ],
        scorer=scorer,
        classifier=classifier,
    )
    assert result["source"] == "provided"
    points = result["requirement_spec"]["feature_points"]
    assert [p["intent"] for p in points] == ["fix", "greenfield"]
    assert result["ambiguity"]["above_threshold"] is False
    assert result["ambiguity"]["weighted_total"] == 0.0
    goal_blocks = result["requirement_spec"]["goal"]
    assert goal_blocks[0]["text"] == "修复登录闪退"


async def test_arun_spec_stage_fail_closed_when_scorer_unavailable() -> None:
    """打分不可得 → 保守全 1.0 + above_threshold=True（fail-closed，与规格门同向）。"""

    async def decomposer(session, text):
        return [{"title": "功能A", "intent": "greenfield"}]

    async def scorer(**kwargs):
        return None

    result = await arun_spec_stage(
        requirement_text="做功能A",
        decomposer=decomposer,
        scorer=scorer,
        classify_intents=False,
    )
    assert result["source"] == "llm"
    ambiguity = result["ambiguity"]
    assert ambiguity["scorer_unavailable"] is True
    assert ambiguity["weighted_total"] == 1.0
    assert ambiguity["above_threshold"] is True
    assert result["requirement_spec"]["feature_points"][0]["title"] == "功能A"


# ── research 沙箱 ──────────────────────────────────────────────────────────


@sync_to_async
def _make_user(username: str):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username=username, password="pw-test-123")


async def test_research_sandbox_light_synthesis_roundtrip() -> None:
    """indirect 轻量合成闭环：沙箱会话 + 任务 done + §7 结论可轮询；非创建者中性不可见。"""
    ctx = await _make_project(with_binding=False)
    owner = await _make_user("sandbox-owner")
    stranger = await _make_user("sandbox-stranger")

    started = await astart_research_sandbox(
        requirement_text="登录页改造",
        repositories=[{"repository_id": ctx["repo_id"], "role": "indirect"}],
        project_id=ctx["project_id"],
        created_by=owner,
        initiated_by_user_id=str(owner.id),
    )
    assert started["dispatched"] == 0
    assert started["synthesized"] == 1
    assert started["degraded"] is False

    session = await ConvergenceSession.objects.aget(id=started["session_id"])
    assert session.process_type == SANDBOX_PROCESS_TYPE
    assert session.entrypoint == ConvergenceSessionEntrypoint.MCP

    result = await aget_research_sandbox(session_id=started["session_id"], user=owner)
    assert result is not None
    assert result["all_terminal"] is True
    task = result["tasks"][0]
    assert task["repository_id"] == ctx["repo_id"]
    assert task["status"] == "done"
    assert task["research"]["fitness"]["verdict"] == "partial"
    assert task["research"]["role_suggestion"] == "indirect"

    # 非创建者 / 非沙箱会话一律 None（中性 404，不泄露存在性）
    assert await aget_research_sandbox(session_id=started["session_id"], user=stranger) is None
    blueprint = await _make_blueprint_session(ctx["project_id"])
    assert await aget_research_sandbox(session_id=str(blueprint.id), user=owner) is None


async def test_research_sandbox_rejects_empty_repositories() -> None:
    owner = await _make_user("sandbox-empty")
    with pytest.raises(ValueError):
        await astart_research_sandbox(
            requirement_text="登录页改造",
            repositories=[{"role": "direct"}],
            created_by=owner,
        )

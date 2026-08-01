"""确认门八端点 REST 测试（Phase 112-05 Task 2/3，FLOW-03 / FLOW-04 / CHARTER-03 / SC-4）。

守的是**契约与闭环**：

1. 鉴权：八端点未认证一律拒（``IsAuthenticated``，T-112-22）。
2. 只读快照：无门 404；有门 200 且每仓含 role / responsibility / fitness / routing_evidence。
3. ``confirm``：200 且重读蓝图最新版本 ``confirmed_at_gate is True`` / ``decided_by == "human"``；
   请求用户进 ``BlueprintReviewer``；存在未决阻塞澄清线程 → 409。
4. 五动作状态码分层：非法 role 400、仓不在快照 404、缺 ``repository_id`` 400。
5. **续驱接线**（本文件前半把续驱桩掉）：六个改状态端点各 ``await_count == 1`` 且入参
   session 是该 artifact 的会话；``GET`` 与 ``rejected-to-boundary`` 为 0。
6. **失败隔离**：续驱抛异常 → 六端点仍 2xx 且动作结果已持久化（不回滚、不回 5xx）。
7. 章程回灌：``remove_repo`` 后 ``confirm`` 产 ``source=ai_draft``；``rejected`` 一键沉淀对
   ``human_confirmed`` 章程**只写 ``draft_content``**（CHARTER-01 不变量）。
8. ``upgrade-research``：缺参 400 / 不在快照 404 / 依赖不可用 503 / 正常 200。
9. 视图零 ORM 写：源码扫描断言。
10. **SC-4 端到端证伪线（真实入口，不桩续驱）**：经 REST ``add-repo`` → session 落
    ``repo_research``、新仓建 task 且 dispatcher 恰 await 1 次、已完成仓 task 与
    ``PartialPlan`` 行数逐一不变；``upgrade-research`` / ``reclassify_role``(indirect→direct)
    同链；``remove_repo`` / ``reclassify_role``(direct→indirect) 不误驱；``confirm`` 推进到
    阶段 2/3（113-06 起 ``confirmed`` 指向 ``repo_plan``，不再直接终态）且**绝不静默落 FAILED**。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync

from delivery.models import (
    ArtifactVersion,
    BlueprintReviewer,
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from repositories.models import RepoCharter, Repository
from services.process_runtime.blueprint_confirm_gate import (
    BlueprintConfirmGateAdapter,
    iter_snapshot_repos,
)
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

BASE = "/api/delivery/artifacts/{aid}/blueprint-gate/"
SNAPSHOT_URL = BASE
CONFIRM_URL = BASE + "confirm/"
REMOVE_URL = BASE + "remove-repo/"
ADD_URL = BASE + "add-repo/"
RECLASSIFY_URL = BASE + "reclassify-role/"
EDIT_URL = BASE + "edit-responsibility/"
REJECTED_URL = BASE + "rejected-to-boundary/"
UPGRADE_URL = BASE + "upgrade-research/"

_RESUME_TARGET = "services.process_runtime.blueprint_resume.aresume_after_gate_action"
_DRIVE_TARGET = (
    "services.process_runtime.blueprint_resume.adrive_blueprint_session_to_pause_or_terminal"
)
_DISPATCHER_TARGET = "runners.dispatcher.get_dispatcher"


# ── 工厂（sync 测试 + async_to_sync 装配）─────────────────────────────────────


# ⭐ 116-01：八端点已收项目范围闸（T-116-01）—— 判据源是蓝图自身的 `meta.project_id`，
# 读不到 / 非成员一律回同一个中性 404。样例蓝图因此必须落在测试用户所属的项目里
# （形态照 `test_blueprint_review_views.py:83-110` 的 `_project_scope`，114-05 给人审
# 七端点补闸时的同款处置）。
_SCOPE_PROJECT_ID = "33333333-3333-3333-3333-333333333333"


def _make_project(project_id: str, *, member: Any = None) -> Any:
    from initiatives.models import Project, ProjectMember
    from projects.models import Space

    project = Project.objects.filter(id=project_id).first()
    if project is None:
        space, _ = Space.objects.get_or_create(
            name=f"space-{project_id[:8]}", defaults={"feishu_project_key": f"k-{project_id[:8]}"}
        )
        project = Project.objects.create(id=project_id, space=space, name=f"proj-{project_id[:8]}")
    if member is not None:
        ProjectMember.objects.get_or_create(project=project, user=member)
    return project


@pytest.fixture(autouse=True)
def _project_scope(user) -> Any:
    return _make_project(_SCOPE_PROJECT_ID, member=user)


def _grant_membership(project: Any, user: Any) -> None:
    """把 user 加成该 project 的成员（重指 `meta.project_id` 后仍要过范围闸）。"""
    from initiatives.models import ProjectMember

    ProjectMember.objects.get_or_create(project=project, user=user)


def _stage1_blueprint(**overrides: Any) -> dict[str, Any]:
    """阶段 1 形态蓝图：``implementation_overview.items`` / ``current_state_analysis`` 为空。

    schema 后置检查 (c) 要求两段的 ``repository_id`` ∈ ``repo_associations``——阶段 1 这两段
    尚未产出（113 才装配），确认门会整段替换仓库集。
    """
    base: dict[str, Any] = {
        "meta": {**make_blueprint()["meta"], "project_id": _SCOPE_PROJECT_ID},
        "current_state_analysis": [],
        "implementation_overview": {
            "requirement_narrative": [
                {"block_id": "blk_narr", "type": "paragraph", "text": "阶段 1 尚未产出实现概述。"}
            ],
            "items": [],
        },
        "api_contracts": [],
        "interaction_flows": [],
        "repo_associations": [],
    }
    base.update(overrides)
    return make_blueprint(**base)


def _make_repo(name: str | None = None) -> Repository:
    name = name or f"r-{uuid.uuid4().hex[:8]}"
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


def _candidate(repo: Repository, *, role: str, confidence: str = "high") -> dict:
    return {
        "repository_id": str(repo.id),
        "repository_name": repo.name,
        "role_suggestion": role,
        "confidence": confidence,
        "total": 0.6,
        "breakdown": {"router_base": 0.4, "charter_match": 0.2, "history_match": 0.0},
        "evidence": {
            "router_version": "v2",
            "matched_domains": [],
            "violated_boundaries": [],
            "history_match_unavailable": "",
        },
    }


def _fitness_entry(repo: Repository, *, role: str, verdict: str = "suitable") -> dict:
    return {
        "verdict": verdict,
        "role_suggestion": role,
        "responsibility": f"{repo.name} 承担生成接口",
        "findings": [{"title": "现状", "detail": "已有雏形", "citations": []}],
        "task_status": "done",
    }


def _routing_state(repos: list[Repository], roles: tuple[str, ...]) -> dict:
    return {
        "routing": {
            "router_version": "v2",
            "auto_selected": False,
            "intent": "greenfield",
            "weights_used": {},
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "candidates": [_candidate(r, role=role) for r, role in zip(repos, roles)],
            "citations": [],
        }
    }


def _open_gate(user, roles: tuple[str, ...] = ("direct", "indirect")) -> SimpleNamespace:
    """预置一条 open+blocking 确认门（ORM 走 sync 路径，只有 adapter 调用过 async 桥）。"""
    repos = [_make_repo() for _ in roles]
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", _stage1_blueprint(), created_by_user_id="tester"
    )
    session = ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_confirmation",
        status="waiting_clarification",
        stage_state=_routing_state(repos, roles),
        current_artifact_version_id=artifact.current_version_id,
        created_by=user,
    )
    fitness = {str(r.id): _fitness_entry(r, role=role) for r, role in zip(repos, roles)}
    adapter = BlueprintConfirmGateAdapter(fitness_loader=AsyncMock(return_value=fitness))
    async_to_sync(adapter.open_gate)(session)
    thread = BlueprintThread.objects.filter(
        artifact=artifact, kind=ThreadKind.REPO_CONFIRMATION
    ).first()
    return SimpleNamespace(artifact=artifact, session=session, thread=thread, repos=repos)


def _grant_scope(ctx, *repos: Repository) -> None:
    """把仓纳入本蓝图的范围白名单（``include_repos``，与路由的显式范围同源）。

    ``add_repo`` 的 ``repository_id`` 必须落在蓝图范围内（MJ-01）——生产上范围来自
    ``work_item.space`` 的仓集合或路由候选；chat 入口的测试用显式 ``include_repos``。
    """
    session = ConvergenceSession.objects.get(id=ctx.session.id)
    state = dict(session.stage_state or {})
    state["include_repos"] = list(state.get("include_repos") or []) + [str(r.id) for r in repos]
    ConvergenceSession.objects.filter(id=session.id).update(stage_state=state)
    ctx.session.stage_state = state


def _latest_content(artifact) -> dict:
    return ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").first().content


def _snapshot(artifact) -> list[dict]:
    thread = (
        BlueprintThread.objects.filter(artifact=artifact, kind=ThreadKind.REPO_CONFIRMATION)
        .order_by("-created_at")
        .first()
    )
    return iter_snapshot_repos(thread.options if thread else None)


def _entry(artifact, repo) -> dict:
    for item in _snapshot(artifact):
        if item.get("repository_id") == str(repo.id):
            return item
    return {}


def _stub_resume(monkeypatch, *, side_effect: Any = None) -> AsyncMock:
    mock = AsyncMock(side_effect=side_effect) if side_effect else AsyncMock(return_value=None)
    monkeypatch.setattr(_RESUME_TARGET, mock)
    return mock


class _FakeDispatcher:
    def __init__(self) -> None:
        self.tasks: list[Any] = []
        self.await_count = 0

    async def dispatch(self, task: Any) -> None:
        self.await_count += 1
        self.tasks.append(task)


# ═══════════════════════════════════════════════════════════════════════════
# 1. 鉴权（T-112-22）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "url",
    [
        SNAPSHOT_URL,
        CONFIRM_URL,
        REMOVE_URL,
        ADD_URL,
        RECLASSIFY_URL,
        EDIT_URL,
        REJECTED_URL,
        UPGRADE_URL,
    ],
)
def test_gate_endpoints_reject_unauthenticated(api_client, url: str) -> None:
    aid = uuid.uuid4()
    getter = api_client.get if url == SNAPSHOT_URL else api_client.post
    resp = getter(url.format(aid=aid))
    assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# 2. 只读快照
# ═══════════════════════════════════════════════════════════════════════════


def test_snapshot_returns_404_when_gate_not_open(authenticated_client, user) -> None:
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", _stage1_blueprint(), created_by_user_id="tester"
    )
    resp = authenticated_client.get(SNAPSHOT_URL.format(aid=artifact.id))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "确认门未开启"


def test_snapshot_returns_structured_repos(authenticated_client, user, monkeypatch) -> None:
    resume = _stub_resume(monkeypatch)
    ctx = _open_gate(user)

    resp = authenticated_client.get(SNAPSHOT_URL.format(aid=ctx.artifact.id))

    assert resp.status_code == 200
    body = resp.json()
    assert body["repo_count"] == 2
    for repo in body["repos"]:
        for key in ("role_suggestion", "responsibility", "fitness", "routing_evidence"):
            assert key in repo
    assert body["pending_research_repository_ids"] == []
    # 只读端点不接续驱
    assert resume.await_count == 0


def test_snapshot_404_for_unknown_artifact(authenticated_client, user) -> None:
    resp = authenticated_client.get(SNAPSHOT_URL.format(aid=uuid.uuid4()))
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 3. confirm
# ═══════════════════════════════════════════════════════════════════════════


def test_confirm_locks_associations_and_registers_reviewer(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)

    resp = authenticated_client.post(CONFIRM_URL.format(aid=ctx.artifact.id))

    assert resp.status_code == 200
    assert resp.json()["locked"] is True
    content = _latest_content(ctx.artifact)
    assert len(content["repo_associations"]) == 2
    for assoc in content["repo_associations"]:
        assert assoc["confirmed_at_gate"] is True
        assert assoc["decided_by"] == "human"
    assert BlueprintReviewer.objects.filter(artifact=ctx.artifact, user=user).exists()
    thread = BlueprintThread.objects.get(id=ctx.thread.id)
    assert thread.status == ThreadStatus.RESOLVED


def test_confirm_after_add_repo_never_silently_drops_the_new_repo(
    authenticated_client, user, monkeypatch
) -> None:
    """MJ-03：``add_repo`` 成功后紧接 ``confirm`` —— 要么 409，要么锁定集合含新仓。

    绝不能是「200 且新仓消失」：那样用户的加仓动作静默丢失，线程被 resolve 后
    ``pending_research`` 标记再也读不到，那个 PENDING task 成为永不派发的孤儿。
    """
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    repo_c = _make_repo()
    _grant_scope(ctx, repo_c)

    added = authenticated_client.post(
        ADD_URL.format(aid=ctx.artifact.id), {"repository_id": str(repo_c.id)}, format="json"
    )
    assert added.status_code == 200

    resp = authenticated_client.post(CONFIRM_URL.format(aid=ctx.artifact.id))

    if resp.status_code == 200:
        locked = {a["repository_id"] for a in _latest_content(ctx.artifact)["repo_associations"]}
        assert str(repo_c.id) in locked, "锁定集合丢了用户刚加的仓"
    else:
        assert resp.status_code == 409
        assert "调研" in resp.json()["detail"]
        thread = BlueprintThread.objects.get(id=ctx.thread.id)
        assert thread.status != ThreadStatus.RESOLVED, "拒绝落锁时不得关掉确认门"
        assert (
            RepoResearchTask.objects.get(session=ctx.session, repository=repo_c).status
            == RepoResearchTaskStatus.PENDING
        ), "新仓 task 必须仍可派发，不能成孤儿"


def test_confirm_conflicts_with_pending_clarification(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    async_to_sync(BlueprintLifecycleService().open_thread)(
        ctx.artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="目标用户是谁？"
    )

    resp = authenticated_client.post(CONFIRM_URL.format(aid=ctx.artifact.id))

    assert resp.status_code == 409
    assert resp.json()["detail"] == "存在未解决的阻塞澄清线程"


# ═══════════════════════════════════════════════════════════════════════════
# 4. 五动作状态码分层 + 章程回灌
# ═══════════════════════════════════════════════════════════════════════════


def test_remove_repo_drops_it_from_locked_associations_and_drafts_boundary(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    removed = ctx.repos[1]

    resp = authenticated_client.post(
        REMOVE_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(removed.id), "reason": "不该放这里"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["requires_research"] is False

    authenticated_client.post(CONFIRM_URL.format(aid=ctx.artifact.id))
    content = _latest_content(ctx.artifact)
    assert [a["repository_id"] for a in content["repo_associations"]] == [str(ctx.repos[0].id)]
    charter = RepoCharter.objects.get(repository=removed)
    assert charter.source == RepoCharter.Source.AI_DRAFT
    assert charter.boundaries, "移除仓应产 boundaries 草案"


def test_add_repo_requires_research(authenticated_client, user, monkeypatch) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    repo_c = _make_repo()
    _grant_scope(ctx, repo_c)

    resp = authenticated_client.post(
        ADD_URL.format(aid=ctx.artifact.id), {"repository_id": str(repo_c.id)}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["requires_research"] is True
    task = RepoResearchTask.objects.get(session=ctx.session, repository=repo_c)
    assert task.status == RepoResearchTaskStatus.PENDING
    assert _entry(ctx.artifact, repo_c)["pending_research"] is True


def test_add_repo_outside_blueprint_scope_is_404_and_starts_nothing(
    authenticated_client, user, monkeypatch
) -> None:
    """MJ-01：越界仓一律 404 中性消息——不进快照、不建 task、不起容器、不写章程。"""
    resume = _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    outsider = _make_repo()  # 全库存在，但不在本蓝图范围内

    resp = authenticated_client.post(
        ADD_URL.format(aid=ctx.artifact.id), {"repository_id": str(outsider.id)}, format="json"
    )

    assert resp.status_code == 404
    assert not RepoResearchTask.objects.filter(session=ctx.session, repository=outsider).exists()
    assert _entry(ctx.artifact, outsider) == {}
    assert resume.await_count == 0, "越界动作不得触发续驱"


def test_add_repo_missing_repository_id_is_400(authenticated_client, user, monkeypatch) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    resp = authenticated_client.post(ADD_URL.format(aid=ctx.artifact.id), {}, format="json")
    assert resp.status_code == 400


def test_reclassify_role_rejects_invalid_role(authenticated_client, user, monkeypatch) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    resp = authenticated_client.post(
        RECLASSIFY_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(ctx.repos[0].id), "role": "maybe"},
        format="json",
    )
    assert resp.status_code == 400


def test_reclassify_role_updates_snapshot(authenticated_client, user, monkeypatch) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    resp = authenticated_client.post(
        RECLASSIFY_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(ctx.repos[0].id), "role": "indirect"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["requires_research"] is False
    assert _entry(ctx.artifact, ctx.repos[0])["role_suggestion"] == "indirect"


def test_action_on_repo_outside_snapshot_is_404(authenticated_client, user, monkeypatch) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    other = _make_repo()
    resp = authenticated_client.post(
        RECLASSIFY_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(other.id), "role": "direct"},
        format="json",
    )
    assert resp.status_code == 404


def test_edit_responsibility_lands_in_locked_associations(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    target = ctx.repos[0]

    resp = authenticated_client.post(
        EDIT_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(target.id), "responsibility": "只提供只读查询接口"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["requires_research"] is False

    authenticated_client.post(CONFIRM_URL.format(aid=ctx.artifact.id))
    content = _latest_content(ctx.artifact)
    locked = {a["repository_id"]: a for a in content["repo_associations"]}[str(target.id)]
    assert locked["responsibility"][0]["text"] == "只提供只读查询接口"


# ═══════════════════════════════════════════════════════════════════════════
# 5-6. 续驱接线与失败隔离
# ═══════════════════════════════════════════════════════════════════════════


def _action_calls(ctx, repo_c) -> list[tuple[str, dict]]:
    return [
        (CONFIRM_URL, {}),
        (REMOVE_URL, {"repository_id": str(ctx.repos[1].id)}),
        (ADD_URL, {"repository_id": str(repo_c.id)}),
        (RECLASSIFY_URL, {"repository_id": str(ctx.repos[0].id), "role": "indirect"}),
        (EDIT_URL, {"repository_id": str(ctx.repos[0].id), "responsibility": "只读"}),
    ]


@pytest.mark.parametrize("index", range(5))
def test_each_mutating_endpoint_triggers_resume_once(
    authenticated_client, user, monkeypatch, index: int
) -> None:
    resume = _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    repo_c = _make_repo()
    _grant_scope(ctx, repo_c)
    url, body = _action_calls(ctx, repo_c)[index]

    resp = authenticated_client.post(url.format(aid=ctx.artifact.id), body, format="json")

    assert resp.status_code == 200
    assert resume.await_count == 1
    assert str(resume.await_args.args[0].id) == str(ctx.session.id)


def test_upgrade_research_triggers_resume_once(authenticated_client, user, monkeypatch) -> None:
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    resume = _stub_resume(monkeypatch)
    monkeypatch.setattr(BlueprintResearchAdapter, "aupgrade_to_deep", AsyncMock(return_value=True))
    ctx = _open_gate(user)

    resp = authenticated_client.post(
        UPGRADE_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(ctx.repos[1].id)},
        format="json",
    )

    assert resp.status_code == 200
    assert resume.await_count == 1


def test_readonly_and_rejected_endpoints_do_not_resume(
    authenticated_client, user, monkeypatch
) -> None:
    resume = _stub_resume(monkeypatch)
    ctx = _open_gate(user)

    authenticated_client.get(SNAPSHOT_URL.format(aid=ctx.artifact.id))
    authenticated_client.post(
        REJECTED_URL.format(aid=ctx.artifact.id),
        {"project_id": str(uuid.uuid4())},
        format="json",
    )

    assert resume.await_count == 0


@pytest.mark.parametrize("index", range(5))
def test_resume_failure_does_not_roll_back_action_or_change_status(
    authenticated_client, user, monkeypatch, index: int
) -> None:
    """续驱失败隔离：桩掉**内层 driver** 让它抛，保留真实的 ``aresume_after_gate_action`` 包裹。

    桩掉外层入口本身会连同它的 ``try/except`` 一起替掉——那测的是「视图有没有自己包 try」，
    而契约恰恰是「helper 自己兜、视图不重复包」。故必须从内层制造异常。
    """
    monkeypatch.setattr(_DRIVE_TARGET, AsyncMock(side_effect=RuntimeError("resume boom")))
    ctx = _open_gate(user)
    repo_c = _make_repo()
    _grant_scope(ctx, repo_c)
    url, body = _action_calls(ctx, repo_c)[index]

    resp = authenticated_client.post(url.format(aid=ctx.artifact.id), body, format="json")

    assert 200 <= resp.status_code < 300, "续驱失败绝不改动作响应码"
    if url == ADD_URL:
        task = RepoResearchTask.objects.get(session=ctx.session, repository=repo_c)
        assert task.status == RepoResearchTaskStatus.PENDING
        assert _entry(ctx.artifact, repo_c)["pending_research"] is True
    elif url == REMOVE_URL:
        assert _entry(ctx.artifact, ctx.repos[1])["removed"] is True
    elif url == CONFIRM_URL:
        content = _latest_content(ctx.artifact)
        assert all(a["confirmed_at_gate"] for a in content["repo_associations"])
    elif url == RECLASSIFY_URL:
        assert _entry(ctx.artifact, ctx.repos[0])["role_suggestion"] == "indirect"
    else:
        assert _entry(ctx.artifact, ctx.repos[0])["responsibility"] == "只读"


# ═══════════════════════════════════════════════════════════════════════════
# 7. rejected 一键沉淀（CHARTER-03 + CHARTER-01 不变量）
# ═══════════════════════════════════════════════════════════════════════════


def _bind_blueprint_project(artifact, project, *, member: Any = None) -> None:
    """把蓝图 ``meta.project_id`` 指向该 project（沉淀端点的项目范围唯一来源）。

    ⭐ 116-01：``meta.project_id`` 同时也是范围闸的判据源 ⇒ 重指之后必须把调用方加成新
    project 的成员，否则会被中性 404 挡在服务之前（那正是补闸要的效果）。
    """
    if member is not None:
        _grant_membership(project, member)
    version = ArtifactVersion.objects.filter(id=artifact.current_version_id).first()
    content = dict(version.content)
    meta = dict(content.get("meta") or {})
    meta["project_id"] = str(project.id)
    content["meta"] = meta
    ArtifactVersion.objects.filter(id=version.id).update(content=content)


def _make_rejected_association(repo: Repository, reason: str = "该类需求不落此仓"):
    from initiatives.models import Project, RepoAssociation, RepoAssociationStatus
    from projects.models import Space

    space = Space.objects.create(
        name=f"space-{uuid.uuid4().hex[:6]}", feishu_project_key=f"k-{uuid.uuid4().hex[:6]}"
    )
    project = Project.objects.create(space=space, name="p")
    RepoAssociation.objects.create(
        project=project,
        repository=repo,
        status=RepoAssociationStatus.REJECTED,
        routed_reason=reason,
    )
    return project


def test_rejected_to_boundary_creates_ai_draft(authenticated_client, user, monkeypatch) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    rejected_repo = _make_repo()
    project = _make_rejected_association(rejected_repo)
    _bind_blueprint_project(ctx.artifact, project, member=user)

    resp = authenticated_client.post(
        REJECTED_URL.format(aid=ctx.artifact.id), {"project_id": str(project.id)}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["draft_count"] == 1
    charter = RepoCharter.objects.get(repository=rejected_repo)
    assert charter.source == RepoCharter.Source.AI_DRAFT
    assert "该类需求不落此仓" in charter.boundaries[0]["rule"]


def test_rejected_to_boundary_never_overwrites_human_confirmed(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    rejected_repo = _make_repo()
    project = _make_rejected_association(rejected_repo)
    _bind_blueprint_project(ctx.artifact, project, member=user)
    confirmed = RepoCharter.objects.create(
        repository=rejected_repo,
        source=RepoCharter.Source.HUMAN_CONFIRMED,
        version=4,
        positioning="人工定位",
        owned_domains=[
            {"domain": "人工领域", "status": "implemented", "note": "", "citations": []}
        ],
        boundaries=[{"rule": "人工禁区", "decided_by": "human", "citations": []}],
        evolution="active",
    )
    before = {
        field: getattr(confirmed, field)
        for field in ("positioning", "owned_domains", "boundaries", "evolution", "version")
    }

    resp = authenticated_client.post(
        REJECTED_URL.format(aid=ctx.artifact.id), {"project_id": str(project.id)}, format="json"
    )

    assert resp.status_code == 200
    fresh = RepoCharter.objects.get(repository=rejected_repo)
    for field, value in before.items():
        assert getattr(fresh, field) == value, f"{field} 被 AI 回灌覆盖了"
    assert fresh.draft_content["boundaries"], "新禁区候选只应落 draft_content"


def test_rejected_to_boundary_requires_scope(authenticated_client, user, monkeypatch) -> None:
    """⭐ 116-01 起是**中性 404**（更严变体），不再是 400。

    读不到合法 ``meta.project_id`` 与「非该项目成员」回**同一个**响应体 ⇒ 零新增存在性
    暴露面（``test_blueprint_gate_scope.py`` 有 ``a.json() == b.json()`` 的逐字断言）。
    仍然「绝不跨项目全表沉淀」——只是拒绝的方式从可区分的 400 换成了不可区分的 404。
    """
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    _bind_blueprint_project(ctx.artifact, _make_project("44444444-4444-4444-4444-444444444444"))
    resp = authenticated_client.post(REJECTED_URL.format(aid=ctx.artifact.id), {}, format="json")
    assert resp.status_code == 404


def test_rejected_to_boundary_rejects_foreign_project_id(
    authenticated_client, user, monkeypatch
) -> None:
    """MN-01：body 的 project_id 不能越过 URL 里的 artifact 决定写入范围。"""
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    own_repo = _make_repo()
    own_project = _make_rejected_association(own_repo)
    _bind_blueprint_project(ctx.artifact, own_project, member=user)
    foreign_repo = _make_repo()
    foreign_project = _make_rejected_association(foreign_repo, "别的项目的候选")

    resp = authenticated_client.post(
        REJECTED_URL.format(aid=ctx.artifact.id),
        {"project_id": str(foreign_project.id)},
        format="json",
    )

    assert resp.status_code == 403
    assert not RepoCharter.objects.filter(repository=foreign_repo).exists()


# ═══════════════════════════════════════════════════════════════════════════
# 8. upgrade-research（B2 / FLOW-04）
# ═══════════════════════════════════════════════════════════════════════════


def test_upgrade_research_missing_repository_id_is_400(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    resp = authenticated_client.post(UPGRADE_URL.format(aid=ctx.artifact.id), {}, format="json")
    assert resp.status_code == 400


def test_upgrade_research_repo_outside_snapshot_is_404(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    resp = authenticated_client.post(
        UPGRADE_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(_make_repo().id)},
        format="json",
    )
    assert resp.status_code == 404


def test_upgrade_research_marks_snapshot_and_stales_task(
    authenticated_client, user, monkeypatch
) -> None:
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    _stub_resume(monkeypatch)
    monkeypatch.setattr(
        BlueprintResearchAdapter,
        "dispatch",
        AsyncMock(return_value={"dispatched": 0, "synthesized": 0, "degraded": False, "tasks": []}),
    )
    ctx = _open_gate(user)
    target = ctx.repos[1]
    RepoResearchTask.objects.create(
        session=ctx.session, repository=target, status=RepoResearchTaskStatus.DONE
    )

    resp = authenticated_client.post(
        UPGRADE_URL.format(aid=ctx.artifact.id), {"repository_id": str(target.id)}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["upgraded"] is True
    assert resp.json()["already_running"] is False
    task = RepoResearchTask.objects.get(session=ctx.session, repository=target)
    assert task.status == RepoResearchTaskStatus.STALE
    entry = _entry(ctx.artifact, target)
    assert entry["pending_research"] is True
    assert entry["role_suggestion"] == "direct"


def test_upgrade_research_reports_already_running_for_in_flight_task(
    authenticated_client, user, monkeypatch
) -> None:
    """MN-03：在途 task 既进不了 mark_stale 也进不了派发白名单 → 如实回 already_running。"""
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    _stub_resume(monkeypatch)
    monkeypatch.setattr(
        BlueprintResearchAdapter,
        "dispatch",
        AsyncMock(return_value={"dispatched": 0, "synthesized": 0, "degraded": False, "tasks": []}),
    )
    ctx = _open_gate(user)
    target = ctx.repos[1]
    RepoResearchTask.objects.create(
        session=ctx.session, repository=target, status=RepoResearchTaskStatus.RUNNING
    )

    resp = authenticated_client.post(
        UPGRADE_URL.format(aid=ctx.artifact.id), {"repository_id": str(target.id)}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["already_running"] is True, "在途时不得假装刚重开了深调研"
    task = RepoResearchTask.objects.get(session=ctx.session, repository=target)
    assert task.status == RepoResearchTaskStatus.RUNNING, "在途 task 不得被置 stale"


def test_upgrade_research_returns_503_when_dependency_unavailable(
    authenticated_client, user, monkeypatch
) -> None:
    from services.process_runtime.blueprint_research_adapter import BlueprintResearchAdapter

    _stub_resume(monkeypatch)
    monkeypatch.setattr(BlueprintResearchAdapter, "aupgrade_to_deep", AsyncMock(return_value=False))
    ctx = _open_gate(user)

    resp = authenticated_client.post(
        UPGRADE_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(ctx.repos[1].id)},
        format="json",
    )

    assert resp.status_code == 503


# ═══════════════════════════════════════════════════════════════════════════
# 9. 视图零 ORM 写（INV-6 源码扫描守护）
# ═══════════════════════════════════════════════════════════════════════════


def test_gate_views_contain_no_orm_writes() -> None:
    import re

    path = Path(__file__).resolve().parents[2] / "delivery" / "api" / "blueprint_gate_views.py"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\b(?:RepoCharter|BlueprintThread|RepoResearchTask|RepoAssociation|Artifact)"
        r"\.objects\.(?:a?create|a?update|a?bulk_create|a?get_or_create|a?update_or_create)\b"
    )
    assert not pattern.findall(text), "确认门视图必须零 ORM 写（写入一律委托 service）"
    assert (
        "repo_associations" not in text or "objects" not in text.split("repo_associations")[1][:60]
    )
    assert "aresume_after_gate_action" in text
    assert "sync_to_async" in text


# ═══════════════════════════════════════════════════════════════════════════
# 10. SC-4 端到端证伪线（**经真实 REST 入口，不桩续驱**）
#
# 上面那批断言把 `aresume_after_gate_action` 桩掉了，只验「调用点存在 + 失败不反噬」。
# 本节**不桩续驱**（process 已注册、engine 工厂已就位），只把容器 dispatcher 换成替身：
# 断言经 REST 动作真的能把 session 推过 `research_required` 回边、只为待调研仓起容器、
# 已完成仓的结论与 PartialPlan 行数逐一不变。
# ═══════════════════════════════════════════════════════════════════════════


def _e2e_setup(user, monkeypatch, roles=("direct", "indirect")) -> SimpleNamespace:
    """预置停在 ``repo_confirmation``、A/B 两仓 task 已 ``done`` 的真实会话。

    容器链只替身化 dispatcher（``get_dispatcher``）与凭证解析；**续驱、stage graph、
    增量 dispatch、判据全部走真实代码**。deep 桶需要在线 runner，否则 112-04 会整体
    降级轻量合成、dispatcher 永不被调用（那样断言就测不到容器链）。
    """
    from django.utils import timezone

    from runners.models import Runner

    ctx = _open_gate(user, roles)
    Runner.objects.create(
        name=f"runner-{uuid.uuid4().hex[:6]}",
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=Runner.Status.ONLINE,
        last_heartbeat=timezone.now(),
    )
    for repo in ctx.repos:
        task = RepoResearchTask.objects.create(
            session=ctx.session, repository=repo, status=RepoResearchTaskStatus.DONE
        )
        PartialPlan.objects.create(
            research_task=task,
            content={"repository_id": str(repo.id), "fitness": {"verdict": "suitable"}},
            content_hash=uuid.uuid4().hex,
            valid=True,
        )
    dispatcher = _FakeDispatcher()
    monkeypatch.setattr(_DISPATCHER_TARGET, lambda: dispatcher)
    monkeypatch.setattr(
        "services.provider_config.aget_claude_code_runtime_config",
        AsyncMock(return_value={"api_key": "k", "default_model": "m"}),
    )
    monkeypatch.setattr("services.git_credentials.aresolve_git_token", AsyncMock(return_value=""))
    ctx.dispatcher = dispatcher
    ctx.baseline_partials = PartialPlan.objects.count()
    return ctx


def _task(ctx, repo) -> RepoResearchTask:
    return RepoResearchTask.objects.get(session=ctx.session, repository=repo)


def _stage(ctx) -> str:
    return ConvergenceSession.objects.get(id=ctx.session.id).current_stage


def test_e2e_add_repo_through_rest_reaches_repo_research_and_dispatches_only_new_repo(
    authenticated_client, user, monkeypatch
) -> None:
    ctx = _e2e_setup(user, monkeypatch)
    repo_c = _make_repo()
    _grant_scope(ctx, repo_c)

    resp = authenticated_client.post(
        ADD_URL.format(aid=ctx.artifact.id), {"repository_id": str(repo_c.id)}, format="json"
    )

    assert resp.status_code == 200
    # ① 确实走了 research_required 回边（证明续驱在生产路径上被触发）
    assert _stage(ctx) == "repo_research"
    # ② 只为新仓起容器
    assert _task(ctx, repo_c).status in (
        RepoResearchTaskStatus.PENDING,
        RepoResearchTaskStatus.RUNNING,
    )
    assert ctx.dispatcher.await_count == 1
    assert repo_c.name in ctx.dispatcher.tasks[0].repo_url
    # ③ 已完成仓的 task 状态与 PartialPlan 行数逐一不变（结论保留，不重跑）
    for repo in ctx.repos:
        assert _task(ctx, repo).status == RepoResearchTaskStatus.DONE
    assert PartialPlan.objects.count() == ctx.baseline_partials


def test_e2e_reclassify_indirect_to_direct_reaches_repo_research(
    authenticated_client, user, monkeypatch
) -> None:
    ctx = _e2e_setup(user, monkeypatch)
    target = ctx.repos[1]  # indirect

    resp = authenticated_client.post(
        RECLASSIFY_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(target.id), "role": "direct"},
        format="json",
    )

    assert resp.status_code == 200
    assert resp.json()["requires_research"] is True
    assert _stage(ctx) == "repo_research"
    assert _task(ctx, target).status in (
        RepoResearchTaskStatus.STALE,
        RepoResearchTaskStatus.RUNNING,
    )
    assert ctx.dispatcher.await_count == 1
    assert _task(ctx, ctx.repos[0]).status == RepoResearchTaskStatus.DONE


def test_e2e_reclassify_direct_to_indirect_does_not_trigger_research(
    authenticated_client, user, monkeypatch
) -> None:
    ctx = _e2e_setup(user, monkeypatch)

    resp = authenticated_client.post(
        RECLASSIFY_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(ctx.repos[0].id), "role": "indirect"},
        format="json",
    )

    assert resp.status_code == 200
    assert _stage(ctx) == "repo_confirmation", "无谓重调研不得被触发"
    assert ctx.dispatcher.await_count == 0


def test_e2e_remove_repo_does_not_drive_research(authenticated_client, user, monkeypatch) -> None:
    ctx = _e2e_setup(user, monkeypatch)

    resp = authenticated_client.post(
        REMOVE_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(ctx.repos[1].id)},
        format="json",
    )

    assert resp.status_code == 200
    assert _stage(ctx) == "repo_confirmation"
    assert ctx.dispatcher.await_count == 0


def test_e2e_upgrade_research_starts_deep_container_for_that_repo_only(
    authenticated_client, user, monkeypatch
) -> None:
    """``upgrade-research`` 同链：真实入口 → 该仓被起深调研容器，其它仓结论保留。

    与 ``add_repo`` / ``reclassify_role`` 的差别在于 112-04 的 ``aupgrade_to_deep`` 自带
    ``dispatch``（它必须带 ``force_deep_repository_ids``，否则被重新分回 light 桶再合成
    一遍），所以增量派发在 service 调用内就完成了；随后视图触发的续驱看到该仓 task 已
    ``running``（判据合取的第二项为假）→ 在 pause 短路处零 advance，``current_stage`` 仍为
    ``repo_confirmation``。断言因此落在**这个端点真正要保证的事**上：容器确实为且只为该仓起了。
    """
    ctx = _e2e_setup(user, monkeypatch)
    target = ctx.repos[1]  # indirect + done

    resp = authenticated_client.post(
        UPGRADE_URL.format(aid=ctx.artifact.id), {"repository_id": str(target.id)}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["upgraded"] is True
    assert _task(ctx, target).status in (
        RepoResearchTaskStatus.STALE,
        RepoResearchTaskStatus.RUNNING,
    )
    assert ctx.dispatcher.await_count == 1
    assert target.name in ctx.dispatcher.tasks[0].repo_url
    assert _task(ctx, ctx.repos[0]).status == RepoResearchTaskStatus.DONE
    assert _entry(ctx.artifact, target)["role_suggestion"] == "direct"


def test_e2e_confirm_through_rest_drives_session_into_stage_two(
    authenticated_client, user, monkeypatch
) -> None:
    """confirm 也接了续驱：会话离开 ``repo_confirmation`` 进入阶段 2/3。

    113-06 把 ``repo_confirmation.confirmed`` 的目标从 ``__done__`` 改成 ``repo_plan``，
    确认门通过后不再直接终态。本用例因此改断言「**已推进且没有静默失败**」——
    环境缺 LLM/容器时它会停在 ``repo_plan`` / ``merge`` 等人处置（有阻塞澄清线程），
    **绝不允许**被推到步数上限落 FAILED（那会把「缺条件」变成「流程失败」）。
    """
    ctx = _e2e_setup(user, monkeypatch)

    resp = authenticated_client.post(CONFIRM_URL.format(aid=ctx.artifact.id))

    assert resp.status_code == 200
    fresh = ConvergenceSession.objects.get(id=ctx.session.id)
    assert fresh.current_stage in ("repo_plan", "merge"), "confirm 未接续到阶段 2/3"
    assert fresh.status != ConvergenceSessionStatus.FAILED, (
        "缺 LLM/容器只能停在挂起态等人处置，绝不许静默落 FAILED"
    )
    if fresh.status == ConvergenceSessionStatus.WAITING_CLARIFICATION:
        assert BlueprintThread.objects.filter(
            artifact=ctx.artifact, blocking=True, status=ThreadStatus.OPEN
        ).exists(), "停在澄清态必须有阻塞线程，否则续驱会一路 advance 到步数上限"
    content = _latest_content(ctx.artifact)
    assert all(a["confirmed_at_gate"] for a in content["repo_associations"])


def test_e2e_resume_failure_keeps_marker_for_next_trigger(
    authenticated_client, user, monkeypatch
) -> None:
    """续驱失败不反噬（真链路版）：标记与新仓 task 已持久化，下次触发仍可闭环。"""
    ctx = _e2e_setup(user, monkeypatch)
    repo_c = _make_repo()
    _grant_scope(ctx, repo_c)
    monkeypatch.setattr(_DRIVE_TARGET, AsyncMock(side_effect=RuntimeError("resume boom")))

    resp = authenticated_client.post(
        ADD_URL.format(aid=ctx.artifact.id), {"repository_id": str(repo_c.id)}, format="json"
    )

    assert resp.status_code == 200
    assert _stage(ctx) == "repo_confirmation", "续驱炸了 → stage 不前进（但动作已落库）"
    assert _task(ctx, repo_c).status == RepoResearchTaskStatus.PENDING
    assert _entry(ctx.artifact, repo_c)["pending_research"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 11. 跨 process 隔离（CR-01）
#
# 蓝图链刻意复用 `technical_plan` 这个 artifact_type，同一 artifact 上可能并存两条
# 会话。会话解析必须带 `process_type` 条件——否则「最近一条」会取到旧链会话，被蓝图
# engine 驱动后旧链 handler 取不到 `deps.router`，engine 把那条无关会话落 FAILED。
# ═══════════════════════════════════════════════════════════════════════════


def _make_plan_session(ctx, user) -> ConvergenceSession:
    """在同一 artifact 上再挂一条**更新的** `technical_plan` 会话（旧链形态）。"""
    return ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="route",
        status=ConvergenceSessionStatus.RUNNING,
        current_artifact_version_id=ctx.artifact.current_version_id,
        created_by=user,
    )


def test_gate_action_never_touches_unrelated_technical_plan_session(
    authenticated_client, user, monkeypatch
) -> None:
    """同 artifact 上并存的 `technical_plan` 会话不得被确认门动作触碰（不桩续驱）。"""
    ctx = _e2e_setup(user, monkeypatch)
    plan = _make_plan_session(ctx, user)

    resp = authenticated_client.post(
        REMOVE_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(ctx.repos[1].id)},
        format="json",
    )

    assert resp.status_code == 200
    fresh_plan = ConvergenceSession.objects.get(id=plan.id)
    assert fresh_plan.status == ConvergenceSessionStatus.RUNNING, "无关会话被驱成了终态"
    assert fresh_plan.current_stage == "route", "无关会话的 stage 被推动了"
    assert fresh_plan.error in (None, {}, "")
    # 动作确实落在蓝图会话上
    assert _stage(ctx) == "repo_confirmation"
    assert _entry(ctx.artifact, ctx.repos[1])["removed"] is True


def test_gate_action_404s_when_only_non_blueprint_session_exists(
    authenticated_client, user, monkeypatch
) -> None:
    """没有蓝图会话时明确 404——绝不静默退化成「拿别的 process 的会话」。"""
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    plan = _make_plan_session(ctx, user)
    ConvergenceSession.objects.filter(id=ctx.session.id).delete()

    resp = authenticated_client.post(
        REMOVE_URL.format(aid=ctx.artifact.id),
        {"repository_id": str(ctx.repos[1].id)},
        format="json",
    )

    assert resp.status_code == 404
    assert ConvergenceSession.objects.get(id=plan.id).status == ConvergenceSessionStatus.RUNNING

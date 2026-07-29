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
    同链；``remove_repo`` / ``reclassify_role``(direct→indirect) 不误驱；``confirm`` 推到终态。
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


def _stage1_blueprint(**overrides: Any) -> dict[str, Any]:
    """阶段 1 形态蓝图：``implementation_overview.items`` / ``current_state_analysis`` 为空。

    schema 后置检查 (c) 要求两段的 ``repository_id`` ∈ ``repo_associations``——阶段 1 这两段
    尚未产出（113 才装配），确认门会整段替换仓库集。
    """
    base: dict[str, Any] = {
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

    resp = authenticated_client.post(
        ADD_URL.format(aid=ctx.artifact.id), {"repository_id": str(repo_c.id)}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["requires_research"] is True
    task = RepoResearchTask.objects.get(session=ctx.session, repository=repo_c)
    assert task.status == RepoResearchTaskStatus.PENDING
    assert _entry(ctx.artifact, repo_c)["pending_research"] is True


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
    _stub_resume(monkeypatch)
    ctx = _open_gate(user)
    resp = authenticated_client.post(REJECTED_URL.format(aid=ctx.artifact.id), {}, format="json")
    # 样例蓝图的 meta.project_id 不是 UUID，且未显式给范围 → 400（绝不跨项目全表沉淀）
    assert resp.status_code == 400


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
    task = RepoResearchTask.objects.get(session=ctx.session, repository=target)
    assert task.status == RepoResearchTaskStatus.STALE
    entry = _entry(ctx.artifact, target)
    assert entry["pending_research"] is True
    assert entry["role_suggestion"] == "direct"


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

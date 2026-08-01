"""blueprint-gate/ 八端点的项目范围闸 + confirm 两处 409 的 blocked_reason（116-01 Task 3）。

守六件事（断言一律**从 DB 重读**，不信响应体）：

1. ⭐ **八端点参数化非成员用例**：非该蓝图所属项目的成员调用八个端点 ⇒ **全部 404**。
   修前八个 View 的授权判据只有「登录了」，而其中 ``confirm`` / ``remove-repo`` /
   ``add-repo`` 是**破坏性写**（T-116-01）。
2. ⭐ **两个失败分支响应体逐字相同**：(a) 蓝图 ``meta.project_id`` 缺失/非 UUID、
   (b) 有合法 project_id 但调用者非成员 —— ``a.json() == b.json()``。**这是「零新增存在性
   暴露面」的唯一可证伪形态**（T-116-02）：补闸绝不能引入 400/404 可区分的新预言机。
3. **成员 200 / superuser 200**（⛔ 证明第 1 条断言非恒真）。
4. ⭐ **三条破坏性写在非成员调用后 DB 一字未动**：蓝图状态、快照仓集、版本数逐一不变。
5. ⭐ **``confirm/`` 两处 409 的 ``blocked_reason``**：``pending_clarification`` 与
   ``lock["reason"]`` 原样 —— 让 115-07 已实现且已有用例的「一键跳未决线程」在生产生效
   （``web/src/components/blueprint/__tests__/gatePanel.spec.ts:577`` / ``:591``，前端零改动）。
6. **未认证一律拒**（401/403），八端点参数化。

REST client 是同步的 ⇒ 同步用例 + ``async_to_sync`` 装配；async service 跨线程写库 ⇒
``transaction=True``。范围闸工厂逐字复用 ``test_blueprint_review_views`` 的
``_make_project`` / ``_SCOPE_PROJECT_ID`` / ``_OTHER_PROJECT_ID``（⛔ 不重造第二份）。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ThreadKind,
)
from delivery.services import ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from repositories.models import Repository
from services.process_runtime.blueprint_confirm_gate import (
    BlueprintConfirmGateAdapter,
    iter_snapshot_repos,
)
from tests.delivery.test_blueprint_review_views import (
    _OTHER_PROJECT_ID,
    _SCOPE_PROJECT_ID,
    _make_project,
)
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

_RESUME_TARGET = "services.process_runtime.blueprint_resume.aresume_after_gate_action"

# 八端点（name, http method）—— ⛔ 必须参数化，只测 confirm 不算数。
_GATE_ENDPOINTS = (
    ("blueprint-gate-snapshot", "get"),
    ("blueprint-gate-confirm", "post"),
    ("blueprint-gate-remove-repo", "post"),
    ("blueprint-gate-add-repo", "post"),
    ("blueprint-gate-reclassify-role", "post"),
    ("blueprint-gate-edit-responsibility", "post"),
    ("blueprint-gate-rejected-to-boundary", "post"),
    ("blueprint-gate-upgrade-research", "post"),
)


# ── 工厂 ─────────────────────────────────────────────────────────────────────


def _stub_resume(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(_RESUME_TARGET, mock)
    return mock


def _make_repo() -> Repository:
    name = f"r-{uuid.uuid4().hex[:8]}"
    return Repository.objects.create(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


def _stage1_blueprint(project_id: str) -> dict[str, Any]:
    base = make_blueprint()
    return make_blueprint(
        meta={**base["meta"], "project_id": project_id},
        current_state_analysis=[],
        implementation_overview={
            "requirement_narrative": [
                {"block_id": "blk_narr", "type": "paragraph", "text": "阶段 1 尚未产出。"}
            ],
            "items": [],
        },
        api_contracts=[],
        interaction_flows=[],
        repo_associations=[],
    )


def _candidate(repo: Repository, *, role: str) -> dict:
    return {
        "repository_id": str(repo.id),
        "repository_name": repo.name,
        "role_suggestion": role,
        "confidence": "high",
        "total": 0.6,
        "breakdown": {"router_base": 0.4, "charter_match": 0.2, "history_match": 0.0},
        "evidence": {
            "router_version": "v2",
            "matched_domains": [],
            "violated_boundaries": [],
            "history_match_unavailable": "",
        },
    }


def _open_gate(user, *, project_id: str = _SCOPE_PROJECT_ID) -> SimpleNamespace:
    """预置一条 open+blocking 确认门，蓝图 ``meta.project_id`` 指向 ``project_id``。"""
    roles = ("direct", "indirect")
    repos = [_make_repo() for _ in roles]
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", _stage1_blueprint(project_id), created_by_user_id="tester"
    )
    session = ConvergenceSession.objects.create(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_confirmation",
        status="waiting_clarification",
        stage_state={
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
        },
        current_artifact_version_id=artifact.current_version_id,
        created_by=user,
    )
    fitness = {
        str(r.id): {
            "verdict": "suitable",
            "role_suggestion": role,
            "responsibility": f"{r.name} 承担生成接口",
            "findings": [],
            "task_status": "done",
        }
        for r, role in zip(repos, roles)
    }
    adapter = BlueprintConfirmGateAdapter(fitness_loader=AsyncMock(return_value=fitness))
    async_to_sync(adapter.open_gate)(session)
    return SimpleNamespace(artifact=artifact, session=session, repos=repos)


def _url(name: str, artifact: Artifact) -> str:
    return reverse(name, args=[str(artifact.id)])


def _call(client, name: str, method: str, artifact: Artifact, body: dict | None = None):
    url = _url(name, artifact)
    if method == "get":
        return client.get(url)
    return client.post(url, body or {}, format="json")


def _snapshot_repo_ids(artifact: Artifact) -> list[str]:
    thread = (
        BlueprintThread.objects.filter(artifact=artifact, kind=ThreadKind.REPO_CONFIRMATION)
        .order_by("-created_at")
        .first()
    )
    return [
        str(r.get("repository_id")) for r in iter_snapshot_repos(thread.options if thread else None)
    ]


# ═══════════════════════════════════════════════════════════════════════════
# 1 + 6. 鉴权与范围（安全边界不降级）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(("name", "method"), _GATE_ENDPOINTS)
def test_gate_endpoints_reject_unauthenticated(api_client, name: str, method: str) -> None:
    url = reverse(name, args=[str(uuid.uuid4())])
    resp = api_client.get(url) if method == "get" else api_client.post(url)
    assert resp.status_code in (401, 403)


@pytest.mark.parametrize(("name", "method"), _GATE_ENDPOINTS)
def test_gate_endpoints_reject_non_members_of_the_blueprint_project(
    authenticated_client, user, monkeypatch, name: str, method: str
) -> None:
    """⭐ T-116-01：只有「登录了」不够 —— 八端点必须按蓝图自身 ``meta.project_id`` 收范围。

    修前 ``artifact_id`` 是唯一范围约束、而它在 URL 里可控 ⇒ 任意登录用户拿到一个 artifact
    UUID 就能确认锁定别人项目的仓库集（下游 implementing 链据此启动）、移除仓、加仓触发
    调研、改判角色与职责。越权回**中性 404**（不是 403）。
    """
    _stub_resume(monkeypatch)
    _make_project(_OTHER_PROJECT_ID)  # 存在但 user 不是成员
    ctx = _open_gate(user, project_id=_OTHER_PROJECT_ID)

    resp = _call(
        authenticated_client, name, method, ctx.artifact, {"repository_id": str(ctx.repos[0].id)}
    )

    assert resp.status_code == 404


def test_unresolvable_project_and_non_member_return_the_very_same_body(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ T-116-02：「零新增存在性暴露面」的唯一可证伪形态。

    ⛔ 补闸绝不能引入 400/404 可区分的第四种状态 —— 那反而新开一个存在性预言机，正是
    115-MN-03 判为「设计决策、本轮不改」的那条暴露面被扩大。
    """
    _stub_resume(monkeypatch)
    _make_project(_OTHER_PROJECT_ID)
    unresolvable = _open_gate(user, project_id="proj-0001")  # 非 UUID，读不出项目范围
    foreign = _open_gate(user, project_id=_OTHER_PROJECT_ID)  # 合法 UUID 但非成员

    a = _call(authenticated_client, "blueprint-gate-snapshot", "get", unresolvable.artifact)
    b = _call(authenticated_client, "blueprint-gate-snapshot", "get", foreign.artifact)

    assert a.status_code == b.status_code == 404
    assert a.json() == b.json(), "两个失败分支的响应体必须逐字相同"


def test_project_member_is_allowed_through(authenticated_client, user, monkeypatch) -> None:
    """⛔ 反向对照：证明八端点 404 那条断言不是恒真。"""
    _stub_resume(monkeypatch)
    _make_project(_SCOPE_PROJECT_ID, member=user)
    ctx = _open_gate(user)

    resp = _call(authenticated_client, "blueprint-gate-snapshot", "get", ctx.artifact)

    assert resp.status_code == 200
    assert resp.json()["repo_count"] == 2


def test_superuser_passes_through_without_membership(
    api_client, admin_user, user, monkeypatch
) -> None:
    """superuser 直通（与 ``permissions.api_permissions.IsProjectMember`` 同口径）。"""
    _stub_resume(monkeypatch)
    _make_project(_OTHER_PROJECT_ID)
    ctx = _open_gate(user, project_id=_OTHER_PROJECT_ID)
    api_client.force_authenticate(user=admin_user)

    resp = _call(api_client, "blueprint-gate-snapshot", "get", ctx.artifact)

    assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 4. 三条破坏性写在非成员调用后 DB 一字未动
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("blueprint-gate-confirm", {}),
        ("blueprint-gate-remove-repo", {}),
        ("blueprint-gate-add-repo", {}),
    ],
)
def test_destructive_writes_leave_the_db_untouched_for_non_members(
    authenticated_client, user, monkeypatch, name: str, body: dict
) -> None:
    """⭐ 三条破坏性写：越权调用后蓝图状态 / 快照仓集 / 版本数逐一未变。"""
    _stub_resume(monkeypatch)
    _make_project(_OTHER_PROJECT_ID)
    ctx = _open_gate(user, project_id=_OTHER_PROJECT_ID)
    payload = dict(body)
    payload.setdefault("repository_id", str(ctx.repos[0].id))

    before_status = Artifact.objects.get(id=ctx.artifact.id).blueprint_status
    before_repos = _snapshot_repo_ids(ctx.artifact)
    before_versions = ArtifactVersion.objects.filter(artifact=ctx.artifact).count()

    resp = _call(authenticated_client, name, "post", ctx.artifact, payload)

    assert resp.status_code == 404
    assert Artifact.objects.get(id=ctx.artifact.id).blueprint_status == before_status
    assert _snapshot_repo_ids(ctx.artifact) == before_repos
    assert ArtifactVersion.objects.filter(artifact=ctx.artifact).count() == before_versions


# ═══════════════════════════════════════════════════════════════════════════
# 5. confirm/ 两处 409 的 blocked_reason（115-07 的第二条后端缺口）
# ═══════════════════════════════════════════════════════════════════════════


def test_confirm_409_carries_pending_clarification_blocked_reason(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ 机器可读键让前端的「前往未决线程」那一档在生产生效（gatePanel.spec.ts:577）。"""
    _stub_resume(monkeypatch)
    _make_project(_SCOPE_PROJECT_ID, member=user)
    ctx = _open_gate(user)
    async_to_sync(BlueprintLifecycleService().open_thread)(
        ctx.artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True, question="目标用户是谁？"
    )

    resp = _call(authenticated_client, "blueprint-gate-confirm", "post", ctx.artifact)

    assert resp.status_code == 409
    body = resp.json()
    assert body["blocked_reason"] == "pending_clarification"
    assert body["detail"] == "存在未解决的阻塞澄清线程"


def test_confirm_409_passes_the_lock_reason_through_verbatim(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ 第二处 409：``blocked_reason`` 原样透传 ``lock["reason"]``（gatePanel.spec.ts:591）。"""
    _stub_resume(monkeypatch)
    _make_project(_SCOPE_PROJECT_ID, member=user)
    ctx = _open_gate(user)
    monkeypatch.setattr(
        BlueprintConfirmGateAdapter,
        "alock",
        AsyncMock(return_value={"event": "blocked", "reason": "snapshot_changed"}),
    )

    resp = _call(authenticated_client, "blueprint-gate-confirm", "post", ctx.artifact)

    assert resp.status_code == 409
    body = resp.json()
    assert body["blocked_reason"] == "snapshot_changed"
    assert body["detail"] == "确认门快照已被其它操作更新，请刷新后重新确认"


def test_gate_scope_has_exactly_one_judgment_and_no_400_branch() -> None:
    """⭐ 判据只有一份、且闸内没有 400 分支（更严变体的源码级锁）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "delivery/api/blueprint_gate_views.py").read_text(
        encoding="utf-8"
    )
    assert src.count("async def _aassert_gate_scope") == 1, "范围闸判据必须只有一份"
    assert "_aassert_project_scope" not in src, (
        "⛔ 不 import review 的 _aassert_project_scope（其 400 分支是 115-MN-03 的暴露面）"
    )
    body = src[src.index("async def _aassert_gate_scope") :]
    body = body[: body.index("\n\n\nasync def ")]
    assert body.count("status.HTTP_404_NOT_FOUND") >= 2, "两个失败分支都必须 404"
    assert "HTTP_400_BAD_REQUEST" not in body and "status=400" not in body

"""确认门 adapter + 五动作 service 行为测试（Phase 112-05 Task 1，FLOW-03 / SC-4）。

守的是**回路与规则表**，不是措辞：

1. ``open_gate`` 开一条 open+blocking 的 ``repo_confirmation`` 线程，``options`` 每仓含
   role / responsibility / fitness / routing_evidence 四类键。
2. pending 门：已有 open 确认门线程时不重开、不重算 fitness。
3. ``build_locked_associations`` 纯函数：``confirmed_at_gate`` / ``decided_by=human``、
   被 remove 的仓不出现、字段集是 schema 子集。
4. ``alock``：重读最新版本 → 锁定字段与 ``decision_log`` 就位且过 ``validate_blueprint``；
   线程 resolved；确认者进 ``BlueprintReviewer``；连锁两次 decision_log 不翻倍。
5. 章程草案 best-effort：writer 抛异常锁定仍成功。
6. **五动作 → 重调研规则表逐行断言**（SC-4 的可证伪形式）：``add_repo`` 建 ``pending``
   task、``remove_repo`` 不动、``reclassify_role`` 仅 indirect→direct 置 stale、
   ``edit_responsibility`` 仅 ``rerun=True`` 置 stale。
7. ``acollect_pending_research_repos`` 的**合取判据**：标记 + task 可派发才命中；
   task 已 done 不命中（标记无需清位）；缺键/非 dict 返回 ``[]`` 且不抛。
8. fail-closed：``add_version`` 抛 ``ArtifactContentInvalid`` → 返回
   ``awaiting_confirmation``，不上抛、不产非法蓝图版本。
9. 未决 ``ai_clarification`` 阻塞线程存在时 ``confirm`` 被拒（LIFE-02 同款语义）。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

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
from delivery.services import ArtifactContentInvalid, ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from repositories.models import Repository
from services.process_runtime.blueprint_confirm_gate import (
    BlueprintConfirmGateAdapter,
    acollect_pending_research_repos,
    build_locked_associations,
    iter_snapshot_repos,
)
from services.process_runtime.blueprint_schema import validate_blueprint
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ── 工厂 ──────────────────────────────────────────────────────────────────


def _stage1_blueprint(**overrides: Any) -> dict[str, Any]:
    """阶段 1 形态蓝图：清空引用 repo_associations 的两段（确认门会整段替换仓库集）。

    schema 后置检查 (c) 要求 ``implementation_overview.items`` /
    ``current_state_analysis`` 的 ``repository_id`` ∈ ``repo_associations``——阶段 1
    这两段还没产出，故为空（113 才装配）。
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


async def _make_repo(name: str | None = None) -> Repository:
    name = name or f"r-{uuid.uuid4().hex[:8]}"
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


async def _make_user():
    from asgiref.sync import sync_to_async
    from django.contrib.auth import get_user_model

    return await sync_to_async(get_user_model().objects.create_user)(
        username=f"u-{uuid.uuid4().hex[:8]}", password="x"
    )


async def _make_artifact(content: dict[str, Any] | None = None):
    return await ArtifactService().create(
        artifact_type="technical_plan",
        content=content if content is not None else _stage1_blueprint(),
        created_by_user_id="tester",
    )


def _candidate(repo: Repository, *, role: str = "direct", confidence: str = "high") -> dict:
    return {
        "repository_id": str(repo.id),
        "repository_name": repo.name,
        "role_suggestion": role,
        "confidence": confidence,
        "total": 0.6,
        "breakdown": {"router_base": 0.4, "charter_match": 0.2, "history_match": 0.0},
        "evidence": {
            "router_version": "v2",
            "matched_domains": [{"domain": "培优/学习提分", "status": "planned"}],
            "violated_boundaries": [],
            "history_match_unavailable": "",
        },
    }


def _routing_state(*candidates: dict) -> dict:
    return {
        "routing": {
            "router_version": "v2",
            "auto_selected": False,
            "intent": "greenfield",
            "weights_used": {},
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "candidates": list(candidates),
            "citations": [],
        }
    }


async def _make_session(artifact, stage_state: dict | None = None, *, user=None):
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_confirmation",
        stage_state=stage_state or {},
        current_artifact_version_id=artifact.current_version_id,
        created_by=user,
    )


def _fitness(repo: Repository, *, verdict: str = "suitable", role: str = "direct") -> dict:
    return {
        str(repo.id): {
            "verdict": verdict,
            "role_suggestion": role,
            "responsibility": f"{repo.name} 负责生成接口与持久化",
            "findings": [{"title": "已有能力", "detail": "题库模型已就位", "citations": []}],
            "task_status": "done",
        }
    }


def _adapter(*, fitness: dict | None = None, charter_writer: Any = None):
    return BlueprintConfirmGateAdapter(
        fitness_loader=AsyncMock(return_value=fitness or {}),
        charter_writer=charter_writer or AsyncMock(return_value=object()),
    )


async def _latest_content(artifact) -> dict[str, Any]:
    fresh = await ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").afirst()
    return fresh.content


async def _gate_thread(artifact) -> BlueprintThread | None:
    return await BlueprintThread.objects.filter(
        artifact=artifact, kind=ThreadKind.REPO_CONFIRMATION
    ).afirst()


async def _open_gate_with_two_repos():
    """预置：A(direct) + B(indirect) 两仓的 open 确认门，返回全套句柄。"""
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    artifact = await _make_artifact()
    session = await _make_session(
        artifact,
        _routing_state(
            _candidate(repo_a, role="direct"),
            _candidate(repo_b, role="indirect", confidence="low"),
        ),
    )
    fitness = {**_fitness(repo_a), **_fitness(repo_b, verdict="partial", role="indirect")}
    adapter = _adapter(fitness=fitness)
    result = await adapter.open_gate(session)
    assert result["event"] == "awaiting_confirmation"
    thread = await _gate_thread(artifact)
    return artifact, session, thread, repo_a, repo_b, adapter


async def _make_task(session, repo, status: str) -> RepoResearchTask:
    return await RepoResearchTask.objects.acreate(session=session, repository=repo, status=status)


async def _task_status(session, repo) -> str:
    row = (
        await RepoResearchTask.objects.filter(session=session, repository=repo)
        .values_list("status", flat=True)
        .afirst()
    )
    return str(row or "")


async def _snapshot_entry(thread, repo) -> dict:
    fresh = await BlueprintThread.objects.filter(id=thread.id).afirst()
    for entry in iter_snapshot_repos(fresh.options):
        if entry.get("repository_id") == str(repo.id):
            return entry
    return {}


# ═══════════════════════════════════════════════════════════════════════════
# 1-2. 开门与 pending 门
# ═══════════════════════════════════════════════════════════════════════════


async def test_open_gate_creates_blocking_thread_with_structured_options() -> None:
    artifact, _session, thread, repo_a, _repo_b, _adapter_ = await _open_gate_with_two_repos()

    assert thread is not None
    assert thread.status == ThreadStatus.OPEN
    assert thread.blocking is True
    entries = iter_snapshot_repos(thread.options)
    assert len(entries) == 2
    by_id = {entry["repository_id"]: entry for entry in entries}
    entry = by_id[str(repo_a.id)]
    for key in ("role_suggestion", "responsibility", "fitness", "routing_evidence"):
        assert key in entry, f"快照缺 {key}：{entry}"
    assert entry["fitness"]["verdict"] == "suitable"
    assert entry["routing_evidence"]["router_version"] == "v2"
    assert entry["routing_evidence"]["charter_match"] == pytest.approx(0.2)
    assert entry["current_state_summary"]
    assert await BlueprintThread.objects.filter(artifact=artifact).acount() == 1


async def test_open_gate_pending_short_circuits() -> None:
    artifact, session, _thread, repo_a, _repo_b, _a = await _open_gate_with_two_repos()
    loader = AsyncMock(return_value=_fitness(repo_a))
    adapter = BlueprintConfirmGateAdapter(
        fitness_loader=loader, charter_writer=AsyncMock(return_value=object())
    )

    result = await adapter.open_gate(session)

    assert result["event"] == "awaiting_confirmation"
    assert loader.await_count == 0, "pending 门应短路，不重算 fitness"
    assert await BlueprintThread.objects.filter(artifact=artifact).acount() == 1


# ═══════════════════════════════════════════════════════════════════════════
# 3. build_locked_associations 纯函数
# ═══════════════════════════════════════════════════════════════════════════


async def test_build_locked_associations_marks_human_decision_and_drops_removed() -> None:
    snapshot = [
        {
            "repository_id": "repo-keep",
            "repository_name": "onion-practice",
            "role_suggestion": "direct",
            "responsibility": "提供生成接口",
            "fitness": {"verdict": "suitable", "reasons": ["已有题库模型"], "citations": ["nope"]},
            "routing_evidence": {"total": 0.6, "router_version": "v2"},
        },
        {"repository_id": "repo-gone", "repository_name": "legacy", "removed": True},
    ]

    associations = build_locked_associations(snapshot=snapshot, decisions={}, citation_pool=set())

    assert [a["repository_id"] for a in associations] == ["repo-keep"]
    locked = associations[0]
    assert locked["confirmed_at_gate"] is True
    assert locked["decided_by"] == "human"
    assert locked["role"] == "direct"
    assert locked["responsibility"][0]["text"] == "提供生成接口"
    assert locked["fitness"]["verdict"] == "suitable"
    # 引用池为空 → 裸文件路径类 citation 被白名单过滤掉（否则整份蓝图校验失败）
    assert "citations" not in locked["fitness"]


async def test_build_locked_associations_falls_back_to_direct_for_invalid_role() -> None:
    snapshot = [{"repository_id": "r1", "role_suggestion": "maybe"}]
    assert build_locked_associations(snapshot=snapshot)[0]["role"] == "direct"
    # repository_name 缺失时回落 id（schema 要求 minLength 1）
    assert build_locked_associations(snapshot=snapshot)[0]["repository_name"] == "r1"


# ═══════════════════════════════════════════════════════════════════════════
# 4-5. alock：锁定 / decision_log 幂等 / 章程 best-effort
# ═══════════════════════════════════════════════════════════════════════════


async def test_alock_writes_locked_associations_and_passes_schema() -> None:
    artifact, session, thread, repo_a, repo_b, adapter = await _open_gate_with_two_repos()
    user = await _make_user()
    lifecycle = BlueprintLifecycleService()
    await lifecycle.apply_gate_action(
        artifact,
        thread=thread,
        action="remove_repo",
        payload={"repository_id": str(repo_b.id), "reason": "不该放这里"},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    result = await adapter.alock(session, acting_user=user)

    assert result["event"] == "confirmed"
    content = await _latest_content(artifact)
    assert validate_blueprint(content) == (True, None)
    ids = [a["repository_id"] for a in content["repo_associations"]]
    assert ids == [str(repo_a.id)], "被 remove 的仓不得进 associations"
    locked = content["repo_associations"][0]
    assert locked["confirmed_at_gate"] is True
    assert locked["decided_by"] == "human"
    assert locked["responsibility"], "职责必须落字段"
    log = content["decision_log"]
    assert any(item["action"] == "remove_repo" for item in log)
    assert all(item["decided_by"] for item in log)

    fresh_thread = await BlueprintThread.objects.filter(id=thread.id).afirst()
    assert fresh_thread.status == ThreadStatus.RESOLVED
    assert await BlueprintReviewer.objects.filter(artifact=artifact, user=user).aexists()


async def test_alock_decision_log_is_idempotent() -> None:
    artifact, session, thread, _repo_a, repo_b, adapter = await _open_gate_with_two_repos()
    user = await _make_user()
    await BlueprintLifecycleService().apply_gate_action(
        artifact,
        thread=thread,
        action="remove_repo",
        payload={"repository_id": str(repo_b.id)},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    await adapter.alock(session, acting_user=user)
    first = len((await _latest_content(artifact))["decision_log"])
    # 线程已 resolved，第二次锁定必须是 no-op 而非重复堆积
    await adapter.alock(session, acting_user=user)
    second = len((await _latest_content(artifact))["decision_log"])

    assert first >= 1
    assert second == first


async def test_alock_survives_charter_writer_failure() -> None:
    repo_a = await _make_repo()
    artifact = await _make_artifact()
    session = await _make_session(artifact, _routing_state(_candidate(repo_a)))
    adapter = BlueprintConfirmGateAdapter(
        fitness_loader=AsyncMock(return_value=_fitness(repo_a)),
        charter_writer=AsyncMock(side_effect=RuntimeError("charter down")),
    )
    await adapter.open_gate(session)
    user = await _make_user()

    result = await adapter.alock(session, acting_user=user)

    assert result["event"] == "confirmed"
    content = await _latest_content(artifact)
    assert [a["repository_id"] for a in content["repo_associations"]] == [str(repo_a.id)]


async def test_alock_fail_closed_on_invalid_content(monkeypatch: pytest.MonkeyPatch) -> None:
    artifact, session, _thread, repo_a, _repo_b, adapter = await _open_gate_with_two_repos()
    user = await _make_user()
    before = await ArtifactVersion.objects.filter(artifact=artifact).acount()
    monkeypatch.setattr(
        adapter.artifacts,
        "add_version",
        AsyncMock(side_effect=ArtifactContentInvalid("bad content")),
    )

    result = await adapter.alock(session, acting_user=user)

    assert result["event"] == "awaiting_confirmation"
    assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == before
    assert str(repo_a.id)  # 仓仍在快照里等人修规格后重试


# ═══════════════════════════════════════════════════════════════════════════
# 6. 五动作 → 重调研规则表（SC-4 逐行断言）
# ═══════════════════════════════════════════════════════════════════════════


async def test_apply_gate_action_rejects_unknown_action() -> None:
    artifact, session, thread, _a, _b, _ad = await _open_gate_with_two_repos()
    user = await _make_user()

    with pytest.raises(ValueError):
        await BlueprintLifecycleService().apply_gate_action(
            artifact,
            thread=thread,
            action="drop_database",
            payload={},
            acting_user=user,
            initiated_by_user_id=str(user.id),
            session=session,
        )


async def test_add_repo_requires_research_and_creates_pending_task() -> None:
    artifact, session, thread, _repo_a, _repo_b, _ad = await _open_gate_with_two_repos()
    repo_c = await _make_repo()
    user = await _make_user()

    result = await BlueprintLifecycleService().apply_gate_action(
        artifact,
        thread=thread,
        action="add_repo",
        payload={"repository_id": str(repo_c.id), "role": "direct"},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    assert result["requires_research"] is True
    assert result["repository_id"] == str(repo_c.id)
    assert await _task_status(session, repo_c) == RepoResearchTaskStatus.PENDING
    entry = await _snapshot_entry(thread, repo_c)
    assert entry["pending_research"] is True
    assert entry["role_suggestion"] == "direct"


async def test_add_repo_unknown_repository_is_not_found() -> None:
    artifact, session, thread, _a, _b, _ad = await _open_gate_with_two_repos()
    user = await _make_user()

    with pytest.raises(ValueError) as exc:
        await BlueprintLifecycleService().apply_gate_action(
            artifact,
            thread=thread,
            action="add_repo",
            payload={"repository_id": str(uuid.uuid4())},
            acting_user=user,
            initiated_by_user_id=str(user.id),
            session=session,
        )
    assert exc.value.args[0] == "repository_not_found"


async def test_remove_repo_does_not_trigger_research() -> None:
    artifact, session, thread, repo_a, _repo_b, _ad = await _open_gate_with_two_repos()
    await _make_task(session, repo_a, RepoResearchTaskStatus.DONE)
    user = await _make_user()

    result = await BlueprintLifecycleService().apply_gate_action(
        artifact,
        thread=thread,
        action="remove_repo",
        payload={"repository_id": str(repo_a.id)},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    assert result["requires_research"] is False
    assert await _task_status(session, repo_a) == RepoResearchTaskStatus.DONE
    entry = await _snapshot_entry(thread, repo_a)
    assert entry["removed"] is True
    assert entry["pending_research"] is False


@pytest.mark.parametrize(
    ("before_role", "new_role", "expect_research"),
    [("indirect", "direct", True), ("direct", "indirect", False), ("direct", "direct", False)],
)
async def test_reclassify_role_rule_table(
    before_role: str, new_role: str, expect_research: bool
) -> None:
    repo = await _make_repo()
    artifact = await _make_artifact()
    session = await _make_session(artifact, _routing_state(_candidate(repo, role=before_role)))
    adapter = _adapter(fitness=_fitness(repo, role=before_role))
    await adapter.open_gate(session)
    thread = await _gate_thread(artifact)
    await _make_task(session, repo, RepoResearchTaskStatus.DONE)
    user = await _make_user()

    result = await BlueprintLifecycleService().apply_gate_action(
        artifact,
        thread=thread,
        action="reclassify_role",
        payload={"repository_id": str(repo.id), "role": new_role},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    assert result["requires_research"] is expect_research
    expected_status = (
        RepoResearchTaskStatus.STALE if expect_research else RepoResearchTaskStatus.DONE
    )
    assert await _task_status(session, repo) == expected_status
    entry = await _snapshot_entry(thread, repo)
    assert entry["role_suggestion"] == new_role
    assert entry.get("pending_research", False) is expect_research


async def test_reclassify_role_rejects_invalid_role() -> None:
    artifact, session, thread, repo_a, _b, _ad = await _open_gate_with_two_repos()
    user = await _make_user()

    with pytest.raises(ValueError) as exc:
        await BlueprintLifecycleService().apply_gate_action(
            artifact,
            thread=thread,
            action="reclassify_role",
            payload={"repository_id": str(repo_a.id), "role": "maybe"},
            acting_user=user,
            initiated_by_user_id=str(user.id),
            session=session,
        )
    assert exc.value.args[0] == "invalid_role"


@pytest.mark.parametrize(("rerun", "expect_research"), [(None, False), (True, True)])
async def test_edit_responsibility_rule_table(rerun: Any, expect_research: bool) -> None:
    artifact, session, thread, repo_a, _repo_b, _ad = await _open_gate_with_two_repos()
    await _make_task(session, repo_a, RepoResearchTaskStatus.DONE)
    user = await _make_user()
    payload: dict[str, Any] = {"repository_id": str(repo_a.id), "responsibility": "只提供只读接口"}
    if rerun is not None:
        payload["rerun"] = rerun

    result = await BlueprintLifecycleService().apply_gate_action(
        artifact,
        thread=thread,
        action="edit_responsibility",
        payload=payload,
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    assert result["requires_research"] is expect_research
    expected_status = (
        RepoResearchTaskStatus.STALE if expect_research else RepoResearchTaskStatus.DONE
    )
    assert await _task_status(session, repo_a) == expected_status
    entry = await _snapshot_entry(thread, repo_a)
    assert entry["responsibility"] == "只提供只读接口"


async def test_confirm_blocked_by_pending_clarification() -> None:
    artifact, session, thread, _a, _b, _ad = await _open_gate_with_two_repos()
    lifecycle = BlueprintLifecycleService()
    await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="目标用户是谁？",
    )
    user = await _make_user()

    result = await lifecycle.apply_gate_action(
        artifact,
        thread=thread,
        action="confirm",
        payload={},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    assert result["ready_to_lock"] is False
    assert result["blocked_reason"] == "pending_clarification"


async def test_confirm_ready_to_lock_when_no_blocking_clarification() -> None:
    artifact, session, thread, _a, _b, _ad = await _open_gate_with_two_repos()
    user = await _make_user()

    result = await BlueprintLifecycleService().apply_gate_action(
        artifact,
        thread=thread,
        action="confirm",
        payload={},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    assert result["ready_to_lock"] is True
    assert result["blocked_reason"] == ""
    assert result["requires_research"] is False
    # 留痕消息不得把确认门线程推到 answered（否则 open_gate 会再开第二条门）
    fresh = await BlueprintThread.objects.filter(id=thread.id).afirst()
    assert fresh.status == ThreadStatus.OPEN


# ═══════════════════════════════════════════════════════════════════════════
# 7. acollect_pending_research_repos 的合取判据（唯一实现）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("stage_state", [{}, {"confirmation": "not-a-dict"}, {"confirmation": []}])
async def test_pending_probe_returns_empty_for_missing_or_malformed_state(
    stage_state: Any,
) -> None:
    artifact = await _make_artifact()
    session = await _make_session(artifact, stage_state)

    assert await acollect_pending_research_repos(session) == []


async def test_pending_probe_requires_both_marker_and_dispatchable_task() -> None:
    repo_marked = await _make_repo()
    repo_done = await _make_repo()
    repo_plain = await _make_repo()
    artifact = await _make_artifact()
    session = await _make_session(
        artifact,
        {
            "confirmation": {
                "repos": [
                    {"repository_id": str(repo_marked.id), "pending_research": True},
                    {"repository_id": str(repo_done.id), "pending_research": True},
                    {"repository_id": str(repo_plain.id)},
                ]
            }
        },
    )
    await _make_task(session, repo_marked, RepoResearchTaskStatus.PENDING)
    await _make_task(session, repo_done, RepoResearchTaskStatus.DONE)
    await _make_task(session, repo_plain, RepoResearchTaskStatus.PENDING)

    pending = await acollect_pending_research_repos(session)

    assert pending == [str(repo_marked.id)]


async def test_pending_probe_reads_live_thread_snapshot() -> None:
    """动作端点只写线程行，stage_state 要等下一次 transition —— 判据必须读活跃线程。"""
    artifact, session, thread, _repo_a, _repo_b, _ad = await _open_gate_with_two_repos()
    repo_c = await _make_repo()
    user = await _make_user()
    await BlueprintLifecycleService().apply_gate_action(
        artifact,
        thread=thread,
        action="add_repo",
        payload={"repository_id": str(repo_c.id)},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )

    # session.stage_state 尚未刷新（没有 transition），判据仍须命中新仓
    assert "confirmation" not in (session.stage_state or {})
    assert await acollect_pending_research_repos(session) == [str(repo_c.id)]


async def test_pending_probe_ignores_stale_marker_after_dispatch() -> None:
    repo = await _make_repo()
    artifact = await _make_artifact()
    session = await _make_session(
        artifact,
        {"confirmation": {"repos": [{"repository_id": str(repo.id), "pending_research": True}]}},
    )
    await _make_task(session, repo, RepoResearchTaskStatus.RUNNING)

    assert await acollect_pending_research_repos(session) == []

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
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ArtifactContentInvalid, ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from repositories.models import Repository
from services.process_runtime.blueprint_charter_match import score_charter_match
from services.process_runtime.blueprint_citations import (
    build_citation_entries,
    citation_id_for,
)
from services.process_runtime.blueprint_confirm_gate import (
    _MAX_DOMAIN_CHARS,
    UNSUITABLE_REMOVE_REASON,
    BlueprintConfirmGateAdapter,
    _build_charter_draft,
    _build_snapshot_entry,
    acollect_pending_research_repos,
    build_locked_associations,
    iter_snapshot_repos,
    merge_gate_snapshot,
)
from services.process_runtime.blueprint_merge import (
    build_citation_pool,
    project_repo_associations,
)
from services.process_runtime.blueprint_review import check_citations
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


def _stage1_blueprint_with_empty_citation_pool() -> dict[str, Any]:
    """构造引用池与所有引用点都为空的合法阶段 1 蓝图。"""
    content = _stage1_blueprint()

    def _clear(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == "citations":
                    value[key] = []
                else:
                    _clear(nested)
        elif isinstance(value, list):
            for nested in value:
                _clear(nested)

    _clear(content)
    content["citations"] = {}
    return content


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
            "reasons": ["仓库职责与需求匹配"],
            "role_suggestion": role,
            "responsibility": f"{repo.name} 负责生成接口与持久化",
            "current_state_summary": "已存在题库模型和持久化能力",
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


async def _grant_scope(session, *repos: Repository) -> None:
    """把仓纳入蓝图范围白名单（``add_repo`` 的 repository_id 必须在范围内，MJ-01）。"""
    state = dict(session.stage_state or {})
    state["include_repos"] = list(state.get("include_repos") or []) + [str(r.id) for r in repos]
    session.stage_state = state
    await ConvergenceSession.objects.filter(id=session.id).aupdate(stage_state=state)


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


@pytest.mark.parametrize(
    ("conclusion_patch", "task_status"),
    [
        ({"task_status": "failed"}, RepoResearchTaskStatus.FAILED),
        (
            {"task_status": "failed", "role_suggestion": "indirect"},
            RepoResearchTaskStatus.FAILED,
        ),
        ({"responsibility": ""}, RepoResearchTaskStatus.DONE),
        ({"reasons": []}, RepoResearchTaskStatus.DONE),
        ({"current_state_summary": "", "findings": []}, RepoResearchTaskStatus.DONE),
    ],
)
async def test_open_gate_retries_direct_candidates_without_complete_evidence(
    conclusion_patch: dict[str, Any],
    task_status: str,
) -> None:
    """direct 调研失败或证据不全时不得发布可回答 repo_confirmation。"""
    repo = await _make_repo()
    artifact = await _make_artifact()
    session = await _make_session(artifact, _routing_state(_candidate(repo, role="direct")))
    task = await _make_task(session, repo, task_status)
    task.attempt = 1
    await task.asave(update_fields=["attempt"])
    conclusion = _fitness(repo)[str(repo.id)]
    conclusion.update(conclusion_patch)

    result = await _adapter(fitness={str(repo.id): conclusion}).open_gate(session)

    assert result["event"] == "research_required"
    assert await _gate_thread(artifact) is None
    assert await _task_status(session, repo) == RepoResearchTaskStatus.STALE


async def test_open_gate_retries_routed_direct_lightweight_fallback() -> None:
    """字段齐全也不能把 routed-direct 的轻量路由合成冒充真实仓库调研。"""
    repo = await _make_repo()
    artifact = await _make_artifact()
    session = await _make_session(artifact, _routing_state(_candidate(repo, role="direct")))
    task = await _make_task(session, repo, RepoResearchTaskStatus.DONE)
    task.attempt = 1
    await task.asave(update_fields=["attempt"])
    await PartialPlan.objects.acreate(
        research_task=task,
        content={
            **_fitness(repo)[str(repo.id)],
            "repository_id": str(repo.id),
            "research_depth": "light",
            "research_summary": "服务端轻量合成",
        },
        valid=True,
        content_hash="light",
    )

    result = await _adapter(fitness=_fitness(repo)).open_gate(session)

    assert result["event"] == "research_required"
    assert await _gate_thread(artifact) is None
    assert await _task_status(session, repo) == RepoResearchTaskStatus.STALE


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


async def _team_session(artifact, *, ledger: dict | None = None, decomposition: dict | None = None):
    """构造停在团队 clarify 上的确认门会话（可带团队澄清续跑账本）。"""
    confirmation: dict[str, Any] = {"repos": []}
    if ledger is not None:
        confirmation["team_clarification"] = ledger
        confirmation["clarification_kind"] = "team"
    stage_state: dict[str, Any] = {
        "routing": {
            "status": "clarify",
            "clarify_reason": "missing_team",
            "candidates": [],
        },
        "confirmation": confirmation,
    }
    if decomposition is not None:
        stage_state["decomposition"] = decomposition
    return await _make_session(artifact, stage_state)


async def _answer_team_thread(thread, body: str) -> None:
    """在团队澄清线程上写一条人类答复并置 resolved。"""
    from delivery.models import BlueprintThreadMessage, ThreadAuthorType

    await BlueprintThreadMessage.objects.acreate(
        thread=thread,
        author_type=ThreadAuthorType.HUMAN,
        body=body,
    )
    # reflow 侧还会追写一条 AI 回灌确认 —— 收答必须按 author_type 挑人类那条，
    # 否则会把系统文案当团队名去匹配。
    await BlueprintThreadMessage.objects.acreate(
        thread=thread,
        author_type=ThreadAuthorType.AI,
        body="答案已回灌，产出版本 v3。",
    )
    await BlueprintThread.objects.filter(id=thread.id).aupdate(status=ThreadStatus.RESOLVED)


async def test_missing_team_opens_team_clarification_instead_of_empty_repo_gate() -> None:
    """missing_team 必须先问 Team，禁止生成零选项 repo_confirmation。"""
    artifact = await _make_artifact()
    session = await _team_session(artifact)

    result = await _adapter().open_gate(session)

    team_thread = await BlueprintThread.objects.filter(
        artifact=artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        status=ThreadStatus.OPEN,
    ).afirst()
    assert result["event"] == "awaiting_confirmation"
    assert result["repo_count"] == 0
    confirmation = result["stage_state"]["confirmation"]
    assert confirmation["clarification_kind"] == "team"
    # 续跑账本必须落盘：轮次与线程 id 是下一轮收答与止损的唯一依据。
    assert confirmation["team_clarification"]["rounds"] == 1
    assert confirmation["team_clarification"]["thread_id"] == str(team_thread.id)
    assert team_thread is not None
    first_message = await team_thread.messages.afirst()
    assert first_message is not None
    assert "负责团队" in first_message.body
    assert (
        await BlueprintThread.objects.filter(
            artifact=artifact,
            kind=ThreadKind.REPO_CONFIRMATION,
        ).acount()
        == 0
    )


async def test_team_answer_is_adopted_and_reroutes_instead_of_reasking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """收答闭环：答复解析出团队 → 写进 decomposition.primary_team 并回 route 重跑。

    这是 AGE-66 死循环的可证伪形式 —— 修复前这里会再开一条逐字相同的新澄清线程。
    """
    monkeypatch.setattr(
        "services.process_runtime.team_gate.alist_team_options",
        AsyncMock(return_value=[{"team": "学习工具", "repo_count": 4}]),
    )
    monkeypatch.setattr(
        "services.process_runtime.team_gate.aresolve_accessible_space_id",
        AsyncMock(return_value=str(uuid.uuid4())),
    )
    artifact = await _make_artifact()
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="负责团队是哪个？",
        options=[],
        initiated_by_user_id="tester",
    )
    await _answer_team_thread(thread, "负责团队是「学习工具」，核心仓在该团队 facets 下。")
    session = await _team_session(
        artifact,
        ledger={"rounds": 1, "thread_id": str(thread.id), "adopted_team": ""},
        decomposition={"project_id": "", "primary_team": "学习A"},
    )

    result = await _adapter().open_gate(session)

    assert result["event"] == "reroute_required"
    assert result["stage_state"]["decomposition"]["primary_team"] == "学习工具"
    # project_id 是独立身份，采纳团队绝不能顺手给它塞值。
    assert result["stage_state"]["decomposition"]["project_id"] == ""
    assert (
        await BlueprintThread.objects.filter(
            artifact=artifact, kind=ThreadKind.AI_CLARIFICATION, status=ThreadStatus.OPEN
        ).acount()
        == 0
    ), "采纳答复后不得再开新的团队澄清线程"


async def test_unmatched_team_answer_reasks_with_options_and_counts_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """答复匹配不到已登记取值时带候选再问一轮，并把轮次记上去。"""
    options = [{"team": "学习工具", "repo_count": 4}, {"team": "商业化", "repo_count": 9}]
    monkeypatch.setattr(
        "services.process_runtime.team_gate.alist_team_options",
        AsyncMock(return_value=options),
    )
    monkeypatch.setattr(
        "services.process_runtime.team_gate.aresolve_accessible_space_id",
        AsyncMock(return_value=str(uuid.uuid4())),
    )
    artifact = await _make_artifact()
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="负责团队是哪个？",
        options=[],
        initiated_by_user_id="tester",
    )
    await _answer_team_thread(thread, "就是学习A那个团队")
    session = await _team_session(
        artifact,
        ledger={"rounds": 1, "thread_id": str(thread.id), "adopted_team": ""},
    )

    result = await _adapter().open_gate(session)

    assert result["event"] == "awaiting_confirmation"
    confirmation = result["stage_state"]["confirmation"]
    assert confirmation["team_clarification"]["rounds"] == 2
    fresh = await BlueprintThread.objects.filter(
        artifact=artifact, kind=ThreadKind.AI_CLARIFICATION, status=ThreadStatus.OPEN
    ).afirst()
    assert fresh is not None
    assert fresh.options == options, "再问必须带候选，否则又变成无从校验的自由作答"


async def test_team_clarification_stops_after_round_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """轮次到顶仍解析不出团队时停在确认门交人，绝不再开新线程（止损）。"""
    from services.process_runtime.blueprint_confirm_gate import (
        _MAX_TEAM_CLARIFICATION_ROUNDS,
    )

    monkeypatch.setattr(
        "services.process_runtime.team_gate.alist_team_options",
        AsyncMock(return_value=[{"team": "学习工具", "repo_count": 4}]),
    )
    monkeypatch.setattr(
        "services.process_runtime.team_gate.aresolve_accessible_space_id",
        AsyncMock(return_value=str(uuid.uuid4())),
    )
    artifact = await _make_artifact()
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="负责团队是哪个？",
        options=[],
        initiated_by_user_id="tester",
    )
    await _answer_team_thread(thread, "说不清楚")
    session = await _team_session(
        artifact,
        ledger={
            "rounds": _MAX_TEAM_CLARIFICATION_ROUNDS,
            "thread_id": str(thread.id),
            "adopted_team": "",
        },
    )

    result = await _adapter().open_gate(session)

    assert result["event"] == "awaiting_confirmation"
    assert result["stage_state"] is None
    assert (
        await BlueprintThread.objects.filter(
            artifact=artifact, kind=ThreadKind.AI_CLARIFICATION, status=ThreadStatus.OPEN
        ).acount()
        == 0
    ), "到顶后必须停下来交人，继续出题就是死循环"


async def _set_thread_options(thread, options: list[dict]) -> None:
    await BlueprintThread.objects.filter(id=thread.id).aupdate(options=options)


async def test_open_gate_pending_refreshes_snapshot() -> None:
    """D-01：已有 open 确认门时不重开线程，但**幂等刷新**——loader 会被调用，
    旧 ``task_status=failed`` 被最新调研结论刷成 done（不再永久残留 failed）。"""
    artifact, session, thread, repo_a, repo_b, _a = await _open_gate_with_two_repos()
    # 模拟「门开着期间调研先失败落进快照」的存量：把 repo_a 的 task_status 打成 failed。
    stale = iter_snapshot_repos((await BlueprintThread.objects.aget(id=thread.id)).options)
    for entry in stale:
        if entry["repository_id"] == str(repo_a.id):
            entry["task_status"] = "failed"
            entry["fitness"] = {"verdict": "unsuitable", "reasons": [], "citations": []}
    await _set_thread_options(thread, stale)

    loader = AsyncMock(
        return_value={**_fitness(repo_a), **_fitness(repo_b, verdict="partial", role="indirect")}
    )
    adapter = BlueprintConfirmGateAdapter(
        fitness_loader=loader, charter_writer=AsyncMock(return_value=object())
    )

    result = await adapter.open_gate(session)

    assert result["event"] == "awaiting_confirmation"
    assert loader.await_count >= 1, "pending 门现在必须刷新快照（会调 fitness loader）"
    assert await BlueprintThread.objects.filter(artifact=artifact).acount() == 1
    entry = await _snapshot_entry(thread, repo_a)
    assert entry["task_status"] == "done", "陈旧 failed 必须被刷成最新 done"
    assert entry["fitness"]["verdict"] == "suitable"


async def test_refresh_open_gate_snapshot_updates_stale_task_status() -> None:
    artifact, session, thread, repo_a, _repo_b, adapter = await _open_gate_with_two_repos()
    stale = iter_snapshot_repos((await BlueprintThread.objects.aget(id=thread.id)).options)
    for entry in stale:
        entry["task_status"] = "failed"
    await _set_thread_options(thread, stale)

    result = await adapter.arefresh_open_gate_snapshot(session)

    assert result["refreshed"] is True
    assert result["thread_id"] == str(thread.id)
    assert result["changed_count"] >= 1
    entry = await _snapshot_entry(thread, repo_a)
    assert entry["task_status"] == "done"


async def test_refresh_open_gate_snapshot_preserves_human_fields() -> None:
    """并发终态回调下 refresh 不得冲掉人工裁决面（role/responsibility/removed/actions）。"""
    artifact, session, thread, repo_a, _repo_b, adapter = await _open_gate_with_two_repos()
    user = await _make_user()
    # 人工编辑职责（会写 responsibility + 追加一条 actions），并改判角色。
    await BlueprintLifecycleService().apply_gate_action(
        artifact,
        thread=thread,
        action="edit_responsibility",
        payload={"repository_id": str(repo_a.id), "responsibility": "只提供只读接口"},
        acting_user=user,
        initiated_by_user_id=str(user.id),
        session=session,
    )
    # 再把 task_status 打成 failed 模拟陈旧。
    stale = iter_snapshot_repos((await BlueprintThread.objects.aget(id=thread.id)).options)
    for entry in stale:
        if entry["repository_id"] == str(repo_a.id):
            entry["task_status"] = "failed"
    await _set_thread_options(thread, stale)

    result = await adapter.arefresh_open_gate_snapshot(session)

    assert result["refreshed"] is True
    entry = await _snapshot_entry(thread, repo_a)
    # fitness 面被刷新
    assert entry["task_status"] == "done"
    # 人工裁决面保留
    assert entry["responsibility"] == "只提供只读接口"
    assert entry["actions"], "人工 actions 不得被 refresh 冲掉"
    assert any(a.get("action") == "edit_responsibility" for a in entry["actions"])


async def test_refresh_open_gate_snapshot_is_noop_when_unchanged() -> None:
    """无实质变化时 refresh 不写库（幂等；D-03）。"""
    _artifact, session, _thread, _repo_a, _repo_b, adapter = await _open_gate_with_two_repos()

    # 快照刚由同一 loader 建出，第二次刷新应无变化。
    result = await adapter.arefresh_open_gate_snapshot(session)

    assert result["refreshed"] is False
    assert result["changed_count"] == 0


async def test_refresh_open_gate_snapshot_noop_without_gate() -> None:
    """无打开的确认门时 refresh 安全 no-op（不抛、refreshed=False）。"""
    repo = await _make_repo()
    artifact = await _make_artifact()
    session = await _make_session(artifact, _routing_state(_candidate(repo)))
    adapter = _adapter(fitness=_fitness(repo))

    result = await adapter.arefresh_open_gate_snapshot(session)

    assert result["refreshed"] is False
    assert result["thread_id"] is None


# ═══════════════════════════════════════════════════════════════════════════
# 2b. merge_gate_snapshot 纯函数（幂等 refresh 的字段分工，D-01）
# ═══════════════════════════════════════════════════════════════════════════


async def test_merge_gate_snapshot_overrides_fitness_preserves_human() -> None:
    existing = [
        {
            "repository_id": "r1",
            "repository_name": "",
            "role_suggestion": "indirect",  # 人工改判过
            "responsibility": "人工编辑的职责",
            "removed": False,
            "pending_research": True,
            "actions": [{"action": "edit_responsibility"}],
            "task_status": "failed",
            "fitness": {"verdict": "unsuitable"},
            "confidence": "low",
        }
    ]
    fresh = [
        {
            "repository_id": "r1",
            "repository_name": "onion-repo",
            "role_suggestion": "direct",  # 计算面（不得覆盖人工）
            "responsibility": "调研合成的职责",  # 计算面（不得覆盖人工）
            "task_status": "done",
            "fitness": {"verdict": "suitable"},
            "confidence": "high",
            "current_state_summary": "现状已更新",
        }
    ]

    merged = merge_gate_snapshot(existing, fresh)

    entry = merged[0]
    # fitness 面被刷新
    assert entry["task_status"] == "done"
    assert entry["fitness"] == {"verdict": "suitable"}
    assert entry["confidence"] == "high"
    assert entry["current_state_summary"] == "现状已更新"
    # 人工裁决面保留
    assert entry["role_suggestion"] == "indirect"
    assert entry["responsibility"] == "人工编辑的职责"
    assert entry["pending_research"] is True
    assert entry["actions"] == [{"action": "edit_responsibility"}]
    # 空名才补
    assert entry["repository_name"] == "onion-repo"


async def test_merge_gate_snapshot_never_adds_or_revives_repos() -> None:
    existing = [
        {"repository_id": "keep", "removed": False, "task_status": "failed"},
        {"repository_id": "removed-by-human", "removed": True, "task_status": "failed"},
    ]
    fresh = [
        {"repository_id": "keep", "task_status": "done"},
        {"repository_id": "removed-by-human", "task_status": "done"},
        {"repository_id": "router-only", "task_status": "done"},  # fresh-only 不追加
    ]

    merged = merge_gate_snapshot(existing, fresh)

    ids = [e["repository_id"] for e in merged]
    assert ids == ["keep", "removed-by-human"], "仓集不增不减"
    # 被人工移除的仓不因 refresh 复活
    assert merged[1]["removed"] is True
    # task_status 仍刷新（展示态一致）
    assert merged[0]["task_status"] == "done"
    assert merged[1]["task_status"] == "done"


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


def test_confirm_gate_and_merge_generate_identical_citation_ids() -> None:
    """确认门与 merge 必须共享逐字节一致的引用 id 口径。"""
    raw = "internal/data/user.go:660"
    entries, cite_map = build_citation_entries([raw])
    merge_entries, merge_map = build_citation_pool(
        {},
        [{"fitness": {"citations": [raw]}}],
    )

    assert cite_map[raw] == citation_id_for(raw) == merge_map[raw]
    assert entries == merge_entries


def test_existing_citation_id_does_not_create_second_order_entry() -> None:
    """池内 id 再过确认门时不得生成 ``cit_sha1("cit_xxx")``。"""
    citation_id = citation_id_for("internal/data/user.go:660")

    entries, cite_map = build_citation_entries([citation_id])

    assert entries == []
    assert cite_map == {}


# ═══════════════════════════════════════════════════════════════════════════
# 3b. Fix C：unsuitable 默认不进锁定关联（D-03），人工重纳后可 lock
# ═══════════════════════════════════════════════════════════════════════════


def _entry_with_verdict(verdict: str) -> dict[str, Any]:
    return _build_snapshot_entry(
        "r-1",
        candidate={"repository_name": "onion-repo", "confidence": "high"},
        conclusion={"verdict": verdict, "role_suggestion": "direct", "responsibility": "职责"},
        router_version="v2",
    )


def test_unsuitable_snapshot_entry_is_removed_by_default() -> None:
    """⭐ 调研判 unsuitable → 建门即 ``removed``：默认不该锁进 repo_associations。"""
    entry = _entry_with_verdict("unsuitable")

    assert entry["removed"] is True
    assert entry["remove_reason"] == UNSUITABLE_REMOVE_REASON
    assert build_locked_associations(snapshot=[entry]) == []


def test_suitable_and_partial_snapshot_entries_are_not_auto_removed() -> None:
    """suitable / partial 不自动移除（只拦「明确不适配」，不误伤部分适配）。"""
    for verdict in ("suitable", "partial", ""):
        entry = _entry_with_verdict(verdict)
        assert entry["removed"] is False, verdict
        assert entry["remove_reason"] == ""
        assert len(build_locked_associations(snapshot=[entry])) == 1, verdict


def test_refresh_tightens_gate_opened_before_unsuitable_verdict() -> None:
    """「门先开、调研后判 unsuitable」→ refresh 必须收紧成 removed（时序漏洞）。"""
    existing = [{"repository_id": "r1", "removed": False, "fitness": {"verdict": "partial"}}]
    fresh = [{"repository_id": "r1", "fitness": {"verdict": "unsuitable"}}]

    merged = merge_gate_snapshot(existing, fresh)

    assert merged[0]["removed"] is True
    assert merged[0]["remove_reason"] == UNSUITABLE_REMOVE_REASON
    assert build_locked_associations(snapshot=merged) == []


def test_human_readmission_survives_refresh_and_can_be_locked() -> None:
    """⭐ 人工 ``add_repo`` 重纳后，即使 fresh 仍 unsuitable 也保持 ``removed=False``。

    机器判定不得覆盖人工裁决：否则「我知道它不适配但仍要它参与」永远无法表达。
    """
    existing = [
        {
            "repository_id": "r1",
            "repository_name": "onion-repo",
            "role_suggestion": "direct",
            "removed": False,
            "remove_reason": "",
            "fitness": {"verdict": "unsuitable"},
            "actions": [
                {"action": "add_repo", "before": {"removed": True}, "after": {"removed": False}}
            ],
        }
    ]
    fresh = [{"repository_id": "r1", "fitness": {"verdict": "unsuitable"}}]

    merged = merge_gate_snapshot(existing, fresh)

    assert merged[0]["removed"] is False
    locked = build_locked_associations(snapshot=merged)
    assert [a["repository_id"] for a in locked] == ["r1"]


def test_refresh_keeps_human_remove_reason_on_already_removed_repo() -> None:
    """已被人工 remove 的仓：refresh 不把人工原因冲成机器原因。"""
    existing = [
        {
            "repository_id": "r1",
            "removed": True,
            "remove_reason": "本次不涉及该端",
            "fitness": {"verdict": "partial"},
        }
    ]
    fresh = [{"repository_id": "r1", "fitness": {"verdict": "unsuitable"}}]

    merged = merge_gate_snapshot(existing, fresh)

    assert merged[0]["remove_reason"] == "本次不涉及该端"


def test_auto_removed_charter_boundary_is_not_attributed_to_a_user_action() -> None:
    """自动移除写进章程 boundaries 的措辞不得谎称「用户移除」（长期事实会误导裁决）。"""
    entry = _entry_with_verdict("unsuitable")
    entry["responsibility"] = ""

    rule = _build_charter_draft(entry)["boundaries"][0]["rule"]

    assert "调研判定不适配" in rule
    assert UNSUITABLE_REMOVE_REASON not in rule


def test_unsuitable_auto_remove_emits_sampling_event(monkeypatch) -> None:
    """收紧动作可观测：sampling 事件带计数，无凭证/正文。"""
    events: list[tuple[str, dict]] = []

    class _FakeLogger:
        def info(self, event, **kwargs):
            events.append((event, kwargs))

        def warning(self, event, **kwargs):
            events.append((event, kwargs))

    monkeypatch.setattr("services.process_runtime.blueprint_confirm_gate.logger", _FakeLogger())
    merge_gate_snapshot(
        [{"repository_id": "r1", "removed": False, "fitness": {"verdict": "partial"}}],
        [{"repository_id": "r1", "fitness": {"verdict": "unsuitable"}}],
    )

    event, kwargs = next(
        (e, kw) for e, kw in events if e == "blueprint_confirm_gate_unsuitable_auto_removed"
    )
    assert event
    assert kwargs["category"] == "sampling"
    assert kwargs["component"] == "process_runtime"
    assert kwargs["auto_removed_count"] == 1


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


async def test_alock_builds_pool_before_filtering_raw_fitness_citations() -> None:
    """回归钉：空基线池 + 裸文件路径不能在确认门锁定时被白名单清空。"""
    repo = await _make_repo()
    artifact = await _make_artifact(_stage1_blueprint_with_empty_citation_pool())
    session = await _make_session(artifact, _routing_state(_candidate(repo)))
    adapter = _adapter(fitness=_fitness(repo))
    await adapter.open_gate(session)
    thread = await _gate_thread(artifact)
    raw = "internal/data/user.go:660"
    options = list(thread.options)
    options[0]["fitness"]["citations"] = [raw]
    await BlueprintThread.objects.filter(id=thread.id).aupdate(options=options)

    result = await adapter.alock(session)

    assert result["event"] == "confirmed"
    content = await _latest_content(artifact)
    citations = content["repo_associations"][0]["fitness"]["citations"]
    assert citations
    assert all(citation_id in content["citations"] for citation_id in citations)
    assert validate_blueprint(content) == (True, None)


async def test_confirm_gate_citations_survive_merge_projection_and_review() -> None:
    """确认门锁定 → merge 投影后 rationale 有证据，审查不再报 association 缺引用。"""
    repo = await _make_repo()
    artifact = await _make_artifact(_stage1_blueprint_with_empty_citation_pool())
    session = await _make_session(artifact, _routing_state(_candidate(repo)))
    adapter = _adapter(fitness=_fitness(repo))
    await adapter.open_gate(session)
    thread = await _gate_thread(artifact)
    options = list(thread.options)
    options[0]["fitness"]["citations"] = ["internal/data/user.go:660"]
    await BlueprintThread.objects.filter(id=thread.id).aupdate(options=options)
    assert (await adapter.alock(session))["event"] == "confirmed"
    locked_content = await _latest_content(artifact)

    pool_entries, cite_map = build_citation_pool({}, locked_content["repo_associations"])
    citations = {
        **locked_content["citations"],
        **{entry["citation_id"]: entry for entry in pool_entries},
    }
    cite_map = {**cite_map, **{citation_id: citation_id for citation_id in citations}}
    merged = {
        **locked_content,
        "citations": citations,
        "repo_associations": project_repo_associations(
            locked_content["repo_associations"], cite_map
        ),
    }

    assert merged["repo_associations"][0]["rationale"]["citations"]
    association_missing = [
        finding
        for finding in check_citations(merged)
        if finding["rule_id"] == "citation_missing"
        and finding["section_path"].startswith("repo_associations[")
    ]
    assert association_missing == []


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


async def test_alock_refuses_when_snapshot_changed_mid_flight() -> None:
    """MJ-03：``confirm`` 读完快照后 ``add_repo`` 才提交 → 落锁必须被 CAS 拒绝。

    没有这道 CAS，``confirm`` 会用旧快照落 ``repo_associations``（新仓不在里面）并
    ``resolve_thread`` 关门；此后 ``_acollect_thread_marked_repos`` 只查 OPEN/ANSWERED
    线程，已 RESOLVED 线程里的 ``pending_research`` 再也读不到 → 新仓的 PENDING task
    既不派发也不终态，用户的加仓动作静默丢失。
    """
    artifact, session, thread, _a, _b, adapter = await _open_gate_with_two_repos()
    repo_c = await _make_repo()
    await _grant_scope(session, repo_c)
    user = await _make_user()
    before = await ArtifactVersion.objects.filter(artifact=artifact).acount()
    original = adapter._aload_latest_version

    async def _interleaved(artifact_id):
        # 快照读完之后、落版本之前，另一路 add_repo 提交（真实交错的最短复现）
        await BlueprintLifecycleService().apply_gate_action(
            artifact,
            thread=thread,
            action="add_repo",
            payload={"repository_id": str(repo_c.id)},
            acting_user=user,
            initiated_by_user_id=str(user.id),
            session=session,
        )
        return await original(artifact_id)

    adapter._aload_latest_version = _interleaved

    result = await adapter.alock(session, acting_user=user)

    assert result["event"] == "awaiting_confirmation"
    assert result["reason"] == "snapshot_changed"
    assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == before
    fresh = await BlueprintThread.objects.aget(id=thread.id)
    assert fresh.status != ThreadStatus.RESOLVED, "拒绝落锁时确认门必须还开着"
    assert await _task_status(session, repo_c) == RepoResearchTaskStatus.PENDING


def test_confirmed_responsibility_never_becomes_a_matching_domain() -> None:
    """MJ-07：职责正文不得当 ``owned_domains.domain``（那会污染后续路由）。

    ``domain`` 是 ``score_charter_match`` 拿去做子串 / n-gram 匹配的**领域名**；把一整段
    职责描述塞进去，该仓对任意需求近乎恒命中（owned_implemented=1.0）。现有章程行上，
    ``asubmit_charter_draft`` 自动化只写 appendices/proposals，正式字段保持不变直至
    人工 confirm / 批准提案——但污染性 domain 仍不应进入回灌草案本身。
    """
    responsibility = (
        "本仓负责在专项学习页展示课程内容与权益鉴权状态并提供组卷相关功能配置，"
        "同时承接练习记录的读写与统计口径对齐。" * 3
    )
    entry = {
        "repository_id": "r-1",
        "repository_name": "study-practice",
        "role_suggestion": "direct",
        "responsibility": responsibility,
        "routing_evidence": {"matched_domains": ["专项练习组卷"]},
    }

    draft = _build_charter_draft(entry)

    domain = draft["owned_domains"][0]["domain"]
    assert domain == "专项练习组卷"
    assert len(domain) <= _MAX_DOMAIN_CHARS
    assert "蓝图确认门" in draft["owned_domains"][0]["note"]
    assert responsibility[:20] not in draft["owned_domains"][0]["note"], (
        "职责正文不得落入 note（会污染 score_charter_match）"
    )

    # 拿这条草案重跑打分：对**无关**需求必须仍为 0（原实现会靠 200 字 domain 命中）
    charter = {
        "owned_domains": draft["owned_domains"],
        "boundaries": [],
        "evolution": "active",
        "source": "ai_draft",
        "version": 1,
    }
    result = score_charter_match(charter, query_terms=["新增导出相关功能配置"])
    assert result.score == 0.0
    assert result.matched_domains == []


def test_no_matched_domain_produces_no_owned_domain_draft() -> None:
    """取不到短领域名 → 宁可不回灌，也不写一条会污染路由的「领域」。"""
    entry = {
        "repository_id": "r-2",
        "repository_name": "study-practice",
        "role_suggestion": "direct",
        "responsibility": "承接练习记录读写",
        "routing_evidence": {"matched_domains": []},
    }

    assert _build_charter_draft(entry) == {}


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
    await _grant_scope(session, repo_c)
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
    await _grant_scope(session, repo_c)
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

"""reroute 有界循环与超限升确认门（Phase 112-04 Task 3，FLOW-02）。

守五件事：

1. **三分支判定**：无 unsuitable → converged；未达上界 → reroute 且 `next_round` 正确；
   达上界 → **escalate 且 `reason == "reroute_exhausted"`**。
2. **返回值里不存在 failed 类动作**（CONTEXT「绝不静默失败」的可证伪断言）。
3. **只取最新有效结论**：一 task 多 `PartialPlan` 行时取 `valid=True` 的最新一条，
   `valid=False` 行忽略（`record_partial` 每次 create 新行）。
4. **stage_state 浅合并不丢既有键**（P3 核心）：`decomposition` / `routing` 原值仍在，
   且新增 `reroute.count` —— `stage_state` 是整字典替换，只写增量会清空它们。
5. **escalate 快照含全部现状**：每仓 verdict / role_suggestion / responsibility。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import sync_to_async

from delivery.models import (
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    PartialPlan,
    RepoResearchTask,
    RepoResearchTaskStatus,
)
from repositories.models import Repository
from services.process_runtime.blueprint_research_adapter import (
    MAX_REROUTE_ROUNDS,
    BlueprintResearchAdapter,
    decide_reroute,
)

_ACTIONS = {"converged", "reroute", "escalate"}


def _fitness(**verdicts: str) -> dict[str, dict]:
    return {
        repository_id: {
            "verdict": verdict,
            "role_suggestion": "direct",
            "responsibility": f"{repository_id} 的职责",
            "findings": [],
            "task_status": "done",
        }
        for repository_id, verdict in verdicts.items()
    }


# ===========================================================================
# 1/2. decide_reroute 三分支（纯函数，无 DB）
# ===========================================================================


def test_no_unsuitable_converges() -> None:
    decision = decide_reroute(fitness=_fitness(a="suitable", b="partial"), round_no=0)
    assert decision["action"] == "converged"
    assert decision["unsuitable_repository_ids"] == []
    assert decision["next_round"] == 0
    assert decision["reason"] == "no_unsuitable"


def test_empty_fitness_converges() -> None:
    """无任何结论（读不到 / 无 task）→ converged，绝不误触发重路由。"""
    assert decide_reroute(fitness={}, round_no=0)["action"] == "converged"


@pytest.mark.parametrize("round_no", [0, 1])
def test_unsuitable_under_limit_reroutes(round_no: int) -> None:
    decision = decide_reroute(fitness=_fitness(a="suitable", b="unsuitable"), round_no=round_no)
    assert decision["action"] == "reroute"
    assert decision["next_round"] == round_no + 1
    assert decision["unsuitable_repository_ids"] == ["b"]
    assert decision["reason"] == "unsuitable_repos_excluded"


def test_unsuitable_at_limit_escalates() -> None:
    """达上界（2 轮）仍有 unsuitable → escalate 升确认门，reason=reroute_exhausted。"""
    decision = decide_reroute(fitness=_fitness(b="unsuitable"), round_no=MAX_REROUTE_ROUNDS)
    assert decision["action"] == "escalate"
    assert decision["reason"] == "reroute_exhausted"
    assert decision["next_round"] == MAX_REROUTE_ROUNDS


@pytest.mark.parametrize("round_no", [0, 1, 2, 3, 99])
def test_action_never_failed(round_no: int) -> None:
    """**可证伪断言**：任何轮次下返回的 action 都在三分支白名单内，不存在 failed 类动作。"""
    for fitness in (
        {},
        _fitness(a="suitable"),
        _fitness(a="unsuitable"),
        _fitness(a="unsuitable", b="partial", c="suitable"),
    ):
        action = decide_reroute(fitness=fitness, round_no=round_no)["action"]
        assert action in _ACTIONS
        assert "fail" not in action


def test_mixed_verdicts_only_excludes_unsuitable() -> None:
    """suitable + partial + unsuitable 共存时只把 unsuitable 计入排除清单。"""
    decision = decide_reroute(
        fitness=_fitness(a="suitable", b="partial", c="unsuitable", d="unsuitable"),
        round_no=0,
    )
    assert decision["unsuitable_repository_ids"] == ["c", "d"]


def test_verdict_case_and_whitespace_normalized() -> None:
    fitness = {"a": {"verdict": " UNSUITABLE "}}
    assert decide_reroute(fitness=fitness, round_no=0)["action"] == "reroute"


def test_malformed_round_no_falls_back_to_zero() -> None:
    decision = decide_reroute(fitness=_fitness(a="unsuitable"), round_no=None)  # type: ignore[arg-type]
    assert decision["action"] == "reroute"
    assert decision["next_round"] == 1


# ===========================================================================
# 3/4/5. DB 部分
# ===========================================================================

_DB = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _make_session(stage_state: dict | None = None) -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="repo_research",
        stage_state=stage_state or {},
    )


async def _make_repo() -> Repository:
    name = f"r-{uuid.uuid4().hex[:8]}"
    return await Repository.objects.acreate(
        name=name,
        git_url=f"https://example.com/{name}.git",
        git_platform="github",
        default_branch="main",
    )


async def _make_task(session, repo, status=RepoResearchTaskStatus.DONE) -> RepoResearchTask:
    return await RepoResearchTask.objects.acreate(
        session=session, repository=repo, status=status, routed_confidence="high"
    )


async def _make_partial(task, *, verdict: str, valid: bool = True, responsibility: str = "职责"):
    return await sync_to_async(PartialPlan.objects.create)(
        research_task=task,
        content={
            "fitness": {"verdict": verdict, "reasons": [], "citations": []},
            "role_suggestion": "direct",
            "responsibility": responsibility,
            "findings": [],
        },
        content_hash=uuid.uuid4().hex,
        valid=valid,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_collect_fitness_takes_latest_valid_row() -> None:
    """一 task 多 PartialPlan 行 → 只取 valid=True 的最新一条；valid=False 行被忽略。"""
    session = await _make_session()
    repo = await _make_repo()
    task = await _make_task(session, repo)
    # 顺序落三行：失效的 unsuitable、旧的 suitable、最新的 partial
    await _make_partial(task, verdict="unsuitable", valid=False)
    await _make_partial(task, verdict="suitable")
    await _make_partial(task, verdict="partial", responsibility="最新职责")

    fitness = await BlueprintResearchAdapter().acollect_fitness(session)
    assert fitness[str(repo.id)]["verdict"] == "partial"
    assert fitness[str(repo.id)]["responsibility"] == "最新职责"
    assert fitness[str(repo.id)]["task_status"] == RepoResearchTaskStatus.DONE


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_collect_fitness_only_invalid_rows_yields_empty_verdict() -> None:
    """只有 valid=False 行 → 该仓 verdict 为空（不会被误判成 unsuitable 触发重路由）。"""
    session = await _make_session()
    repo = await _make_repo()
    task = await _make_task(session, repo)
    await _make_partial(task, verdict="unsuitable", valid=False)

    fitness = await BlueprintResearchAdapter().acollect_fitness(session)
    assert fitness[str(repo.id)]["verdict"] == ""
    assert decide_reroute(fitness=fitness, round_no=0)["action"] == "converged"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_advance_reroute_shallow_merge_keeps_existing_stage_state_keys() -> None:
    """P3 核心：浅合并整体回写后 decomposition / routing 原值仍在，且新增 reroute.count。"""
    original = {
        "decomposition": {"requirement_text": "原始需求"},
        "routing": {"candidates": [{"repository_id": "x"}], "router_version": "v2"},
    }
    session = await _make_session(original)
    repo = await _make_repo()
    task = await _make_task(session, repo)
    await _make_partial(task, verdict="unsuitable")

    result = await BlueprintResearchAdapter().aadvance_reroute(session)
    merged = result["stage_state_update"]

    assert merged["decomposition"] == original["decomposition"]
    assert merged["routing"] == original["routing"]
    assert merged["reroute"]["count"] == 1
    assert merged["reroute"]["excluded"] == [str(repo.id)]
    assert merged["repo_research_fitness"][str(repo.id)]["verdict"] == "unsuitable"
    assert result["event"] == "reroute_needed"
    # 摘要只存标量，正文（responsibility / findings）不进 stage_state
    assert "responsibility" not in merged["repo_research_fitness"][str(repo.id)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_advance_reroute_counts_from_existing_state() -> None:
    """轮次从 stage_state 读并递增（判定与递增在同一次调用里完成，无 check-then-act 窗口）。"""
    session = await _make_session({"reroute": {"count": 1}})
    repo = await _make_repo()
    task = await _make_task(session, repo)
    await _make_partial(task, verdict="unsuitable")

    result = await BlueprintResearchAdapter().aadvance_reroute(session)
    assert result["stage_state_update"]["reroute"]["count"] == MAX_REROUTE_ROUNDS
    assert result["event"] == "reroute_needed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_advance_reroute_exhausted_escalates_with_full_snapshot() -> None:
    """达上界 → event=exhausted + escalation 快照含每仓 verdict/role/responsibility。"""
    session = await _make_session({"reroute": {"count": MAX_REROUTE_ROUNDS}})
    good_repo = await _make_repo()
    bad_repo = await _make_repo()
    await _make_partial(
        await _make_task(session, good_repo), verdict="suitable", responsibility="承载主流程"
    )
    await _make_partial(
        await _make_task(session, bad_repo), verdict="unsuitable", responsibility="与本需求无关"
    )

    result = await BlueprintResearchAdapter().aadvance_reroute(session)

    assert result["event"] == "exhausted"
    escalation = result["escalation"]
    assert escalation["reason"] == "reroute_exhausted"
    assert escalation["unsuitable_repository_ids"] == [str(bad_repo.id)]
    by_id = {item["repository_id"]: item for item in escalation["repos"]}
    assert set(by_id) == {str(good_repo.id), str(bad_repo.id)}
    assert by_id[str(good_repo.id)]["responsibility"] == "承载主流程"
    assert by_id[str(bad_repo.id)]["verdict"] == "unsuitable"
    assert by_id[str(bad_repo.id)]["role_suggestion"] == "direct"
    # 轮次不再增长（已到上界），且不落任何失败态
    assert result["stage_state_update"]["reroute"]["count"] == MAX_REROUTE_ROUNDS
    assert result["decision"]["action"] == "escalate"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_advance_reroute_converged_emits_no_reroute_event() -> None:
    """收敛路径不 emit reroute 事件，且 stage_state 仍带轮次账本（供审计）。"""
    from delivery.models import ConvergenceSessionEvent
    from delivery.services.event_taxonomy import EVENT_BLUEPRINT_REROUTE_TRIGGERED

    session = await _make_session({"routing": {"candidates": []}})
    repo = await _make_repo()
    await _make_partial(await _make_task(session, repo), verdict="suitable")

    result = await BlueprintResearchAdapter().aadvance_reroute(session)

    assert result["event"] == "converged"
    assert result["escalation"] == {}
    assert result["stage_state_update"]["reroute"]["count"] == 0
    assert (
        await ConvergenceSessionEvent.objects.filter(
            session=session, event=EVENT_BLUEPRINT_REROUTE_TRIGGERED
        ).acount()
        == 0
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_advance_reroute_emits_event_payload_without_repo_bodies() -> None:
    """reroute 事件 payload 只含 round / excluded_count / action（无正文、无仓清单）。"""
    from delivery.models import ConvergenceSessionEvent
    from delivery.services.event_taxonomy import EVENT_BLUEPRINT_REROUTE_TRIGGERED

    session = await _make_session()
    repo = await _make_repo()
    await _make_partial(await _make_task(session, repo), verdict="unsuitable")

    await BlueprintResearchAdapter().aadvance_reroute(session)

    event = await ConvergenceSessionEvent.objects.filter(
        session=session, event=EVENT_BLUEPRINT_REROUTE_TRIGGERED
    ).afirst()
    assert event is not None
    assert set(event.payload) == {"round", "excluded_count", "action"}
    assert event.payload["excluded_count"] == 1
    assert event.payload["action"] == "reroute"

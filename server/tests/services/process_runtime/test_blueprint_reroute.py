"""reroute 有界循环与超限升确认门（Phase 112-04 Task 3，FLOW-02）。

守五件事（另加 GAP-1 闭环的第 6 组「排除 + 补候选真的发生」）：

1. **三分支判定**：无 unsuitable → converged；未达上界 → reroute 且 `next_round` 正确；
   达上界 → **escalate 且 `reason == "reroute_exhausted"`**。
2. **返回值里不存在 failed 类动作**（CONTEXT「绝不静默失败」的可证伪断言）。
3. **只取最新有效结论**：一 task 多 `PartialPlan` 行时取 `valid=True` 的最新一条，
   `valid=False` 行忽略（`record_partial` 每次 create 新行）。
4. **stage_state 浅合并不丢既有键**（P3 核心）：`decomposition` / `routing` 原值仍在，
   且新增 `reroute.count` —— `stage_state` 是整字典替换，只写增量会清空它们。
5. **escalate 快照含全部现状**：每仓 verdict / role_suggestion / responsibility。
6. **GAP-1 闭环（可证伪空转）**：reroute 轮必须在排除集之外**真的补到新仓**——第 2 轮
   派发集合与第 1 轮不同且不含被排除仓；被排除仓在后续任何轮次都不再出现；补不到新候选
   才升确认门（带全部现状）；补候选不会突破 ≤2 轮上界。
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


class _FakeRoute:
    """双面路由替身：记录每次 `exclude_repository_ids`，按脚本逐轮返回候选。

    默认**无视排除集**原样返回脚本里的仓 —— 剔除责任压在被测代码上（若 adapter 不消费
    排除集，`test_excluded_repo_never_reappears_in_later_rounds` 会立刻变红）。
    """

    def __init__(self, *rounds: list[Repository]) -> None:
        self._rounds = list(rounds)
        self.exclusions: list[set[str]] = []
        self.await_count = 0

    async def route(self, session, *, exclude_repository_ids=None) -> dict:
        self.await_count += 1
        self.exclusions.append({str(rid) for rid in (exclude_repository_ids or set())})
        repos = self._rounds.pop(0) if self._rounds else []
        return {
            "router_version": "v2",
            "auto_selected": False,
            "intent": "brownfield",
            "weights_used": {},
            "charter_supplement_count": 0,
            "unjustified_boundary_hit_count": 0,
            "candidates": [_candidate(repo) for repo in repos],
            "citations": [],
        }


def _candidate(repo: Repository) -> dict:
    """indirect 候选：走服务端轻量合成，无需 runner / dispatcher 即可观察派发集合。"""
    return {
        "repository_id": str(repo.id),
        "repository_name": repo.name,
        "role_suggestion": "indirect",
        "confidence": "low",
        "total": 0.3,
        "breakdown": {"router_base": 0.3, "charter_match": 0.0, "history_match": 0.0},
        "evidence": {"matched_node_paths": [], "matched_domains": []},
    }


async def _dispatch_repo_ids(adapter: BlueprintResearchAdapter, session) -> set[str]:
    """跑一轮 dispatch 并返回**本轮真正被派发**的仓集合（按新建/重派的 task 反查）。"""
    result = await adapter.dispatch(session)
    task_ids = result["tasks"]
    return {
        str(repository_id)
        async for repository_id in RepoResearchTask.objects.filter(id__in=task_ids).values_list(
            "repository_id", flat=True
        )
    }


async def _apply(session, result: dict) -> None:
    """模拟 engine 的 transition 落 stage_state（handler 原样回写整字典）。"""
    session.stage_state = result["stage_state_update"]
    await session.asave(update_fields=["stage_state"])


async def _make_partial(
    task,
    *,
    verdict: str,
    valid: bool = True,
    responsibility: str = "职责",
    reasons: list | None = None,
    citations: list | None = None,
):
    return await sync_to_async(PartialPlan.objects.create)(
        research_task=task,
        content={
            "fitness": {
                "verdict": verdict,
                "reasons": reasons or [],
                "citations": citations or [],
            },
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
async def test_collect_fitness_carries_reasons() -> None:
    """⭐ 适配理由随聚合携带：`fitness.reasons` 是确认门快照与蓝图「适配判定」正文的
    唯一来源——只聚合三标量会让该区在快照/锁定/蓝图全程为空（用户实测反馈）。"""
    session = await _make_session()
    repo = await _make_repo()
    task = await _make_task(session, repo)
    await _make_partial(
        task, verdict="partial", reasons=["复用 exam/single 组件即可承载", "缺倒计时组件需新增"]
    )

    fitness = await BlueprintResearchAdapter().acollect_fitness(session)
    assert fitness[str(repo.id)]["reasons"] == [
        "复用 exam/single 组件即可承载",
        "缺倒计时组件需新增",
    ]

    # 反面：fitness.reasons 非 list（半可信容器产物）→ 收敛为空数组，不上抛
    session2 = await _make_session()
    repo2 = await _make_repo()
    task2 = await _make_task(session2, repo2)
    await sync_to_async(PartialPlan.objects.create)(
        research_task=task2,
        content={"fitness": {"verdict": "partial", "reasons": "不是列表"}, "findings": []},
        valid=True,
    )
    fitness2 = await BlueprintResearchAdapter().acollect_fitness(session2)
    assert fitness2[str(repo2.id)]["reasons"] == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_collect_fitness_carries_citations() -> None:
    """⭐ 结构化引用必须随聚合带上：确认门快照只认 `conclusion.citations`，
    容器写进 PartialPlan 的路径若不在这里透出，下游只能看到空数组。"""
    session = await _make_session()
    repo = await _make_repo()
    task = await _make_task(session, repo)
    await _make_partial(
        task,
        verdict="partial",
        citations=["src/exam/single.vue", "src/timer/countdown.ts"],
    )

    fitness = await BlueprintResearchAdapter().acollect_fitness(session)
    assert fitness[str(repo.id)]["citations"] == [
        "src/exam/single.vue",
        "src/timer/countdown.ts",
    ]

    session2 = await _make_session()
    repo2 = await _make_repo()
    task2 = await _make_task(session2, repo2)
    await sync_to_async(PartialPlan.objects.create)(
        research_task=task2,
        content={"fitness": {"verdict": "partial", "citations": "不是列表"}, "findings": []},
        valid=True,
    )
    fitness2 = await BlueprintResearchAdapter().acollect_fitness(session2)
    assert fitness2[str(repo2.id)]["citations"] == []


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
    fresh = await _make_repo()
    task = await _make_task(session, repo)
    await _make_partial(task, verdict="unsuitable")

    result = await BlueprintResearchAdapter(route_adapter=_FakeRoute([fresh])).aadvance_reroute(
        session
    )
    merged = result["stage_state_update"]

    assert merged["decomposition"] == original["decomposition"]
    # routing 顶层键与既有候选原样保留，补候选只**追加**
    assert merged["routing"]["router_version"] == "v2"
    assert merged["routing"]["candidates"][0] == {"repository_id": "x"}
    assert [c["repository_id"] for c in merged["routing"]["candidates"][1:]] == [str(fresh.id)]
    # 轮次账本落 stage_state["reroute"]["count"]（唯一递增点在 aadvance_reroute 内）
    reroute_count = merged["reroute"]["count"]
    assert reroute_count == 1
    assert merged["reroute"]["excluded"] == [str(repo.id)]
    assert merged["reroute"]["supplemented"] == [str(fresh.id)]
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
    fresh = await _make_repo()
    task = await _make_task(session, repo)
    await _make_partial(task, verdict="unsuitable")

    result = await BlueprintResearchAdapter(route_adapter=_FakeRoute([fresh])).aadvance_reroute(
        session
    )
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
    fresh = await _make_repo()
    await _make_partial(await _make_task(session, repo), verdict="unsuitable")

    await BlueprintResearchAdapter(route_adapter=_FakeRoute([fresh])).aadvance_reroute(session)

    event = await ConvergenceSessionEvent.objects.filter(
        session=session, event=EVENT_BLUEPRINT_REROUTE_TRIGGERED
    ).afirst()
    assert event is not None
    assert set(event.payload) == {"round", "excluded_count", "action"}
    assert event.payload["excluded_count"] == 1
    assert event.payload["action"] == "reroute"


# ===========================================================================
# 6. GAP-1 闭环：排除 unsuitable + 补候选真的重调研（可证伪「空转」）
# ===========================================================================


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_second_round_dispatch_set_differs_and_excludes_unsuitable_repo() -> None:
    """**核心证伪断言**：A 判 unsuitable → 第 2 轮派发集合与第 1 轮不同且不含 A。

    空转实现（`excluded` 只写不读、回边不补候选）下第 2 轮派发集合为空 —— 与第 1 轮
    `{A}` 既不「不同且非空」，也证不出「新仓真的进了调研」，本例必红。
    """
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    session = await _make_session({"routing": {"candidates": [_candidate(repo_a)]}})
    adapter = BlueprintResearchAdapter(route_adapter=_FakeRoute([repo_b]))

    first = await _dispatch_repo_ids(adapter, session)
    assert first == {str(repo_a.id)}

    # A 的容器回传 unsuitable（覆盖轻量合成的 partial）
    task_a = await RepoResearchTask.objects.aget(session=session, repository=repo_a)
    await _make_partial(task_a, verdict="unsuitable")

    result = await adapter.aadvance_reroute(session)
    assert result["event"] == "reroute_needed"
    await _apply(session, result)

    second = await _dispatch_repo_ids(adapter, session)
    assert second == {str(repo_b.id)}
    assert second != first
    assert str(repo_a.id) not in second
    # 补候选复用双面路由时把排除集与已试仓一并传下去（不是自己另写一套选仓判据）
    assert str(repo_a.id) in adapter._route_adapter.exclusions[0]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_excluded_repo_never_reappears_in_later_rounds() -> None:
    """被排除仓在后续轮次即便被路由器再次召回也不会回到候选（excluded 真的被消费）。"""
    repo_a = await _make_repo()
    repo_b = await _make_repo()
    repo_c = await _make_repo()
    session = await _make_session({"routing": {"candidates": [_candidate(repo_a)]}})
    # 两轮脚本都把已被排除的 A 原样返回（路由器无状态，不会自己记得排除过谁）
    route = _FakeRoute([repo_a, repo_b], [repo_a, repo_c])
    adapter = BlueprintResearchAdapter(route_adapter=route)

    await _dispatch_repo_ids(adapter, session)
    task_a = await RepoResearchTask.objects.aget(session=session, repository=repo_a)
    await _make_partial(task_a, verdict="unsuitable")

    first = await adapter.aadvance_reroute(session)
    assert first["stage_state_update"]["reroute"]["supplemented"] == [str(repo_b.id)]
    await _apply(session, first)
    round_two = await _dispatch_repo_ids(adapter, session)
    assert round_two == {str(repo_b.id)}

    # 第 2 轮：B 也判 unsuitable，补入 C；A 依旧不得回归
    task_b = await RepoResearchTask.objects.aget(session=session, repository=repo_b)
    await _make_partial(task_b, verdict="unsuitable")
    second = await adapter.aadvance_reroute(session)
    assert second["event"] == "reroute_needed"
    assert second["stage_state_update"]["reroute"]["supplemented"] == [str(repo_c.id)]
    # 排除集累积（A ∪ B），且 A 从未出现在任一轮的补入清单与派发集合里
    assert set(second["stage_state_update"]["reroute"]["excluded"]) == {
        str(repo_a.id),
        str(repo_b.id),
    }
    await _apply(session, second)
    round_three = await _dispatch_repo_ids(adapter, session)
    assert round_three == {str(repo_c.id)}
    assert str(repo_a.id) not in round_three


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_no_new_candidate_escalates_with_full_snapshot() -> None:
    """补不到新候选**才**升确认门，且升门时携带全部现状（绝不静默失败、不空转回边）。"""
    repo_a = await _make_repo()
    good = await _make_repo()
    session = await _make_session({"routing": {"candidates": [_candidate(repo_a)]}})
    await _make_partial(
        await _make_task(session, repo_a), verdict="unsuitable", responsibility="与本需求无关"
    )
    await _make_partial(
        await _make_task(session, good), verdict="suitable", responsibility="承载主流程"
    )
    route = _FakeRoute([])  # 排除集之外没有任何可补候选
    adapter = BlueprintResearchAdapter(route_adapter=route)

    result = await adapter.aadvance_reroute(session)

    assert result["event"] == "exhausted"
    assert result["decision"]["action"] == "escalate"
    escalation = result["escalation"]
    assert escalation["reason"] == "no_new_candidates"
    assert escalation["excluded_repository_ids"] == [str(repo_a.id)]
    by_id = {item["repository_id"]: item for item in escalation["repos"]}
    assert set(by_id) == {str(repo_a.id), str(good.id)}
    assert by_id[str(good.id)]["responsibility"] == "承载主流程"
    assert by_id[str(repo_a.id)]["verdict"] == "unsuitable"
    # 补不到就不白烧一轮：轮次不递增
    assert result["stage_state_update"]["reroute"]["count"] == 0
    assert route.await_count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_refill_failure_escalates_instead_of_looping() -> None:
    """补候选依赖炸掉 → 按「补不到」升门（观测/旁路失败绝不上抛、也绝不空转回边）。"""

    class _BoomRoute:
        async def route(self, session, *, exclude_repository_ids=None):
            raise RuntimeError("router unavailable")

    session = await _make_session()
    repo = await _make_repo()
    await _make_partial(await _make_task(session, repo), verdict="unsuitable")

    result = await BlueprintResearchAdapter(route_adapter=_BoomRoute()).aadvance_reroute(session)

    assert result["event"] == "exhausted"
    assert result["escalation"]["reason"] == "no_new_candidates"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_refill_never_exceeds_two_rounds() -> None:
    """**上界仍成立**：即便每轮都补得到新仓，第 3 次判定必 exhausted，count ≤ 2。"""
    repos = [await _make_repo() for _ in range(4)]
    session = await _make_session({"routing": {"candidates": [_candidate(repos[0])]}})
    route = _FakeRoute([repos[1]], [repos[2]], [repos[3]])
    adapter = BlueprintResearchAdapter(route_adapter=route)

    events: list[str] = []
    counts: list[int] = []
    for index in range(3):
        await _dispatch_repo_ids(adapter, session)
        task = await RepoResearchTask.objects.aget(session=session, repository=repos[index])
        await _make_partial(task, verdict="unsuitable")
        result = await adapter.aadvance_reroute(session)
        events.append(result["event"])
        counts.append(result["stage_state_update"]["reroute"]["count"])
        await _apply(session, result)

    assert events == ["reroute_needed", "reroute_needed", "exhausted"]
    assert counts == [1, MAX_REROUTE_ROUNDS, MAX_REROUTE_ROUNDS]
    assert max(counts) <= MAX_REROUTE_ROUNDS
    # 达上界后不再多花一次路由重跑（第 3 次判定直接 escalate）
    assert route.await_count == 2

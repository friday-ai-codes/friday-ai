"""引用覆盖率门 / 归因回退 / 超界带未决项 / golden 可量测（Phase 113-06 Task 1·3）。

守以下几件事（编号即守护点）：

1. **阈值真的从 SystemSetting 读**：同一份覆盖率 0.5 的样本，阈值 0.9 判不达标、
   阈值 0.5 判通过（若门写死模块常量，两条里必有一条红）。
2. **配置坏了回落模块常量且不抛**：非 JSON / 顶层 list / 缺键 / 值类型错四形态。
3. **分母为 0 返 1.0**：空文档（三类关键结论全空）不被惩罚，门通过。
4. ⭐ **归因两档**：缺口能定位到仓 → 回该仓 `repo_plan` 且带 `back_repository_id`；
   缺口全无仓归属 → 回 `merge` 重融合。混合时取缺口最多的仓；空输入三键全空。
5. **`coverage_gaps` 三类 section 各能被定位**（与 `citation_coverage` 同一遍历口径）。
6. ⭐ **有界回退**：`attempt=0` 不达标 → `retry` 且 `attempt == 1`、**不落版本**。
7. ⭐ **超界出口是 `exhausted`**：**仍落版本**（版本数 +1）、`unresolved` 非空、DB 有
   blocking 澄清线程且 `return_stage == "merge"`；返回值里**不出现 failed**、
   会话未被落终态。
8. **轮次单点串行**：连续两次 `merge()` 后 `stage_state["merge"]["count"]` 递增，
   且 `routing` / `decomposition` / `repo_plan` 等既有键仍在（浅合并整体回写不丢键）。
9. **stage handler 四类必测**（`_h_bp_repo_plan` / `_h_bp_merge`）：deps 未注入 /
   `engine.deps` 整体 None / 正常路径落 stage_state 且 ⭐`current_artifact_version`
   非空 / 依赖抛异常经 engine 兜底落 failed 且 `error["stage"]` 正确；外加
   「adapter 返回怪异 validation_status → 映射到白名单内 event」。
10. **stage 图四跳可达**：`repo_confirmation --confirmed--> repo_plan --plan_complete-->
    merge --merged--> STAGE_DONE`。
11. ⭐ **W1 golden set 可量测**：融合产物写成 golden case → `evaluate_blueprint_golden`
    的 report 里 `citation_coverage` 与 `target_repo_hit_rate` 两个指标都能产出；把门槛
    抬到 1.01 则 `CommandError` 且该 case `passed is False`（证明断言非恒真）。

工厂与替身**复用 113-05 的 `test_blueprint_merge_stage`**（同目录同 basedir，pytest 已把
该目录插进 `sys.path`），不重复造。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import sync_to_async
from django.core.management import call_command
from django.core.management.base import CommandError
from test_blueprint_merge_stage import (  # noqa: E402 — 同目录 basedir，pytest 已插 sys.path
    _CITATION_A,
    _association,
    _make_locked_session,
    _repo_id,
    _repo_plan,
    _run_merge,
)

from delivery.models import (
    ArtifactVersion,
    BlueprintThread,
    BlueprintThreadMessage,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    ThreadKind,
    ThreadStatus,
)
from delivery.services import ConvergenceSessionService
from services.process_runtime import builtin_processes as bp
from services.process_runtime.blueprint_merge import (
    MAX_MERGE_ROUNDS,
    STAGE_STATE_KEY,
    decide_back_target,
)
from services.process_runtime.blueprint_reconcile import coverage_gaps
from services.process_runtime.engine import ProcessEngine
from services.process_runtime.registry import STAGE_DONE, get_process_definition
from system.models import SettingKeys, SystemSetting

# 只挂 django_db：asyncio_mode=auto 会自动标记 async 用例，显式再挂 asyncio 会让本文件
# 的纯函数（同步）用例报「marked with asyncio but not async」警告。
pytestmark = [pytest.mark.django_db(transaction=True)]


# ── 工具 ──────────────────────────────────────────────────────────────────


async def _set_merge_config(value: Any) -> None:
    """写 `blueprint.merge.config`（`value` 为 str 时原样落，用于畸形配置形态）。"""
    raw = value if isinstance(value, str) else json.dumps(value)
    await SystemSetting.objects.aupdate_or_create(
        key=SettingKeys.BLUEPRINT_MERGE_CONFIG, defaults={"value": raw}
    )


async def _half_covered_session(*, stage_state: dict | None = None):
    """覆盖率恰好 0.5 的样本：association 无 citations（未覆盖）+ finding 有 citations。

    分母 = 1 个 `repo_associations` + 1 个 `current_state_analysis.findings` = 2，
    分子 = 1 ⇒ 0.5。缺口定位在 `repo_associations` 且带该仓 id（单仓归因可断言）。
    """
    rid = _repo_id("a")
    session, artifact = await _make_locked_session(_association(rid, citations=[]))
    if stage_state is not None:
        await ConvergenceSession.objects.filter(id=session.id).aupdate(stage_state=stage_state)
        session = await ConvergenceSession.objects.aget(id=session.id)
    return session, artifact, rid, {rid: _repo_plan(rid)}


def _blueprint_with_gaps() -> dict:
    """三类 section 各一条未引用 + 各一条已引用（`coverage_gaps` 定位口径样本）。"""
    return {
        "current_state_analysis": [
            {
                "repository_id": "repo-a",
                "findings": [
                    {"citations": ["cit_x"]},
                    {"citations": []},
                ],
            }
        ],
        "repo_associations": [
            {"repository_id": "repo-a", "rationale": {"citations": ["cit_x"]}},
            {"repository_id": "repo-b", "rationale": {"citations": []}},
        ],
        "impact_analysis": {
            "affected_features": [
                {"feature": "已有据", "citations": ["cit_x"]},
                {"feature": "没有据"},
            ]
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1-3. 覆盖率门（阈值可配 / 配置坏了回默认 / 分母为 0）
# ═══════════════════════════════════════════════════════════════════════════


async def test_threshold_is_read_from_system_setting():
    """同一样本：阈值 0.9 判不达标、阈值 0.5 判通过 ⇒ 门确实读 SystemSetting。"""
    await _set_merge_config({"citation_coverage_min": 0.9})
    session, _artifact, _rid, plans = await _half_covered_session()
    strict, _s = await _run_merge(session, plans=plans)
    assert strict["validation_status"] == "retry", strict
    assert strict["report"]["min"] == 0.9

    await _set_merge_config({"citation_coverage_min": 0.5})
    session2, _a2, _r2, plans2 = await _half_covered_session()
    loose, _s2 = await _run_merge(session2, plans=plans2)
    assert loose["validation_status"] == "passed", loose


@pytest.mark.parametrize(
    "bad_value",
    [
        "not-json-at-all",
        "[1, 2, 3]",
        "",
        json.dumps({"citation_coverage_min": "很高"}),
        json.dumps({"max_merge_rounds": None}),
        json.dumps({}),
    ],
)
async def test_malformed_config_falls_back_to_module_constants(bad_value: str):
    """配置畸形一律回落模块常量（默认 0.8 ⇒ 0.5 的样本仍判不达标）且**不抛**。"""
    await _set_merge_config(bad_value)
    session, _artifact, _rid, plans = await _half_covered_session()
    result, _s = await _run_merge(session, plans=plans)
    assert result["validation_status"] == "retry", result
    assert result["report"]["min"] == pytest.approx(0.8)


async def test_empty_document_coverage_is_one_and_passes_gate():
    """三类关键结论全空 ⇒ `citation_coverage` 返 1.0 ⇒ 门通过（不惩罚未写内容）。"""
    session, artifact = await _make_locked_session()
    before = await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount()
    result, _s = await _run_merge(session, plans={})
    assert result["validation_status"] == "passed", result
    assert await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount() == before + 1


# ═══════════════════════════════════════════════════════════════════════════
# 4-5. 归因两档 + coverage_gaps 三类定位
# ═══════════════════════════════════════════════════════════════════════════


async def test_single_repo_attribution_points_back_to_that_repo_plan():
    """⭐ 缺口能定位到仓 → `back_target == "repo_plan"` 且带 `back_repository_id`。"""
    session, _artifact, rid, plans = await _half_covered_session()
    result, _s = await _run_merge(session, plans=plans)
    assert result["validation_status"] == "retry", result
    assert result["back_target"] == "repo_plan"
    assert result["back_repository_id"] == rid
    assert result["gap_count"] == 1


def test_merge_attribution_when_no_gap_resolves_to_a_repo():
    """⭐ 缺口全在 `impact_analysis` 且无仓归属 → 回 `merge` 重融合。"""
    gaps = [
        {"section": "impact_analysis", "index": 0, "repository_id": ""},
        {"section": "impact_analysis", "index": 1, "repository_id": ""},
    ]
    assert decide_back_target(gaps) == {
        "back_target": "merge",
        "back_repository_id": "",
        "gap_count": 2,
    }


def test_mixed_attribution_picks_the_repo_with_most_gaps():
    gaps = [{"section": "s", "index": i, "repository_id": "A"} for i in range(3)]
    gaps.append({"section": "s", "index": 9, "repository_id": "B"})
    gaps.append({"section": "impact_analysis", "index": 0, "repository_id": ""})
    decision = decide_back_target(gaps)
    assert decision["back_target"] == "repo_plan"
    assert decision["back_repository_id"] == "A"
    assert decision["gap_count"] == 3


def test_decide_back_target_on_empty_gaps_is_all_empty():
    assert decide_back_target([]) == {
        "back_target": "",
        "back_repository_id": "",
        "gap_count": 0,
    }


def test_coverage_gaps_locates_all_three_sections():
    gaps = coverage_gaps(_blueprint_with_gaps())
    located = {(gap["section"], gap["repository_id"]) for gap in gaps}
    assert ("current_state_analysis", "repo-a") in located
    assert ("repo_associations", "repo-b") in located
    assert ("impact_analysis", "") in located
    assert len(gaps) == 3, gaps
    assert all(set(gap) == {"section", "index", "repository_id"} for gap in gaps)


@pytest.mark.parametrize(
    "bad", [None, 42, "text", [], {"current_state_analysis": "nope"}, {"repo_associations": [1, 2]}]
)
def test_coverage_gaps_never_raises_on_malformed_input(bad: Any):
    assert isinstance(coverage_gaps(bad), list)


# ═══════════════════════════════════════════════════════════════════════════
# 6-8. 有界回退 / 超界转 STAGE_DONE 带未决项 / 轮次单点串行
# ═══════════════════════════════════════════════════════════════════════════


async def test_first_failure_returns_retry_without_landing_a_version():
    """⭐ `attempt=0` 不达标 → `retry` 且 `attempt == 1`；中间产物不进版本历史。"""
    session, artifact, _rid, plans = await _half_covered_session()
    before = await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount()
    result, _s = await _run_merge(session, plans=plans)
    assert result["validation_status"] == "retry"
    assert result["attempt"] == 1
    assert result["artifact_version_id"] == ""
    assert await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount() == before
    assert result["stage_state"][STAGE_STATE_KEY]["count"] == 1


async def test_exhausted_still_lands_version_and_carries_unresolved():
    """⭐ 超界 = `exhausted`：仍落版本 + `unresolved` + blocking 澄清；**绝不 failed**。"""
    session, artifact, rid, plans = await _half_covered_session(
        stage_state={STAGE_STATE_KEY: {"count": MAX_MERGE_ROUNDS}}
    )
    before = await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount()

    result, _s = await _run_merge(session, plans=plans)

    assert result["validation_status"] == "exhausted", result
    assert "failed" not in json.dumps(result, default=str)
    assert result["artifact_version_id"]
    assert await ArtifactVersion.objects.filter(artifact_id=artifact.id).acount() == before + 1
    assert result["unresolved"], "超界必须带未决项清单"
    assert all(set(item) == {"section", "index", "repository_id"} for item in result["unresolved"])
    assert result["back_repository_id"] == rid
    assert result["stage_state"][STAGE_STATE_KEY]["unresolved"]
    assert result["stage_state"][STAGE_STATE_KEY]["last_attribution"]["back_target"] == "repo_plan"

    thread = await BlueprintThread.objects.filter(artifact_id=artifact.id).afirst()
    assert thread is not None
    assert thread.kind == ThreadKind.AI_CLARIFICATION
    assert thread.blocking is True
    assert thread.status == ThreadStatus.OPEN
    assert thread.return_stage == "merge", "漏传 return_stage 会让人审恢复退回阶段 1（B3）"

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status != ConvergenceSessionStatus.FAILED


async def test_unresolved_snapshot_carries_no_blueprint_prose():
    """未决项与澄清文本只含段名/序号/仓 id —— 方案正文零外泄（T-113-42）。"""
    session, artifact, _rid, plans = await _half_covered_session(
        stage_state={STAGE_STATE_KEY: {"count": MAX_MERGE_ROUNDS}}
    )
    result, _s = await _run_merge(session, plans=plans)
    assert result["validation_status"] == "exhausted", result

    thread = await BlueprintThread.objects.filter(artifact_id=artifact.id).afirst()
    question = await BlueprintThreadMessage.objects.filter(thread_id=thread.id).afirst()
    assert question is not None
    # 只列段名 + 序号 + 仓 id：段名与覆盖率数字在，结论正文与引用串一律不在
    assert "repo_associations" in question.body
    assert "承担职责" not in question.body, "澄清文本夹带了 responsibility 正文"
    assert "urls.py 已注册 router" not in question.body
    assert _CITATION_A not in question.body
    assert _CITATION_A not in json.dumps(result["unresolved"])


async def test_round_counter_increments_and_keeps_existing_stage_state_keys():
    """轮次只在 merge() 单点递增；`stage_state` 浅合并整体回写不丢既有键。"""
    baseline = {
        "routing": {"candidates": []},
        "decomposition": {"requirement_text": "x"},
        "repo_plan": {"ready_repository_ids": []},
    }
    session, _artifact, _rid, plans = await _half_covered_session(stage_state=dict(baseline))

    first, _s1 = await _run_merge(session, plans=plans)
    assert first["stage_state"][STAGE_STATE_KEY]["count"] == 1
    # handler 单点持久化：测试里手动落盘，模拟 `_h_bp_merge` 的写入
    await ConvergenceSession.objects.filter(id=session.id).aupdate(stage_state=first["stage_state"])
    session = await ConvergenceSession.objects.aget(id=session.id)

    second, _s2 = await _run_merge(session, plans=plans)
    assert second["stage_state"][STAGE_STATE_KEY]["count"] == 2
    for key in baseline:
        assert key in second["stage_state"], f"既有键 {key} 被整体回写清掉了"


# ═══════════════════════════════════════════════════════════════════════════
# 9. stage handler 四类必测（_h_bp_repo_plan / _h_bp_merge）
# ═══════════════════════════════════════════════════════════════════════════


def _engine(**deps: Any) -> ProcessEngine:
    return ProcessEngine(
        session_service=ConvergenceSessionService(),
        deps=SimpleNamespace(**deps) if deps else None,
    )


async def _stage_session(stage: str, stage_state: dict | None = None):
    return await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage=stage,
        stage_state=stage_state or {},
    )


def _repo_plan_double(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "aplan_waves": AsyncMock(return_value={"stage_state_summary": {"waves": {1: ["r1"]}}}),
        "dispatch_plans": AsyncMock(
            return_value={
                "dispatched": 1,
                "synthesized": 0,
                "pending": 1,
                "completed": [],
                "repositories": ["r1"],
            }
        ),
        "acollect_repo_plans": AsyncMock(return_value={}),
        "aall_repo_plans_ready": AsyncMock(return_value=False),
        "aexpire_stale_waiters": AsyncMock(return_value=[]),
        "aredispatch_waiting_repos": AsyncMock(return_value=0),
        "build_stage_state": lambda **kwargs: {"ready_repository_ids": [], "attempts": {}},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_repo_plan_handler_without_deps_stops_for_clarification():
    """⭐ MN-07：缺依赖与 `_h_bp_merge` 同口径返 `needs_clarification`。

    原实现返 `plan_dispatched`（self-loop 回本 stage + `wait_status="waiting_event"`），
    但**没有任何容器被派出、也没有阻塞线程** —— 会话静默挂在等事件态，正是 `_h_bp_merge`
    的 D-W4 逐条论证否掉的形态（「假装推进」）。
    """
    session = await _stage_session("repo_plan")
    for engine in (_engine(), ProcessEngine(deps=None)):
        outcome = await bp._h_bp_repo_plan(session, engine)
        assert outcome.event == "needs_clarification"
        assert outcome.stage_state_update is None


async def test_merge_handler_without_deps_stops_for_clarification():
    """⭐ D-W4：缺依赖返 `needs_clarification` —— **不自旋**（remerge）也**不假装成功**（merged）。"""
    session = await _stage_session("merge")
    for engine in (_engine(), ProcessEngine(deps=None)):
        outcome = await bp._h_bp_merge(session, engine)
        assert outcome.event == "needs_clarification"
        assert outcome.current_artifact_version is None


async def test_repo_plan_handler_writes_stage_state_and_completes():
    session = await _stage_session("repo_plan")
    adapter = _repo_plan_double(
        aall_repo_plans_ready=AsyncMock(return_value=True),
        build_stage_state=lambda **kwargs: {"ready_repository_ids": ["r1"], "attempts": {"r1": 1}},
    )
    engine = _engine(repo_plan=adapter)

    outcome = await bp._h_bp_repo_plan(session, engine)

    assert outcome.event == "plan_complete"
    assert outcome.stage_state_update == {
        "repo_plan": {"ready_repository_ids": ["r1"], "attempts": {"r1": 1}}
    }
    assert adapter.aplan_waves.await_count == 1
    assert adapter.aexpire_stale_waiters.await_count == 1, (
        "barrier 续驱必须清一次超龄 waiter，否则「等的 key 永不出现」的仓永久卡住"
    )


async def test_repo_plan_handler_redispatches_expired_waiters():
    session = await _stage_session("repo_plan")
    adapter = _repo_plan_double(aexpire_stale_waiters=AsyncMock(return_value=["r9"]))
    await bp._h_bp_repo_plan(session, _engine(repo_plan=adapter))
    adapter.aredispatch_waiting_repos.assert_awaited_once()
    assert adapter.aredispatch_waiting_repos.await_args.args[1] == ["r9"]


async def test_repo_plan_handler_does_not_dispatch_while_blocked(monkeypatch):
    """⭐ MJ-02 门控 + MN-06：有 open+blocking 线程 → 整轮不 mark drafting、不派发。

    「裁决前不重派」必须是显式门控；靠让 task 卡在 RUNNING 来物理阻止重派会让人裁决后
    该仓**永远无法重派**。同时展示态不得先被刷成 `drafting`（用户其实在等他回答）。
    """
    marked: list[str] = []

    async def _fake_mark(session):
        marked.append(str(session.id))

    monkeypatch.setattr(bp, "_abp_has_open_blocking_threads", AsyncMock(return_value=True))
    monkeypatch.setattr(bp, "_abp_mark_drafting", _fake_mark)

    session = await _stage_session("repo_plan")
    adapter = _repo_plan_double()
    outcome = await bp._h_bp_repo_plan(session, _engine(repo_plan=adapter))

    assert outcome.event == "needs_clarification"
    assert adapter.dispatch_plans.await_count == 0, "有阻塞线程仍派发 = 再撞同一个环并烧额度"
    assert marked == [], "展示态不得在等人回答时被刷成 drafting（MN-06）"


async def test_repo_plan_handler_writes_no_half_key_when_summary_is_empty():
    session = await _stage_session("repo_plan")
    adapter = _repo_plan_double(build_stage_state=lambda **kwargs: {})
    outcome = await bp._h_bp_repo_plan(session, _engine(repo_plan=adapter))
    assert outcome.stage_state_update is None, "半截键会让下游把「没跑」误当成「跑了但空」"


async def test_merge_handler_backfills_current_artifact_version_on_passed():
    """⭐ `_h_bp_merge` 是本蓝图链首个回填 `current_artifact_version` 的 handler。"""
    session = await _stage_session("merge")
    adapter = SimpleNamespace(
        merge=AsyncMock(
            return_value={
                "validation_status": "passed",
                "artifact_version_id": "ver-123",
                "stage_state": {"merge": {"count": 1}},
            }
        )
    )
    outcome = await bp._h_bp_merge(session, _engine(merge=adapter))
    assert outcome.event == "merged"
    assert outcome.current_artifact_version == "ver-123"
    assert outcome.stage_state_update == {"merge": {"count": 1}}


async def test_merge_handler_maps_exhausted_to_merged_with_unresolved():
    """超界转 STAGE_DONE：event 仍是 `merged`（带未决项），**绝不** failed 出边。"""
    session = await _stage_session("merge")
    adapter = SimpleNamespace(
        merge=AsyncMock(
            return_value={
                "validation_status": "exhausted",
                "artifact_version_id": "ver-9",
                "unresolved": [{"section": "repo_associations", "index": 0, "repository_id": "A"}],
                "stage_state": {"merge": {"count": 3, "unresolved": [{"index": 0}]}},
            }
        )
    )
    outcome = await bp._h_bp_merge(session, _engine(merge=adapter))
    assert outcome.event == "merged"
    assert outcome.current_artifact_version == "ver-9"
    assert outcome.stage_state_update["merge"]["unresolved"]
    assert outcome.error is None


@pytest.mark.parametrize(
    ("status", "back_target", "expected"),
    [
        ("retry", "repo_plan", "repo_rework"),
        ("retry", "merge", "remerge"),
        ("retry", "", "remerge"),
        ("needs_clarification", "merge", "needs_clarification"),
        ("failed", "merge", "needs_clarification"),
        ("完全没见过的状态", "", "needs_clarification"),
        (None, "", "needs_clarification"),
    ],
)
async def test_merge_handler_event_whitelist(status: Any, back_target: str, expected: str):
    """event 白名单：怪异 `validation_status` 也只能映射到已登记 event（否则 engine ValueError）。"""
    session = await _stage_session("merge")
    adapter = SimpleNamespace(
        merge=AsyncMock(return_value={"validation_status": status, "back_target": back_target})
    )
    outcome = await bp._h_bp_merge(session, _engine(merge=adapter))
    assert outcome.event == expected
    stages = get_process_definition("technical_blueprint").stages
    assert outcome.event in stages["merge"].transitions


@pytest.mark.parametrize("stage", ["repo_plan", "merge"])
async def test_handler_exception_lands_failed_with_stage_name(stage: str):
    session = await _stage_session(stage)
    boom = AsyncMock(side_effect=RuntimeError("boom"))
    deps = (
        {"repo_plan": _repo_plan_double(dispatch_plans=boom)}
        if stage == "repo_plan"
        else {"merge": SimpleNamespace(merge=boom)}
    )
    engine = _engine(**deps)

    await engine.advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status == ConvergenceSessionStatus.FAILED
    assert fresh.error["stage"] == stage


# ═══════════════════════════════════════════════════════════════════════════
# 10. stage 图四跳可达
# ═══════════════════════════════════════════════════════════════════════════


def test_stage_graph_reaches_done_in_four_hops():
    stages = get_process_definition("technical_blueprint").stages
    assert stages["repo_confirmation"].transitions["confirmed"] == "repo_plan"
    assert stages["repo_plan"].transitions["plan_complete"] == "merge"
    assert stages["merge"].transitions["merged"] == STAGE_DONE


# ═══════════════════════════════════════════════════════════════════════════
# 11. ⭐ W1 golden set 可量测（复用 111-04 的 command，零指标算法内联）
# ═══════════════════════════════════════════════════════════════════════════


def _write_case(directory: Path, content: dict, *, min_coverage: float) -> Path:
    direct = [
        assoc.get("repository_name")
        for assoc in content.get("repo_associations") or []
        if assoc.get("role") == "direct" and assoc.get("repository_name")
    ]
    case = {
        "name": "case_113",
        "blueprint": content,
        "expected": {
            "min_citation_coverage": min_coverage,
            "min_repo_hit_rate": 0.0,
            "direct_repos": direct,
        },
    }
    path = directory / "case_113.json"
    path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    return path


async def test_merged_blueprint_is_golden_measurable(tmp_path: Path):
    """融合产物写成 golden case → `citation_coverage` 指标可产出、门槛判定生效。"""
    rid = _repo_id("a")
    session, _artifact = await _make_locked_session(_association(rid))
    result, _s = await _run_merge(session, plans={rid: _repo_plan(rid)})
    assert result["validation_status"] == "passed", result
    version = await ArtifactVersion.objects.filter(id=result["artifact_version_id"]).afirst()

    fixtures = tmp_path / "cases"
    fixtures.mkdir()
    case_path = _write_case(fixtures, version.content, min_coverage=0.0)
    report_path = tmp_path / "report.json"

    await sync_to_async(call_command)(
        "evaluate_blueprint_golden",
        fixtures_dir=str(fixtures),
        output_json=str(report_path),
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["total"] == 1
    assert report["failed"] == 0
    metrics = report["cases"][0]["metrics"]
    assert "citation_coverage" in metrics and isinstance(metrics["citation_coverage"], (int, float))
    assert "target_repo_hit_rate" in metrics
    assert isinstance(metrics["target_repo_hit_rate"], (int, float))

    # ⭐ 门槛可判定（证明上面的断言不是恒真）：把覆盖率门槛抬到 1.01 必须非零退出。
    _write_case(fixtures, version.content, min_coverage=1.01)
    with pytest.raises(CommandError):
        await sync_to_async(call_command)(
            "evaluate_blueprint_golden",
            fixtures_dir=str(fixtures),
            output_json=str(report_path),
        )
    strict = json.loads(report_path.read_text(encoding="utf-8"))
    assert strict["cases"][0]["passed"] is False
    assert any("覆盖率" in failure for failure in strict["cases"][0]["failures"])
    assert case_path.exists()

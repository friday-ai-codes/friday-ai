"""ai_review stage 端到端 + BlueprintReviewAdapter 测试（Phase 114-03 Task 3，FLOW-07）。

守十三件事（断言一律**从 DB 重读**，不信返回体）：

1. **handler 四类必测**：``deps.review`` 未注入 / ``engine.deps`` 整体 ``None`` /
   正常返回 ``passed`` 落 ``stage_state`` / adapter 抛异常经 engine 兜底落终态失败且
   ``error["stage"] == "ai_review"``（负向路径不许漏）。外加 ``review_status`` 怪异值
   一律映射到白名单内 event（否则 engine 直接 ``ValueError``）。
2. ⭐ **持续 BLOCKER 不会无限循环**（本文件头号靶子）：恒返同一条 BLOCKER 的判定连跑
   三轮 —— 前两轮打回（蓝图 ``drafting``、``round`` 递增、**版本数不增**），第三次进入
   走 ``review_exhausted`` ⇒ 蓝图 ``pending_review``、``unresolved`` 非空且元素**恰好
   六键无正文**、会话 **不是 FAILED**。配「WARNING 首轮即 passed」的对照证明非恒真。
3. ⭐ **``stage_state`` 的审查桶与融合桶互不覆盖**（T-114-14）：预置带 ``sentinel`` 的
   融合桶，跑一轮后融合桶**逐字不变**且审查桶已写入；并断言两个 ``STAGE_STATE_KEY``
   不相等。桶被覆盖 = 轮次计数归零 = 无限打回循环。
4. **仅 WARNING/INFO 不打回**：``review_passed`` + 蓝图 ``pending_review`` + 线程
   ``blocking is False`` + ``ahas_open_blocking_threads`` 为假（人审可通过）。
5. ⭐ **去重幂等**：同一 ``(rule_id, block_id)`` 连跑两轮 ⇒ finding 线程数**仍为 1**、
   消息数 **+1**（第二条由留痕写、``author_type == "ai"``）、状态仍 ``open``、门仍在。
6. ⭐ **留痕未污染线程状态**（行为 + 源码双断言）：留痕后线程仍 ``open``（若走了会把
   ``open`` 推到 ``answered`` 的作答通道，门就没了）；源码层扫描该通道零命中。
7. **BLOCKER finding 落库形状**：``severity/blocking/kind/return_stage/
   created_on_version/anchor`` 六项逐项断言。
8. **已修复的 finding 被收尾**：第 1 轮产 finding、第 2 轮不再命中 ⇒ 线程 ``resolved``。
9. **``needs_clarification`` 前已 ensure 阻塞线程**：否则续驱会 advance 到步数上限落 FAILED。
10. ⭐ **review 入口消费已作答线程并产新版本（B1）**：版本 +1、``decision_log`` 含该线程
    条目（六键）、线程 ``resolved``、且**审查跑的是新内容**。配「无已作答线程 ⇒ 版本不变」
    的对照，以及「回灌报 conflict ⇒ 不跑规则、直接 needs_clarification」。
11. ⭐ **打回重装不抹掉人工编辑 + 冲突有线程（B3）**：人工编辑产 ``human_edit:`` 版本 →
    桩重装把该块改回 AI 版本 → 再进审查 ⇒ 当前最新版本的该块与人工版本**逐字相等**、
    新开阻塞线程（``return_stage="ai_reviewing"``、question 不含两侧正文）、本轮
    ``needs_clarification``。配「重装未触碰该块 ⇒ 无冲突、审查照常出结论」的对照。
12. ⭐ **新版本落库后线程被重锚（判据 = 版本推进）**：12a 回灌产版本 / 12b **仅重装产
    版本**（0-a/0-b 都不产版本的主路径，专门证伪「以本轮是否产版本为判据」的错误实现）/
    12c 无版本推进则不重锚；重锚抛异常时审查照常出结论且 ``anchored_version_id`` 不回写。
13. **状态全经 lifecycle + CAS 不外泄**：``transition`` 抛并发冲突时审查仍返回合法
    ``review_status``、会话不是 FAILED；源码层无裸改状态的 ``update()``。

``async`` service 跨线程写库 → ``transaction=True``。
"""

from __future__ import annotations

import copy
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from delivery.models import (
    ArtifactVersion,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    ThreadAuthorType,
    ThreadKind,
    ThreadSeverity,
    ThreadStatus,
)
from delivery.services import ConvergenceSessionService
from delivery.services.artifact_service import ArtifactService
from delivery.services.blueprint_lifecycle_service import (
    BlueprintLifecycleService,
    ConcurrentBlueprintTransitionError,
)
from services.process_runtime import blueprint_merge, blueprint_reflow
from services.process_runtime import blueprint_review as review_mod
from services.process_runtime import builtin_processes as bp
from services.process_runtime.blueprint_review import (
    SEVERITY_BLOCKER,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STAGE_STATE_KEY,
    BlueprintReviewAdapter,
    _decide_back_target,
)
from services.process_runtime.engine import ProcessEngine
from services.process_runtime.registry import get_process_definition
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_BLOCK_X = "blk_impl01_how"
_BLOCK_Y = "blk_impl02_how"
_RULE = "citation_missing"
_REPO = "repo-backend"
_ANSWER = "回落到静态题库，并在响应里标记 degraded=true。"

_SERVER_DIR = Path(__file__).resolve().parents[3]
_ADAPTER_SOURCE = (_SERVER_DIR / "services/process_runtime/blueprint_review.py").read_text(
    encoding="utf-8"
)


# ══════════════════════════════════════════════════════════════════════════
# fixture 工厂
# ══════════════════════════════════════════════════════════════════════════


def _finding(
    *,
    rule_id: str = _RULE,
    severity: str = SEVERITY_BLOCKER,
    block_id: str = _BLOCK_X,
    repository_id: str = _REPO,
    detail: str = "关键结论条目缺少引用",
) -> dict:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "section_path": "implementation_overview.items[impl_01].how",
        "block_id": block_id,
        "repository_id": repository_id,
        "detail": detail,
    }


async def _make_session(*, stage_state: dict | None = None, content: dict | None = None):
    """建 artifact（首版即合法蓝图）+ 钉住它的 ai_review 会话，蓝图态置 ``ai_reviewing``。

    状态用**生产 helper** ``_abp_mark_ai_reviewing`` 推进（handler 进 stage 时做的正是这件
    事）：直接调 ``adapter.review`` 的用例若停在 ``""`` 态，出口转移会因非法边被拒 —— 那
    测的就不是审查逻辑而是 fixture 缺陷了。
    """
    artifact = await ArtifactService().create("technical_plan", content or make_blueprint())
    session = await ConvergenceSession.objects.acreate(
        process_type="technical_blueprint",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="ai_review",
        current_artifact_version_id=artifact.current_version_id,
        stage_state=stage_state or {},
        initiated_by_user_id="tester",
    )
    await bp._abp_mark_ai_reviewing(session)
    assert (await _refresh(artifact)).blueprint_status == BlueprintStatus.AI_REVIEWING
    return session, artifact


async def _carry_stage_state(session, result: dict) -> ConvergenceSession:
    """把 adapter 返回的 ``stage_state`` 增量落进会话并重读（直调 adapter 时代替 engine）。"""
    merged = {**(session.stage_state or {}), **(result.get("stage_state") or {})}
    await ConvergenceSession.objects.filter(id=session.id).aupdate(stage_state=merged)
    return await ConvergenceSession.objects.aget(id=session.id)


def _engine(**deps: Any) -> ProcessEngine:
    return ProcessEngine(
        session_service=ConvergenceSessionService(),
        deps=SimpleNamespace(**deps) if deps else None,
    )


def _stub_rules(monkeypatch, findings: list[dict], *, llm: Any = None) -> SimpleNamespace:
    """桩掉判定内核，返回可断言的调用记录（``llm=None`` 走 fail-closed meta finding）。"""
    calls = SimpleNamespace(count=0, contents=[])

    def _run(content, *, charters=None, locked_snapshot=None):
        calls.count += 1
        calls.contents.append(copy.deepcopy(content))
        return [dict(item) for item in findings]

    monkeypatch.setattr(review_mod, "run_mechanical_rules", _run)
    monkeypatch.setattr(review_mod, "agoal_backward_review", AsyncMock(return_value=llm))
    return calls


async def _latest(artifact) -> ArtifactVersion:
    return await ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").afirst()


async def _refresh(artifact):
    from delivery.models import Artifact

    return await Artifact.objects.aget(id=artifact.id)


async def _finding_threads(artifact) -> list[BlueprintThread]:
    return [
        row
        async for row in BlueprintThread.objects.filter(
            artifact=artifact, kind=ThreadKind.AI_REVIEW_FINDING
        ).order_by("created_at")
    ]


async def _answered_thread(artifact, *, block_id: str = _BLOCK_X) -> BlueprintThread:
    """开一条澄清线程并由人类作答 ⇒ 线程进 ``answered``（回灌的输入前提）。

    这里用「人类回答澄清线程」的正当通道；AI 侧留痕一律走留痕通道（守 6）。
    """
    lifecycle = BlueprintLifecycleService()
    thread = await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="生成失败时应该回落到静态题库还是直接报错？",
        anchor={"section_path": "implementation_overview", "block_id": block_id},
    )
    await lifecycle.record_answer(thread, body=_ANSWER)
    return thread


def _set_block_text(content: dict, block_id: str, text: str) -> dict:
    """深拷贝后改某个块的正文（构造「内容真的变了」的新版本）。"""
    updated = copy.deepcopy(content)
    for item in updated["implementation_overview"]["items"]:
        for block in item.get("how") or []:
            if isinstance(block, dict) and block.get("block_id") == block_id:
                block["text"] = text
    return updated


def _block_of(content: dict, block_id: str) -> dict | None:
    for item in content.get("implementation_overview", {}).get("items") or []:
        for block in item.get("how") or []:
            if isinstance(block, dict) and block.get("block_id") == block_id:
                return block
    return None


async def _reenter(session) -> ConvergenceSession:
    """把会话拨回 ``ai_review`` 并重读（模拟打回后经 repo_plan/merge 再次进入本 stage）。"""
    await ConvergenceSession.objects.filter(id=session.id).aupdate(current_stage="ai_review")
    return await ConvergenceSession.objects.aget(id=session.id)


# ══════════════════════════════════════════════════════════════════════════
# 1. handler 四类必测 + 出边白名单
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("engine", ["no_dep", "no_deps_ns"])
async def test_handler_returns_needs_clarification_without_adapter(engine: str) -> None:
    """依赖缺失既不自旋也不假装通过，且先 ensure 阻塞线程（守 1 + 守 9）。"""
    session, artifact = await _make_session()
    target = _engine() if engine == "no_dep" else ProcessEngine(deps=None)

    outcome = await bp._h_bp_ai_review(session, target)

    assert outcome.event == "needs_clarification"
    assert await BlueprintThread.objects.filter(
        artifact=artifact, blocking=True, status=ThreadStatus.OPEN
    ).aexists(), "无线程的 self-loop 会被续驱推到 max_steps 后落 FAILED"


async def test_handler_maps_passed_and_persists_stage_state() -> None:
    session, _artifact = await _make_session()
    adapter = SimpleNamespace(
        review=AsyncMock(
            return_value={
                "review_status": "passed",
                "artifact_version_id": "",
                "stage_state": {STAGE_STATE_KEY: {"round": 0, "blocker_count": 0}},
            }
        )
    )

    await _engine(review=adapter).advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status == ConvergenceSessionStatus.DONE
    assert fresh.stage_state[STAGE_STATE_KEY]["blocker_count"] == 0


async def test_handler_exception_lands_failed_with_stage_name() -> None:
    """负向路径：adapter 真抛异常时由 engine 兜底，``error["stage"]`` 必须指认本 stage。"""
    session, _artifact = await _make_session()
    adapter = SimpleNamespace(review=AsyncMock(side_effect=RuntimeError("boom")))

    await _engine(review=adapter).advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status == ConvergenceSessionStatus.FAILED
    assert fresh.error["stage"] == "ai_review"


@pytest.mark.parametrize(
    ("status", "back_target", "expected"),
    [
        ("passed", "", "review_passed"),
        ("exhausted", "", "review_exhausted"),
        ("retry", "repo_plan", "repo_rework"),
        ("retry", "", "remerge"),
        ("needs_clarification", "", "needs_clarification"),
        ("完全没见过的状态", "", "needs_clarification"),
        (None, "", "needs_clarification"),
    ],
)
async def test_handler_event_whitelist(status: Any, back_target: str, expected: str) -> None:
    """怪异 ``review_status`` 也只能映射到已登记 event（否则 engine 直接 ValueError）。"""
    session, _artifact = await _make_session()
    adapter = SimpleNamespace(
        review=AsyncMock(return_value={"review_status": status, "back_target": back_target})
    )

    outcome = await bp._h_bp_ai_review(session, _engine(review=adapter))

    assert outcome.event == expected
    assert (
        outcome.event
        in get_process_definition("technical_blueprint").stages["ai_review"].transitions
    )


# ══════════════════════════════════════════════════════════════════════════
# 2. ⭐ 持续 BLOCKER 两轮后转 pending_review 携未决清单（且会话不是 FAILED）
# ══════════════════════════════════════════════════════════════════════════


async def test_persistent_blocker_exhausts_into_pending_review_and_never_fails(
    monkeypatch,
) -> None:
    session, artifact = await _make_session()
    _stub_rules(monkeypatch, [_finding()])
    engine = _engine(review=BlueprintReviewAdapter())
    versions_before = await ArtifactVersion.objects.filter(artifact=artifact).acount()

    # 前两轮：归因打回，蓝图回 drafting，轮次递增，**不落版本**。
    for expected_round in (1, 2):
        session = await _reenter(session)
        await engine.advance(session)
        fresh = await ConvergenceSession.objects.aget(id=session.id)
        assert fresh.current_stage in ("repo_plan", "merge"), fresh.current_stage
        assert fresh.stage_state[STAGE_STATE_KEY]["round"] == expected_round
        assert (await _refresh(artifact)).blueprint_status == BlueprintStatus.DRAFTING
        assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == versions_before

    # 第三次进入：轮次用尽 ⇒ 携未决清单进人审。
    session = await _reenter(session)
    await engine.advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    bucket = fresh.stage_state[STAGE_STATE_KEY]
    assert bucket["status"] == "exhausted"
    assert bucket["unresolved"], "超界出口必须携未决清单"
    assert set(bucket["unresolved"][0]) == {
        "rule_id",
        "severity",
        "section_path",
        "block_id",
        "repository_id",
        "thread_id",
    }, "未决项只许含定位标量，绝不夹带正文"
    assert (await _refresh(artifact)).blueprint_status == BlueprintStatus.PENDING_REVIEW
    assert fresh.status != ConvergenceSessionStatus.FAILED, "超界是「待人审」不是「流程失败」"
    assert fresh.status == ConvergenceSessionStatus.DONE


async def test_warning_only_finding_passes_on_the_first_round(monkeypatch) -> None:
    """对照组：把 finding 降到 WARNING ⇒ 首轮即通过（证明上面那条断言非恒真）。"""
    session, artifact = await _make_session()
    _stub_rules(monkeypatch, [_finding(severity=SEVERITY_WARNING)], llm=[])

    result = await BlueprintReviewAdapter().review(session)

    assert result["review_status"] == "passed"
    assert (await _refresh(artifact)).blueprint_status == BlueprintStatus.PENDING_REVIEW


async def test_decide_back_target_has_two_tiers() -> None:
    """归因两档：全部 BLOCKER 同仓 → 回该仓；跨仓 / 无归属 → 回融合重装。"""
    same = _decide_back_target([_finding(), _finding(rule_id="role_mismatch")])
    assert same["back_target"] == "repo_plan" and same["back_repository_id"] == _REPO
    cross = _decide_back_target([_finding(), _finding(repository_id="repo-frontend")])
    assert cross["back_target"] == "" and cross["back_repository_id"] == ""
    assert _decide_back_target([])["blocker_count"] == 0


# ══════════════════════════════════════════════════════════════════════════
# 3. ⭐ 审查桶与融合桶互不覆盖（T-114-14：桶被覆盖 = 无限打回循环）
# ══════════════════════════════════════════════════════════════════════════


async def test_review_bucket_never_overwrites_the_merge_bucket(monkeypatch) -> None:
    merge_bucket = {"count": 1, "status": "passed", "sentinel": "keep-me"}
    session, _artifact = await _make_session(
        stage_state={blueprint_merge.STAGE_STATE_KEY: dict(merge_bucket)}
    )
    _stub_rules(monkeypatch, [_finding(severity=SEVERITY_INFO)], llm=[])

    await _engine(review=BlueprintReviewAdapter()).advance(session)

    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.stage_state[blueprint_merge.STAGE_STATE_KEY] == merge_bucket, (
        "融合桶被覆盖 ⇒ 轮次计数归零 ⇒ 无限打回循环"
    )
    assert STAGE_STATE_KEY in fresh.stage_state


def test_stage_state_key_is_not_the_merge_bucket() -> None:
    assert STAGE_STATE_KEY == "ai_review"
    assert STAGE_STATE_KEY != blueprint_merge.STAGE_STATE_KEY


# ══════════════════════════════════════════════════════════════════════════
# 4. 仅 WARNING/INFO 不打回，且人审不被无关线程挡住
# ══════════════════════════════════════════════════════════════════════════


async def test_warning_findings_do_not_block_human_review(monkeypatch) -> None:
    session, artifact = await _make_session()
    _stub_rules(monkeypatch, [_finding(severity=SEVERITY_WARNING)], llm=[])

    result = await BlueprintReviewAdapter().review(session)

    assert result["review_status"] == "passed"
    threads = await _finding_threads(artifact)
    assert threads and all(row.blocking is False for row in threads)
    assert await BlueprintLifecycleService().ahas_open_blocking_threads(artifact) is False


# ══════════════════════════════════════════════════════════════════════════
# 5/6/7/8. 落库形状 / 去重幂等 / 留痕不改状态 / 消失即收尾
# ══════════════════════════════════════════════════════════════════════════


async def test_blocker_finding_thread_shape(monkeypatch) -> None:
    session, artifact = await _make_session()
    _stub_rules(monkeypatch, [_finding()], llm=[])
    version = await _latest(artifact)

    await BlueprintReviewAdapter().review(session)

    thread = (await _finding_threads(artifact))[0]
    assert thread.severity == ThreadSeverity.BLOCKER
    assert thread.blocking is True
    assert thread.kind == ThreadKind.AI_REVIEW_FINDING
    assert thread.return_stage == "ai_reviewing"
    assert str(thread.created_on_version_id) == str(version.id)
    assert thread.anchor["block_id"] == _BLOCK_X
    assert thread.anchor["section_path"]
    assert thread.anchor["quoted_text"], "quoted_text 留空会让块被删后直接失锚（CLAR-02）"


async def test_same_finding_second_round_appends_note_without_reopening(monkeypatch) -> None:
    session, artifact = await _make_session()
    _stub_rules(monkeypatch, [_finding()], llm=[])
    adapter = BlueprintReviewAdapter()

    first = await adapter.review(session)
    session = await _carry_stage_state(await _reenter(session), first)
    await bp._abp_mark_ai_reviewing(session)
    await adapter.review(session)

    threads = await _finding_threads(artifact)
    assert len(threads) == 1, "同一 (rule_id, block_id) 第 2 轮不得重开线程"
    messages = [
        row
        async for row in BlueprintThreadMessage.objects.filter(thread=threads[0]).order_by(
            "created_at"
        )
    ]
    assert len(messages) == 2
    assert messages[1].author_type == ThreadAuthorType.AI
    assert "第 2 轮仍存在" in messages[1].body
    assert threads[0].status == ThreadStatus.OPEN, "留痕绝不推进线程状态，否则门就没了"
    assert await BlueprintLifecycleService().ahas_open_blocking_threads(artifact) is True


def test_adapter_never_uses_the_answer_channel_for_notes() -> None:
    """源码扫描：finding 留痕只走留痕通道，绝不走会把 open 推到 answered 的作答通道。"""
    assert "record_answer" not in _ADAPTER_SOURCE
    assert "append_note" in _ADAPTER_SOURCE


def test_adapter_has_no_raw_status_or_thread_writes() -> None:
    """INV-6：状态与线程写入只走 service，adapter 不裸改 ORM。"""
    for forbidden in (
        "BlueprintThread.objects.create",
        "BlueprintThread.objects.acreate",
        "BlueprintThread.objects.filter(id",
        "ConvergenceSessionEvent.objects.acreate(",
        "._emit_event(",
    ):
        assert forbidden not in _ADAPTER_SOURCE, forbidden
    # 裸 queryset 写会绕过 lifecycle 的 CAS 守卫（`bucket.update(...)` 是 dict 方法，放行）。
    assert re.search(r"objects[^\n]*\.(update|abulk|bulk_)", _ADAPTER_SOURCE) is None
    assert "blueprint_status =" not in _ADAPTER_SOURCE, "状态只许经 lifecycle.transition 改"


async def test_disappeared_finding_thread_is_resolved(monkeypatch) -> None:
    session, artifact = await _make_session()
    calls = _stub_rules(monkeypatch, [_finding()], llm=[])
    adapter = BlueprintReviewAdapter()
    await adapter.review(session)
    assert calls.count == 1

    monkeypatch.setattr(review_mod, "run_mechanical_rules", lambda *a, **k: [])
    session = await _reenter(session)
    await adapter.review(session)

    threads = await _finding_threads(artifact)
    assert len(threads) == 1
    assert threads[0].status == ThreadStatus.RESOLVED


# ══════════════════════════════════════════════════════════════════════════
# 9. needs_clarification 前先 ensure 阻塞线程
# ══════════════════════════════════════════════════════════════════════════


async def test_needs_clarification_ensures_a_blocking_thread() -> None:
    session, artifact = await _make_session()
    adapter = SimpleNamespace(
        review=AsyncMock(return_value={"review_status": "needs_clarification", "report": {}})
    )
    assert not await BlueprintThread.objects.filter(artifact=artifact).aexists()

    outcome = await bp._h_bp_ai_review(session, _engine(review=adapter))

    assert outcome.event == "needs_clarification"
    thread = await BlueprintThread.objects.filter(artifact=artifact, blocking=True).afirst()
    assert thread is not None and thread.status == ThreadStatus.OPEN
    assert thread.return_stage == "ai_review"


# ══════════════════════════════════════════════════════════════════════════
# 10. ⭐ B1：review 入口消费已作答线程并产新版本
# ══════════════════════════════════════════════════════════════════════════


async def test_review_entry_consumes_answered_threads_and_reviews_the_new_content(
    monkeypatch,
) -> None:
    session, artifact = await _make_session()
    thread = await _answered_thread(artifact)
    calls = _stub_rules(monkeypatch, [], llm=[])
    rewritten = "生成失败时回落到静态题库，并在响应里标记 degraded=true。"

    async def _writer(content, answers, *, session=None):
        assert answers, "生产 writer 必须拿到答案条目"
        return _set_block_text(content, _BLOCK_X, rewritten)

    monkeypatch.setattr(blueprint_reflow, "ablock_section_writer", _writer)
    # ⭐ 包一层 spy 断言「review 入口确实是 `aapply_thread_answers` 的生产调用方」——
    # 少了这条，版本 +1 也可能是别的路径产生的，B1 的接线并未被真正证明（T-114-16b）。
    real_reflow = blueprint_reflow.aapply_thread_answers
    spy = AsyncMock(side_effect=real_reflow)
    monkeypatch.setattr(blueprint_reflow, "aapply_thread_answers", spy)
    before = await ArtifactVersion.objects.filter(artifact=artifact).acount()

    result = await BlueprintReviewAdapter().review(session)

    assert spy.await_count == 1, "review 入口必须无条件消费已作答线程"
    assert result["review_status"] == "passed"
    assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == before + 1
    latest = await _latest(artifact)
    entries = latest.content["decision_log"]
    entry = next(row for row in entries if str(row["thread_id"]) == str(thread.id))
    assert {
        "thread_id",
        "question",
        "answer",
        "decided_at",
        "decided_by",
        "applied_in_version",
    } <= set(entry)
    assert entry["answer"]
    refreshed = await BlueprintThread.objects.aget(id=thread.id)
    assert refreshed.status == ThreadStatus.RESOLVED
    # ⭐ 审查跑的是**回灌后的新内容**，不是入口那一刻的旧快照。
    assert calls.count == 1
    assert _block_of(calls.contents[0], _BLOCK_X)["text"] == rewritten


async def test_review_entry_without_answered_threads_does_not_add_a_version(monkeypatch) -> None:
    """对照组：无已作答线程 ⇒ 版本行数不变（证明上面那条断言非恒真）。"""
    session, artifact = await _make_session()
    _stub_rules(monkeypatch, [], llm=[])
    before = await ArtifactVersion.objects.filter(artifact=artifact).acount()

    await BlueprintReviewAdapter().review(session)

    assert await ArtifactVersion.objects.filter(artifact=artifact).acount() == before


async def test_answer_reflow_conflict_short_circuits_before_running_the_rules(
    monkeypatch,
) -> None:
    session, _artifact = await _make_session()
    calls = _stub_rules(monkeypatch, [_finding()], llm=[])
    monkeypatch.setattr(
        blueprint_reflow,
        "aapply_thread_answers",
        AsyncMock(return_value={"status": "conflict", "conflict_block_ids": [_BLOCK_X]}),
    )

    result = await BlueprintReviewAdapter().review(session)

    assert result["review_status"] == "needs_clarification"
    assert calls.count == 0, "带着待裁决冲突继续审 = 产出一份马上作废的结论"


# ══════════════════════════════════════════════════════════════════════════
# 11. ⭐ B3：打回重装不抹掉人工编辑，冲突有线程
# ══════════════════════════════════════════════════════════════════════════


async def _human_edited(artifact, *, block_id: str, text: str) -> dict:
    """经 114-04 的人工编辑入口产一条 ``human_edit:`` 版本，返回人工版本的该块。"""
    from delivery.services.blueprint_block_edit import aapply_block_edit

    latest = await _latest(artifact)
    block = copy.deepcopy(_block_of(latest.content, block_id))
    block["text"] = text
    result = await aapply_block_edit(
        artifact,
        [{"op": "replace", "block_id": block_id, "block": block}],
        initiated_by_user_id=str(uuid.uuid4()),
    )
    assert result["status"] == "applied", result
    return block


async def test_rework_does_not_wipe_human_edits_and_opens_a_conflict_thread(
    monkeypatch,
) -> None:
    session, artifact = await _make_session()
    human_block = await _human_edited(artifact, block_id=_BLOCK_X, text="人工改写：必须回落题库。")
    # 桩「重装」：融合侧重跑并 add_version，把人工块改回 AI 版本。
    latest = await _latest(artifact)
    await ArtifactService().add_version(
        artifact,
        _set_block_text(latest.content, _BLOCK_X, "AI 重装覆盖：直接报错。"),
        produced_by_ref="merge:rework",
    )
    calls = _stub_rules(monkeypatch, [_finding()], llm=[])

    result = await BlueprintReviewAdapter().review(session)

    assert result["review_status"] == "needs_clarification"
    assert calls.count == 0, "人工块冲突未裁决前不该继续审"
    restored = await _latest(artifact)
    assert _block_of(restored.content, _BLOCK_X)["text"] == human_block["text"], (
        "重装抹掉了人工编辑 —— 用户的修改静默消失"
    )
    conflict = await BlueprintThread.objects.filter(
        artifact=artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True
    ).afirst()
    assert conflict is not None
    assert conflict.return_stage == "ai_reviewing"
    message = await BlueprintThreadMessage.objects.filter(thread=conflict).afirst()
    assert human_block["text"] not in message.body
    assert "AI 重装覆盖" not in message.body


async def test_rework_untouched_human_block_yields_no_conflict(monkeypatch) -> None:
    """对照组：重装没碰人工块 ⇒ 无冲突线程，审查照常出结论（断言非恒真）。"""
    session, artifact = await _make_session()
    await _human_edited(artifact, block_id=_BLOCK_X, text="人工改写：必须回落题库。")
    latest = await _latest(artifact)
    await ArtifactService().add_version(
        artifact,
        _set_block_text(latest.content, _BLOCK_Y, "AI 重装：只动了另一个块。"),
        produced_by_ref="merge:rework",
    )
    calls = _stub_rules(monkeypatch, [_finding(severity=SEVERITY_WARNING)], llm=[])

    result = await BlueprintReviewAdapter().review(session)

    assert result["review_status"] == "passed"
    assert calls.count == 1
    assert not await BlueprintThread.objects.filter(
        artifact=artifact, kind=ThreadKind.AI_CLARIFICATION, blocking=True
    ).aexists()


# ══════════════════════════════════════════════════════════════════════════
# 12. ⭐ 版本推进即重锚（三条判据路径 + best-effort 降级）
# ══════════════════════════════════════════════════════════════════════════


def _spy_reanchor(monkeypatch, **kwargs) -> AsyncMock:
    spy = AsyncMock(
        return_value={"checked": 1, "reanchored": 1, "orphaned": 0, "skipped": 0}, **kwargs
    )
    monkeypatch.setattr(BlueprintLifecycleService, "areanchor_threads", spy)
    return spy


async def test_reanchor_runs_after_answer_reflow_produces_a_version(monkeypatch) -> None:
    """12a：0-a 产版本路径 —— 重锚被调用，且 ``anchored_version_id`` 回写为最新版本。"""
    session, artifact = await _make_session()
    await _answered_thread(artifact)
    _stub_rules(monkeypatch, [], llm=[])

    async def _writer(content, answers, *, session=None):
        return _set_block_text(content, _BLOCK_X, "回灌改写后的正文。")

    monkeypatch.setattr(blueprint_reflow, "ablock_section_writer", _writer)
    spy = _spy_reanchor(monkeypatch)

    result = await BlueprintReviewAdapter().review(session)

    assert spy.await_count >= 1
    latest = await _latest(artifact)
    assert result["stage_state"][STAGE_STATE_KEY]["anchored_version_id"] == str(latest.id)


async def test_reanchor_runs_on_the_merge_rework_path_without_any_reflow_version(
    monkeypatch,
) -> None:
    """12b ⭐ 专门证伪「以本轮是否产版本为判据」的错误实现。

    构造「**仅融合重装产新版本**、无已作答线程、无人工块」：0-a / 0-b 都不产版本。
    若判据写成「本轮是否落新版本」，重锚在此永不触发 —— 线程 anchor 会一直指向已消失
    的 block（115 的批注全部错位，CLAR-02 明令禁止）。本用例即为那条错误实现的红灯。
    """
    session, artifact = await _make_session()
    first = await _latest(artifact)
    await _make_session()  # 噪声 artifact，确保断言不是碰巧命中
    session.stage_state = {STAGE_STATE_KEY: {"anchored_version_id": str(first.id)}}
    await ConvergenceSession.objects.filter(id=session.id).aupdate(stage_state=session.stage_state)
    session = await ConvergenceSession.objects.aget(id=session.id)
    await ArtifactService().add_version(
        artifact,
        _set_block_text(first.content, _BLOCK_X, "融合重装产出的新正文。"),
        produced_by_ref="merge:rework",
    )
    _stub_rules(monkeypatch, [], llm=[])
    spy = _spy_reanchor(monkeypatch)

    result = await BlueprintReviewAdapter().review(session)

    assert spy.await_count == 1, "仅重装产版本时重锚必须照样触发"
    latest = await _latest(artifact)
    assert result["stage_state"][STAGE_STATE_KEY]["anchored_version_id"] == str(latest.id)


async def test_reanchor_is_skipped_when_no_version_advanced(monkeypatch) -> None:
    """12c：``anchored_version_id`` 已等于最新版本 ⇒ 不做无谓重锚。"""
    session, artifact = await _make_session()
    latest = await _latest(artifact)
    await ConvergenceSession.objects.filter(id=session.id).aupdate(
        stage_state={STAGE_STATE_KEY: {"anchored_version_id": str(latest.id)}}
    )
    session = await ConvergenceSession.objects.aget(id=session.id)
    _stub_rules(monkeypatch, [], llm=[])
    spy = _spy_reanchor(monkeypatch)

    await BlueprintReviewAdapter().review(session)

    assert spy.await_count == 0


async def test_reanchor_failure_does_not_block_review_nor_write_back(monkeypatch) -> None:
    session, _artifact = await _make_session()
    _stub_rules(monkeypatch, [_finding(severity=SEVERITY_WARNING)], llm=[])
    _spy_reanchor(monkeypatch, side_effect=RuntimeError("reanchor boom"))

    result = await BlueprintReviewAdapter().review(session)

    assert result["review_status"] == "passed", "重锚是 best-effort，绝不阻断审查"
    assert result["stage_state"][STAGE_STATE_KEY]["anchored_version_id"] == "", (
        "失败时回写 anchored_version_id 会让下一轮不再重试"
    )


# ══════════════════════════════════════════════════════════════════════════
# 13. 状态转移全经 lifecycle，CAS 冲突绝不外泄
# ══════════════════════════════════════════════════════════════════════════


async def test_transition_cas_conflict_degrades_instead_of_failing(monkeypatch) -> None:
    session, _artifact = await _make_session()
    _stub_rules(monkeypatch, [_finding(severity=SEVERITY_WARNING)], llm=[])
    monkeypatch.setattr(
        BlueprintLifecycleService,
        "transition",
        AsyncMock(side_effect=ConcurrentBlueprintTransitionError("并发冲突")),
    )

    result = await BlueprintReviewAdapter().review(session)

    assert result["review_status"] in ("passed", "needs_clarification")
    assert result["review_status"] == "needs_clarification"
    fresh = await ConvergenceSession.objects.aget(id=session.id)
    assert fresh.status != ConvergenceSessionStatus.FAILED


async def test_review_never_raises_when_everything_breaks(monkeypatch) -> None:
    """整轮异常也只降级成 ``needs_clarification``（上抛 = engine 落终态失败）。"""
    session, _artifact = await _make_session()

    def _boom(*args, **kwargs):
        raise RuntimeError("rules boom")

    monkeypatch.setattr(review_mod, "run_mechanical_rules", _boom)
    monkeypatch.setattr(review_mod, "agoal_backward_review", AsyncMock(return_value=[]))

    result = await BlueprintReviewAdapter().review(session)

    assert result["review_status"] == "needs_clarification"
    assert set(result) == {
        "review_status",
        "artifact_version_id",
        "round",
        "back_target",
        "back_repository_id",
        "report",
        "stage_state",
        "thread_ids",
    }

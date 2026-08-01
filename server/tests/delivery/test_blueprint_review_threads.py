"""AI 审查 findings 线程底座守护（Phase 114-01，FLOW-07）。

守九件事（每条都写成可证伪断言，正反并列）：

1. **severity 落库**：``open_thread(severity=…)`` 三档各自从 DB 重读等于原值，且
   ``status="open"``。
2. **既有调用逐字等价**：不传 ``severity`` 的 112/113 形状调用落库后 ``severity == ""``。
3. ⭐ **不变式 ``blocking == (severity == "blocker")``**：``ai_review_finding`` 的三种错配
   组合一律 ``ValueError`` 且 ``BlueprintThread`` 行数不增；两种合法组合正常落库
   （证明断言非恒真）；非 finding kind 不受该不变式约束。
4. **非法 severity 被拒**：``severity="fatal"`` → ``ValueError`` 且 DB 不写。
5. ⭐ **``append_note`` 不改线程 status**：对 ``open`` 的 BLOCKER finding 留痕后线程仍
   ``open``、消息数 +1、``author_type == "ai"``，且 ``ahas_open_blocking_threads`` 仍为真
   （门还在）。
6. ⭐ **反向断言：``record_answer`` 不可用于 finding 留痕**。本用例证明的是**理由**而非
   允许该用法：``record_answer`` 把线程推到 ``answered`` → 旧口径（``open+blocking``）判
   为无门（人审本会被放行）；而 114-01 的新守卫判据②（``severity=blocker`` 且
   ``status ∈ {open, answered}``）纵深挡住，``transition(→confirmed)`` 仍 ``ValueError``。
7. ⭐ **confirm 守卫无 TOCTOU**：在守卫查询发生的**那一刻**插入一条 ``open+blocking``
   finding（模拟竞态），``transition(→confirmed)`` 仍被拒且 DB ``blueprint_status`` 未变
   （CAS 未执行）；对照组（守卫内不插行）转移成功 ⇒ 断言非恒真。另有源码扫描断言守卫
   调用点确在 ``_apply_transition_sync`` 的 ``with transaction.atomic():`` 之后。
8. **视图/adapter 零事务外二次查询**（源码扫描）：``aunresolved_blocker_count`` 不得与
   ``BlueprintStatus.CONFIRMED`` 出现在 ``delivery/api/`` 的同一文件（文件不存在则跳过，
   保证 114-05 交付后自动生效）。
9. **``_arecord_gate_note`` 行为等价**：委托 ``append_note`` 后最后一条消息仍
   ``author_type == "human"``，线程 status 不变。

async service 跨线程写库 → ``transaction=True``。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from delivery.models import (
    Artifact,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ThreadAuthorType,
    ThreadKind,
    ThreadSeverity,
    ThreadStatus,
)
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

pytestmark = pytest.mark.django_db(transaction=True)

SERVER_DIR = Path(__file__).resolve().parents[2]
_SERVICE_REL = "delivery/services/blueprint_lifecycle_service.py"


async def _make_artifact(blueprint_status: str = "") -> Artifact:
    return await Artifact.objects.acreate(
        artifact_type="technical_plan", blueprint_status=blueprint_status
    )


async def _make_user():
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")


async def _thread_count(artifact: Artifact) -> int:
    return await BlueprintThread.objects.filter(artifact=artifact).acount()


async def _message_count(thread: BlueprintThread) -> int:
    return await BlueprintThreadMessage.objects.filter(thread=thread).acount()


async def _fresh(thread: BlueprintThread) -> BlueprintThread:
    return await BlueprintThread.objects.aget(id=thread.id)


async def _db_status(artifact: Artifact) -> str:
    fresh = await Artifact.objects.aget(id=artifact.id)
    return fresh.blueprint_status


async def _open_finding(
    service: BlueprintLifecycleService,
    artifact: Artifact,
    *,
    severity: str = ThreadSeverity.BLOCKER,
    blocking: bool = True,
) -> BlueprintThread:
    return await service.open_thread(
        artifact,
        kind=ThreadKind.AI_REVIEW_FINDING,
        blocking=blocking,
        question="规则②：关键结论缺 citations",
        severity=severity,
        initiated_by_user_id="reviewer-agent",
    )


# ---- 1. severity 三档落库 ----


@pytest.mark.parametrize(
    ("severity", "blocking"),
    [
        (ThreadSeverity.BLOCKER, True),
        (ThreadSeverity.WARNING, False),
        (ThreadSeverity.INFO, False),
    ],
)
async def test_severity_persisted_for_each_level(severity: str, blocking: bool) -> None:
    artifact = await _make_artifact()
    thread = await _open_finding(
        BlueprintLifecycleService(), artifact, severity=severity, blocking=blocking
    )

    fresh = await _fresh(thread)
    assert fresh.severity == severity
    assert fresh.blocking is blocking
    assert fresh.status == ThreadStatus.OPEN
    assert fresh.kind == ThreadKind.AI_REVIEW_FINDING


# ---- 2. 既有调用逐字等价（不传 severity） ----


async def test_existing_callers_without_severity_persist_empty_string() -> None:
    """112/113 现存形状的调用（不传 severity）落库后 severity 为空串，其余字段不变。"""
    artifact = await _make_artifact()
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="需求边界是否含移动端？",
        options=[{"label": "含", "value": "yes"}],
        return_stage=BlueprintStatus.DRAFTING,
        initiated_by_user_id="spec-gate",
    )

    fresh = await _fresh(thread)
    assert fresh.severity == ""
    assert fresh.kind == ThreadKind.AI_CLARIFICATION
    assert fresh.blocking is True
    assert fresh.status == ThreadStatus.OPEN
    assert fresh.return_stage == BlueprintStatus.DRAFTING


# ---- 3. blocking == (severity == "blocker") 不变式 ----


@pytest.mark.parametrize(
    ("severity", "blocking"),
    [
        (ThreadSeverity.BLOCKER, False),
        (ThreadSeverity.WARNING, True),
        (ThreadSeverity.INFO, True),
    ],
)
async def test_finding_invariant_mismatch_rejected_and_db_untouched(
    severity: str, blocking: bool
) -> None:
    artifact = await _make_artifact()
    before = await _thread_count(artifact)

    with pytest.raises(ValueError, match="blocking == "):
        await _open_finding(
            BlueprintLifecycleService(), artifact, severity=severity, blocking=blocking
        )

    assert await _thread_count(artifact) == before


@pytest.mark.parametrize(
    ("severity", "blocking"),
    [
        (ThreadSeverity.BLOCKER, True),
        (ThreadSeverity.WARNING, False),
    ],
)
async def test_finding_invariant_legal_combinations_persist(severity: str, blocking: bool) -> None:
    """合法组合必须正常落库——否则上一条「错配被拒」是恒真断言。"""
    artifact = await _make_artifact()
    thread = await _open_finding(
        BlueprintLifecycleService(), artifact, severity=severity, blocking=blocking
    )
    assert await _thread_count(artifact) == 1
    assert (await _fresh(thread)).severity == severity


async def test_invariant_only_applies_to_review_findings() -> None:
    """非 finding kind 不受不变式约束：ai_clarification 可以 blocking 而无 severity。"""
    artifact = await _make_artifact()
    thread = await BlueprintLifecycleService().open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question="仓库集是否包含 infra？",
    )
    fresh = await _fresh(thread)
    assert fresh.severity == ""
    assert fresh.blocking is True


# ---- 4. 非法 severity ----


async def test_illegal_severity_rejected_and_db_untouched() -> None:
    artifact = await _make_artifact()
    before = await _thread_count(artifact)

    with pytest.raises(ValueError, match="非法线程 severity"):
        await BlueprintLifecycleService().open_thread(
            artifact,
            kind=ThreadKind.AI_REVIEW_FINDING,
            blocking=True,
            question="x",
            severity="fatal",
        )

    assert await _thread_count(artifact) == before


# ---- 5. append_note 不改线程 status ----


async def test_append_note_keeps_thread_open_and_gate_intact() -> None:
    service = BlueprintLifecycleService()
    artifact = await _make_artifact()
    thread = await _open_finding(service, artifact)
    assert await _message_count(thread) == 1

    message = await service.append_note(thread, body="第 2 轮仍未修复")

    fresh = await _fresh(thread)
    assert fresh.status == ThreadStatus.OPEN, "append_note 绝不推进线程状态"
    assert await _message_count(thread) == 2
    assert message.author_type == ThreadAuthorType.AI
    latest = await BlueprintThreadMessage.objects.filter(thread=thread).alast()
    assert latest is not None and latest.author_type == ThreadAuthorType.AI
    # 门还在：留痕不得让 confirm 守卫误判为无门
    assert await service.ahas_open_blocking_threads(artifact) is True
    assert await service.aunresolved_blocker_count(artifact) == 1


async def test_append_note_then_confirm_still_blocked() -> None:
    """留痕后人审仍不可通过（append_note 的存在理由的正面证据）。"""
    service = BlueprintLifecycleService()
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    thread = await _open_finding(service, artifact)
    await service.append_note(thread, body="第 2 轮仍未修复")

    with pytest.raises(ValueError, match="蓝图不可确认"):
        await service.transition(
            artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="human-reviewer"
        )
    assert await _db_status(artifact) == BlueprintStatus.PENDING_REVIEW


# ---- 6. ⭐ 反向断言：record_answer 不可用于 finding 留痕 ----


async def test_record_answer_on_finding_breaks_legacy_gate_but_new_guard_holds() -> None:
    """**本用例证明的是 ``record_answer`` 不可用于 finding 留痕**，不是允许该用法。

    ``record_answer`` 把 BLOCKER finding 从 ``open`` 推到 ``answered``，旧口径守卫
    （``status=open & blocking=True``）随即判为无门——若守卫仍是旧口径，人审就能通过
    带未决 BLOCKER 的蓝图。114-01 的判据②（``severity=blocker`` 且
    ``status ∈ {open, answered}``）作为纵深防御把这条旁路挡住。
    """
    service = BlueprintLifecycleService()
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    thread = await _open_finding(service, artifact)

    await service.record_answer(thread, body="第 2 轮仍未修复")

    # ① 破坏确实发生：线程被推到 answered，旧口径判为无门
    assert (await _fresh(thread)).status == ThreadStatus.ANSWERED
    assert await service.ahas_open_blocking_threads(artifact) is False
    legacy_gate_open = await BlueprintThread.objects.filter(
        artifact=artifact, status=ThreadStatus.OPEN, blocking=True
    ).aexists()
    assert legacy_gate_open is False, "旧口径守卫此刻已放行——这正是禁用 record_answer 的理由"

    # ② 新守卫纵深挡住：未决 BLOCKER 仍在，transition 被拒且 DB 状态未变
    assert await service.aunresolved_blocker_count(artifact) == 1
    with pytest.raises(ValueError, match="蓝图不可确认"):
        await service.transition(
            artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="human-reviewer"
        )
    assert await _db_status(artifact) == BlueprintStatus.PENDING_REVIEW


# ---- 7. ⭐ confirm 守卫无 TOCTOU ----


async def test_confirm_guard_rejects_thread_created_inside_guard_window(monkeypatch) -> None:
    """守卫查询发生的那一刻线程刚被建出来 —— 仍必须拒绝（无 check-then-act 窗口）。"""
    service = BlueprintLifecycleService()
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    original = BlueprintLifecycleService._has_confirm_blockers_sync

    def racing_guard(target: Artifact) -> bool:
        # 竞态注入：守卫查询前一瞬新建一条 open+blocking finding（与守卫同事务）
        BlueprintThread.objects.create(
            artifact=target,
            kind=ThreadKind.AI_REVIEW_FINDING,
            severity=ThreadSeverity.BLOCKER,
            blocking=True,
            status=ThreadStatus.OPEN,
        )
        return original(target)

    monkeypatch.setattr(
        BlueprintLifecycleService, "_has_confirm_blockers_sync", staticmethod(racing_guard)
    )

    with pytest.raises(ValueError, match="蓝图不可确认"):
        await service.transition(
            artifact, BlueprintStatus.CONFIRMED, initiated_by_user_id="human-reviewer"
        )
    assert await _db_status(artifact) == BlueprintStatus.PENDING_REVIEW, "CAS 未执行"


async def test_confirm_succeeds_without_blockers_control_case() -> None:
    """对照组：无阻塞线程时 confirm 正常放行 ⇒ 上一条并发断言非恒真。"""
    service = BlueprintLifecycleService()
    artifact = await _make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    user = await _make_user()

    await service.transition(
        artifact,
        BlueprintStatus.CONFIRMED,
        initiated_by_user_id=str(user.id),
        acting_user=user,
    )
    assert await _db_status(artifact) == BlueprintStatus.CONFIRMED


def test_confirm_guard_is_called_inside_transaction_atomic() -> None:
    """源码扫描：守卫调用点在 ``_apply_transition_sync`` 的 ``transaction.atomic()`` 之后。"""
    lines = (SERVER_DIR / _SERVICE_REL).read_text(encoding="utf-8").splitlines()
    func_line = next(i for i, line in enumerate(lines) if "def _apply_transition_sync" in line)
    atomic_line = next(
        i
        for i, line in enumerate(lines[func_line:], func_line)
        if "with transaction.atomic():" in line
    )
    guard_line = next(
        i
        for i, line in enumerate(lines[func_line:], func_line)
        if "self._has_confirm_blockers_sync(" in line
    )
    assert func_line < atomic_line < guard_line, (
        "confirm 守卫必须在 _apply_transition_sync 的 transaction.atomic() 内调用，"
        f"实测 func={func_line + 1} atomic={atomic_line + 1} guard={guard_line + 1}"
    )


# ---- 8. 视图/adapter 零事务外二次查询 ----


def test_no_out_of_transaction_blocker_check_before_confirm() -> None:
    """``aunresolved_blocker_count``（仅供报告）不得与 confirm 转移出现在同一 API 文件。

    同现即意味着有人在事务外「先查 BLOCKER 再 transition」，TOCTOU 窗口复活。
    """
    scan_roots = [SERVER_DIR / "delivery" / "api"]
    extra = SERVER_DIR / "services" / "process_runtime" / "blueprint_review.py"
    violations: list[str] = []

    candidates: list[Path] = []
    for root in scan_roots:
        if root.exists():
            candidates.extend(sorted(root.rglob("*.py")))
    if extra.exists():
        candidates.append(extra)

    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if "aunresolved_blocker_count" not in text:
            continue
        if "BlueprintStatus.CONFIRMED" in text or 'to_status="confirmed"' in text:
            violations.append(path.relative_to(SERVER_DIR).as_posix())

    assert not violations, (
        "发现事务外「先查未决 BLOCKER 再 transition」的形状（TOCTOU）："
        + ", ".join(violations)
        + "；守卫判据一律收敛进 _apply_transition_sync 的事务内单次查询"
    )


# ---- 9. _arecord_gate_note 行为等价 ----


async def test_gate_note_still_records_human_author_and_keeps_status() -> None:
    service = BlueprintLifecycleService()
    artifact = await _make_artifact()
    user = await _make_user()
    thread = await service.open_thread(
        artifact,
        kind=ThreadKind.REPO_CONFIRMATION,
        blocking=True,
        question="确认仓库集与职责",
    )

    await service._arecord_gate_note(thread, body="用户确认当前仓库集与职责。", author=user)

    latest = await BlueprintThreadMessage.objects.filter(thread=thread).alast()
    assert latest is not None
    assert latest.author_type == ThreadAuthorType.HUMAN
    assert (await _fresh(thread)).status == ThreadStatus.OPEN
    assert await _message_count(thread) == 2

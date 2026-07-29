"""``expire_pending_clarifications`` 澄清超时出口命令测试（RELY-02，SC-4 后半句）。

覆盖：到期出口（带未澄清假设继续 / 如实失败）、幂等（连跑两次只推进一次只 emit 一次）、
起算时间取 pending 轮 ``created_at``（刷新会话时间戳不影响到期）、旧行 ``container_status``
为 NULL 仍被命中、未澄清点结构与脱敏、触发用户归因、单条失败不影响其余、事务纪律
（``transition`` 调用不在 atomic 块内）。

``transaction=True``：命令内部 ``asyncio.run`` 经独立连接写库，普通 rollback 型
``django_db`` 无法覆盖跨连接提交；TransactionTestCase teardown TRUNCATE 全表。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
import structlog
from django.core.management import call_command
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from delivery.models import (
    Clarification,
    ClarificationQuestion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionEvent,
    ConvergenceSessionStatus,
)
from delivery.services import ConvergenceSessionService
from delivery.services.convergence_session_service import ConcurrentTransitionError

pytestmark = pytest.mark.django_db(transaction=True)

_TIMED_OUT = "clarification.timed_out"


def _make_session(
    *,
    status: str = ConvergenceSessionStatus.WAITING_CLARIFICATION,
    current_stage: str = "clarify",
    initiated_by_user_id: str = "",
    stage_state: dict | None = None,
    node_execution_id: Any = None,
) -> ConvergenceSession:
    return ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage=current_stage,
        status=status,
        stage_state=stage_state or {},
        initiated_by_user_id=initiated_by_user_id,
        node_execution_id=node_execution_id,
    )


def _make_round(
    session: ConvergenceSession,
    *,
    age_hours: float = 48.0,
    answered: bool = False,
    container_status: str | None = "pending",
    questions: tuple[str, ...] = ("需求涉及哪些仓库？", "是否需要灰度开关？"),
    round_no: int = 1,
) -> Clarification:
    """建一轮澄清并把 ``created_at`` 回拨 ``age_hours`` 小时（模拟等待时长）。"""
    clar = Clarification.objects.create(
        session=session,
        question="",
        round_no=round_no,
        container_status=container_status,
    )
    answered_at = timezone.now() if answered else None
    for idx, text in enumerate(questions):
        ClarificationQuestion.objects.create(
            clarification=clar,
            order=idx,
            question=text,
            qtype="single",
            options=[],
            recommended=[],
            answered_at=answered_at,
        )
    if answered:
        Clarification.objects.filter(id=clar.id).update(
            answered_at=timezone.now(), container_status="answered"
        )
    Clarification.objects.filter(id=clar.id).update(
        created_at=timezone.now() - timedelta(hours=age_hours)
    )
    return Clarification.objects.get(id=clar.id)


def _timed_out_events(session: ConvergenceSession) -> int:
    return ConvergenceSessionEvent.objects.filter(
        session_id=session.id, event=_TIMED_OUT
    ).count()


@override_settings(
    CLARIFICATION_TIMEOUT_HOURS=24,
    CLARIFICATION_TIMEOUT_EXIT_ACTION="resume_with_assumptions",
)
def test_expired_round_resumes_with_assumptions() -> None:
    """到期 pending 轮 → 推进到 research/running，stage_state 落 clarification_exit。"""
    session = _make_session()
    clar = _make_round(session, age_hours=48)

    call_command("expire_pending_clarifications")

    reloaded = ConvergenceSession.objects.get(id=session.id)
    assert reloaded.current_stage == "research"
    assert reloaded.status == ConvergenceSessionStatus.RUNNING
    marker = reloaded.stage_state["clarification_exit"]
    assert marker["action"] == "resumed_with_assumptions"
    assert marker["clarification_id"] == str(clar.id)
    assert marker["waited_seconds"] >= 24 * 3600
    assert marker["unclarified_points"]
    assert marker["at"]
    assert _timed_out_events(session) == 1


@override_settings(
    CLARIFICATION_TIMEOUT_HOURS=24,
    CLARIFICATION_TIMEOUT_EXIT_ACTION="resume_with_assumptions",
)
def test_second_scan_is_idempotent() -> None:
    """连跑两次只推进一次、clarification.timed_out 只有 1 行（CAS 幂等，不新建机制）。"""
    session = _make_session()
    _make_round(session, age_hours=48)

    call_command("expire_pending_clarifications")
    call_command("expire_pending_clarifications")

    reloaded = ConvergenceSession.objects.get(id=session.id)
    assert reloaded.current_stage == "research"
    assert _timed_out_events(session) == 1


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24, CLARIFICATION_TIMEOUT_EXIT_ACTION="fail")
def test_exit_action_fail_marks_session_failed_once() -> None:
    """出口动作 fail → status=failed + error 含 clarification_timeout_no_answer，只 emit 一次。"""
    session = _make_session()
    _make_round(session, age_hours=48)

    call_command("expire_pending_clarifications")
    call_command("expire_pending_clarifications")

    reloaded = ConvergenceSession.objects.get(id=session.id)
    assert reloaded.status == ConvergenceSessionStatus.FAILED
    assert reloaded.error.get("reason") == "clarification_timeout_no_answer"
    assert reloaded.stage_state["clarification_exit"]["action"] == "failed_no_answer"
    assert _timed_out_events(session) == 1


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24)
def test_concurrent_transition_conflict_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """并发 CAS 冲突 → 命令不抛、记 noop_concurrent、零 emit（幂等 no-op）。"""
    session = _make_session()
    _make_round(session, age_hours=48)

    async def _conflict(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise ConcurrentTransitionError("并发推进")

    monkeypatch.setattr(ConvergenceSessionService, "transition", _conflict)

    with structlog.testing.capture_logs() as captured:
        call_command("expire_pending_clarifications")

    noop = [e for e in captured if e.get("event") == "clarification_timeout_exit_noop_concurrent"]
    assert noop, f"未记 noop_concurrent 事件；captured={captured}"
    assert noop[0].get("category") == "sampling"
    assert _timed_out_events(session) == 0


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24)
def test_unclarified_points_carry_question_id_and_text() -> None:
    """未澄清点为非空 list，逐条含 question_id 与 question。"""
    session = _make_session()
    clar = _make_round(session, age_hours=48, questions=("仓库范围？", "是否要开关？"))

    call_command("expire_pending_clarifications")

    marker = ConvergenceSession.objects.get(id=session.id).stage_state["clarification_exit"]
    points = marker["unclarified_points"]
    assert isinstance(points, list) and len(points) == 2
    assert {p["question"] for p in points} == {"仓库范围？", "是否要开关？"}
    question_ids = set(
        str(qid)
        for qid in ClarificationQuestion.objects.filter(clarification_id=clar.id).values_list(
            "id", flat=True
        )
    )
    assert {p["question_id"] for p in points} == question_ids


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24)
def test_unclarified_points_are_redacted() -> None:
    """未澄清点正文经既有脱敏 helper（需求原文可能含凭证，V8）。"""
    session = _make_session()
    _make_round(session, age_hours=48, questions=("请确认密钥 sk-ant-abcdefghijklmnopqrstuvwx 是否可用",))

    call_command("expire_pending_clarifications")

    marker = ConvergenceSession.objects.get(id=session.id).stage_state["clarification_exit"]
    text = marker["unclarified_points"][0]["question"]
    assert "sk-ant-abcdefghijklmnopqrstuvwx" not in text


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24)
@pytest.mark.parametrize(
    ("stored", "expected"),
    [("u-42", "u-42"), ("", "system")],
)
def test_exit_log_binds_initiated_by_user(stored: str, expected: str) -> None:
    """出口日志带 initiated_by_user_id：会话有值取该值，为空取 system。"""
    session = _make_session(initiated_by_user_id=stored)
    _make_round(session, age_hours=48)

    with structlog.testing.capture_logs() as captured:
        call_command("expire_pending_clarifications")

    exits = [e for e in captured if e.get("event") == "clarification_timeout_exit"]
    assert exits, f"未记 clarification_timeout_exit 事件；captured={captured}"
    assert exits[0].get("initiated_by_user_id") == expected
    assert exits[0].get("category") == "caller"
    assert exits[0].get("component") == "delivery"


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24)
def test_single_session_failure_does_not_block_others(monkeypatch: pytest.MonkeyPatch) -> None:
    """单条会话处理抛异常 → 其余会话仍被处理，命令不抛。"""
    doomed = _make_session()
    _make_round(doomed, age_hours=48)
    healthy = _make_session()
    _make_round(healthy, age_hours=48)

    original = ConvergenceSessionService.transition

    async def _selective(self: Any, session: Any, event: str, **kwargs: Any) -> Any:
        if str(session.id) == str(doomed.id):
            raise RuntimeError("boom")
        return await original(self, session, event, **kwargs)

    monkeypatch.setattr(ConvergenceSessionService, "transition", _selective)

    call_command("expire_pending_clarifications")

    assert ConvergenceSession.objects.get(id=healthy.id).current_stage == "research"
    assert (
        ConvergenceSession.objects.get(id=doomed.id).status
        == ConvergenceSessionStatus.WAITING_CLARIFICATION
    )


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24)
def test_transition_runs_outside_atomic_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """事务纪律：transition 调用时不在 atomic 块内（Pitfall 9 / T-107-11）。"""
    session = _make_session()
    _make_round(session, age_hours=48)

    original = ConvergenceSessionService.transition
    seen: list[bool] = []

    async def _probe(self: Any, sess: Any, event: str, **kwargs: Any) -> Any:
        seen.append(transaction.get_connection().in_atomic_block)
        return await original(self, sess, event, **kwargs)

    monkeypatch.setattr(ConvergenceSessionService, "transition", _probe)

    call_command("expire_pending_clarifications")

    assert seen == [False]


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24)
def test_start_time_is_round_created_at_not_session_touch() -> None:
    """起算时间取 pending 轮 created_at：刷新会话行后仍命中出口（Pitfall 7）。"""
    session = _make_session()
    _make_round(session, age_hours=48)
    # 刷新会话行（任何无关写都会刷新会话的最后修改时间戳）
    session.stage_state = {"decomposition": {"requirement_text": "x"}}
    session.save(update_fields=["stage_state"])

    call_command("expire_pending_clarifications")

    assert ConvergenceSession.objects.get(id=session.id).current_stage == "research"


@override_settings(CLARIFICATION_TIMEOUT_HOURS=24)
def test_legacy_round_with_null_container_status_is_collected() -> None:
    """旧行 container_status 为 NULL 仍被命中（pending 判定锚 answered_at，不按展示态过滤）。"""
    session = _make_session()
    _make_round(session, age_hours=48, container_status=None)

    call_command("expire_pending_clarifications")

    assert ConvergenceSession.objects.get(id=session.id).current_stage == "research"
    assert _timed_out_events(session) == 1

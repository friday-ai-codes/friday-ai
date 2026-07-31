"""澄清超时提醒的周期路径测试（Phase 114-05 Task 3，CLAR-04 / B4）。

守六件事（断言一律**从 DB 重读**）：

1. ⭐ **模拟时间推进触发提醒**：``created_at`` 回拨 25 小时 → ``aremind_clarification_threads
   (hours=24)`` 报 ``{scanned:1, due:1, reminded:1}``、``last_reminded_at`` 非 None、
   ``updated_at`` 已推进（``bulk_update`` 绕过 ``auto_now``，漏显式带就红）。
2. ⭐ **同一周期内不重复提醒**：紧接再调（不推进时间）→ ``{due:0, reminded:0, skipped:1}``
   且 ``last_reminded_at`` **逐字不变**（防轰炸）；再用 ``now=+25h`` 推进 → 又 reminded 且
   锚点前移（周期语义成立 ⇒ 断言非恒真）。
3. ⭐ **判据状态是 ``needs_clarification`` 不是 ``pending_review``**（正反并列，锁死 B4 的
   口径定夺）；``answered`` / 非 blocking 线程不进扫描面。
4. **提醒对象名单** = ``BlueprintReviewer`` ∪ 会话发起人（去重），且反查会话带
   ``process_type="technical_blueprint"`` 过滤（另造 ``technical_plan`` 会话不影响名单）。
5. ⭐ **不作答、不改状态、不判失败**：线程仍 ``open``、消息数不变（没有偷偷作答）、蓝图
   状态不变、会话不是 FAILED；源码扫描任务体不含作答/收尾/转移三类写。
6. **挂载点存在**（源码扫描，⚠️ **不启动真 scheduler**）：wrapper 可调用、注册块含
   ``id="remind_blueprint_clarifications"`` 与 ``IntervalTrigger``、wrapper **吞掉**任务体
   异常；且测试环境 ``FF_ENABLE_SCHEDULER is False``（零后台线程）。

``sync_to_async`` 跨线程写库 ⇒ ``transaction=True``。
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone

from delivery.models import (
    Artifact,
    BlueprintReviewer,
    BlueprintStatus,
    BlueprintThread,
    BlueprintThreadMessage,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    ThreadKind,
    ThreadStatus,
)
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from delivery.services.blueprint_review_action import aremind_clarification_threads

pytestmark = pytest.mark.django_db(transaction=True)

SERVER_DIR = Path(__file__).resolve().parents[1]
_SCHEDULER_REL = "agents/management/commands/runapscheduler.py"
_TASKS_REL = "tasks/blueprint_reminder_tasks.py"

_remind = async_to_sync(aremind_clarification_threads)


# ── 工厂 ─────────────────────────────────────────────────────────────────────


def _make_artifact(status: str = BlueprintStatus.NEEDS_CLARIFICATION) -> Artifact:
    return Artifact.objects.create(artifact_type="technical_plan", blueprint_status=status)


def _open_thread(artifact: Artifact, *, blocking: bool = True) -> BlueprintThread:
    return async_to_sync(BlueprintLifecycleService().open_thread)(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=blocking,
        question="该接口的鉴权走哪套？",
        initiated_by_user_id="reviewer-agent",
    )


def _age(thread: BlueprintThread, hours: int) -> None:
    """把 ``created_at`` 回拨 —— ``auto_now_add`` 字段不可直接赋值，只能走 queryset。"""
    BlueprintThread.objects.filter(id=thread.id).update(
        created_at=timezone.now() - timedelta(hours=hours)
    )


def _fresh(thread: BlueprintThread) -> BlueprintThread:
    return BlueprintThread.objects.get(id=thread.id)


def _make_user(name: str | None = None):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(
        username=name or f"u-{uuid.uuid4().hex[:6]}", password="x"
    )


def _make_session(artifact: Artifact, user, *, process_type: str = "technical_blueprint"):
    version = artifact.current_version
    return ConvergenceSession.objects.create(
        process_type=process_type,
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="ai_review",
        status=ConvergenceSessionStatus.WAITING_CLARIFICATION,
        current_artifact_version=version,
        created_by=user,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1-2. 到期触发 + 同周期不重复（周期语义）
# ═══════════════════════════════════════════════════════════════════════════


def test_overdue_thread_is_reminded_and_anchor_is_written_back() -> None:
    artifact = _make_artifact()
    thread = _open_thread(artifact)
    _age(thread, 25)
    before_updated = _fresh(thread).updated_at

    counts = _remind(hours=24)

    assert counts == {"scanned": 1, "due": 1, "reminded": 1, "skipped": 0}
    fresh = _fresh(thread)
    assert fresh.last_reminded_at is not None
    # bulk_update 绕过 auto_now：漏显式带 updated_at 这条即红
    assert fresh.updated_at > before_updated


def test_second_run_in_the_same_period_never_re_reminds(monkeypatch) -> None:
    """⭐ 防轰炸：同周期内锚点逐字不变；推进一个周期后又能提醒（证明断言非恒真）。"""
    artifact = _make_artifact()
    thread = _open_thread(artifact)
    _age(thread, 25)

    assert _remind(hours=24)["reminded"] == 1
    anchor = _fresh(thread).last_reminded_at

    again = _remind(hours=24)
    assert again == {"scanned": 1, "due": 0, "reminded": 0, "skipped": 1}
    assert _fresh(thread).last_reminded_at == anchor

    later = _remind(hours=24, now=timezone.now() + timedelta(hours=25))
    assert later["reminded"] == 1
    assert _fresh(thread).last_reminded_at > anchor


# ═══════════════════════════════════════════════════════════════════════════
# 3. ⭐ 判据状态口径（B4 定夺：needs_clarification，不是 pending_review）
# ═══════════════════════════════════════════════════════════════════════════


def test_scan_targets_needs_clarification_not_pending_review() -> None:
    artifact = _make_artifact()
    thread = _open_thread(artifact)
    _age(thread, 25)

    Artifact.objects.filter(id=artifact.id).update(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    assert _remind(hours=24) == {"scanned": 0, "due": 0, "reminded": 0, "skipped": 0}

    Artifact.objects.filter(id=artifact.id).update(
        blueprint_status=BlueprintStatus.NEEDS_CLARIFICATION
    )
    assert _remind(hours=24)["reminded"] == 1


@pytest.mark.parametrize(
    ("mutate", "label"),
    [
        (
            lambda t: BlueprintThread.objects.filter(id=t.id).update(status=ThreadStatus.ANSWERED),
            "answered",
        ),
        (lambda t: BlueprintThread.objects.filter(id=t.id).update(blocking=False), "non-blocking"),
    ],
)
def test_answered_or_non_blocking_threads_are_out_of_scope(mutate, label: str) -> None:
    artifact = _make_artifact()
    thread = _open_thread(artifact)
    _age(thread, 25)
    mutate(thread)

    assert _remind(hours=24) == {"scanned": 0, "due": 0, "reminded": 0, "skipped": 0}, label


def test_not_yet_due_thread_is_skipped_not_reminded() -> None:
    artifact = _make_artifact()
    thread = _open_thread(artifact)
    _age(thread, 2)

    counts = _remind(hours=24)

    assert counts == {"scanned": 1, "due": 0, "reminded": 0, "skipped": 1}
    assert _fresh(thread).last_reminded_at is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. 提醒对象名单（reviewer ∪ 发起人；反查会话带 process_type 过滤）
# ═══════════════════════════════════════════════════════════════════════════


def test_recipients_are_reviewers_union_initiator_deduped(monkeypatch) -> None:
    from delivery.services import ArtifactService
    from tests.helpers.blueprint_samples import make_blueprint

    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", make_blueprint(), created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(
        blueprint_status=BlueprintStatus.NEEDS_CLARIFICATION
    )
    artifact.refresh_from_db()

    r1, r2, initiator = _make_user("rev1"), _make_user("rev2"), _make_user("starter")
    BlueprintReviewer.objects.create(artifact=artifact, user=r1, first_action="review_approve")
    BlueprintReviewer.objects.create(artifact=artifact, user=r2, first_action="block_edit")
    _make_session(artifact, initiator)
    # 旧 process 的会话不得混进名单（process_type 过滤）
    _make_session(artifact, _make_user("legacy"), process_type="technical_plan")

    thread = _open_thread(artifact)
    _age(thread, 25)

    from delivery.services.blueprint_review_action import _list_recipients

    recipients = async_to_sync(_list_recipients)(artifact.id)

    # reviewer 名单 ∪ 蓝图会话发起人，去重；旧 technical_plan 会话的发起人**不在**其中
    assert set(recipients) == {str(r1.id), str(r2.id), str(initiator.id)}
    assert len(recipients) == 3
    assert _remind(hours=24)["reminded"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# 5. ⭐ 不作答、不改状态、不判失败
# ═══════════════════════════════════════════════════════════════════════════


def test_reminder_never_answers_transitions_or_fails_anything() -> None:
    user = _make_user()
    from delivery.services import ArtifactService
    from tests.helpers.blueprint_samples import make_blueprint

    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", make_blueprint(), created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(
        blueprint_status=BlueprintStatus.NEEDS_CLARIFICATION
    )
    artifact.refresh_from_db()
    session = _make_session(artifact, user)
    thread = _open_thread(artifact)
    _age(thread, 25)
    messages_before = BlueprintThreadMessage.objects.filter(thread=thread).count()

    assert _remind(hours=24)["reminded"] == 1

    fresh = _fresh(thread)
    assert fresh.status == ThreadStatus.OPEN
    assert BlueprintThreadMessage.objects.filter(thread=thread).count() == messages_before
    assert (
        Artifact.objects.get(id=artifact.id).blueprint_status == BlueprintStatus.NEEDS_CLARIFICATION
    )
    assert ConvergenceSession.objects.get(id=session.id).status != ConvergenceSessionStatus.FAILED


def test_reminder_task_source_has_no_write_paths() -> None:
    """源码扫描：调度壳里不得出现作答 / 线程收尾 / 状态转移三类写。"""
    src = (SERVER_DIR / _TASKS_REL).read_text(encoding="utf-8")
    for token in ("record_answer", "resolve_thread", ".transition("):
        assert token not in src, f"提醒任务体出现写路径：{token}"


def test_reminder_falls_back_to_default_hours_when_config_is_broken(monkeypatch) -> None:
    """配置坏了回落常量，绝不让提醒彻底停摆（照 _aload_merge_config 的写法）。"""
    monkeypatch.setattr(
        "system.settings_service.aget_json_setting",
        AsyncMock(side_effect=RuntimeError("配置表炸了")),
    )
    artifact = _make_artifact()
    thread = _open_thread(artifact)
    _age(thread, 25)

    # 不传 hours ⇒ 走配置读取路径；配置抛异常 ⇒ 回落 24h ⇒ 25h 前的线程仍到期
    assert _remind()["reminded"] == 1
    assert _fresh(thread).last_reminded_at is not None


# ═══════════════════════════════════════════════════════════════════════════
# 6. 挂载点（源码扫描 + 直调 wrapper；⚠️ 绝不启动真 scheduler）
# ═══════════════════════════════════════════════════════════════════════════


def test_scheduler_is_disabled_in_tests() -> None:
    from django.conf import settings

    assert settings.FF_ENABLE_SCHEDULER is False


def test_reminder_job_is_registered_on_the_existing_scheduler() -> None:
    src = (SERVER_DIR / _SCHEDULER_REL).read_text(encoding="utf-8")
    assert "def remind_blueprint_clarifications_job" in src
    assert 'id="remind_blueprint_clarifications"' in src
    assert "IntervalTrigger(hours=1)" in src
    assert 'job="remind_blueprint_clarifications"' in src


def test_reminder_job_wrapper_calls_the_task_body(monkeypatch) -> None:
    from agents.management.commands import runapscheduler

    called: list[int] = []

    async def _fake() -> dict:
        called.append(1)
        return {"scanned": 0, "due": 0, "reminded": 0, "skipped": 0}

    monkeypatch.setattr("tasks.blueprint_reminder_tasks.aremind_blueprint_clarifications", _fake)
    runapscheduler.remind_blueprint_clarifications_job()

    assert called == [1]


def test_reminder_job_wrapper_swallows_task_failures(monkeypatch) -> None:
    """wrapper 吞掉任务体异常——异常外抛会打断 scheduler 主循环。"""
    from agents.management.commands import runapscheduler

    async def _boom() -> dict:
        raise RuntimeError("任务体炸了")

    monkeypatch.setattr("tasks.blueprint_reminder_tasks.aremind_blueprint_clarifications", _boom)

    runapscheduler.remind_blueprint_clarifications_job()  # 不抛即通过


def test_task_shell_never_raises_even_when_service_explodes(monkeypatch) -> None:
    from tasks.blueprint_reminder_tasks import aremind_blueprint_clarifications

    monkeypatch.setattr(
        "delivery.services.blueprint_review_action.aremind_clarification_threads",
        AsyncMock(side_effect=RuntimeError("service 炸了")),
    )

    assert async_to_sync(aremind_blueprint_clarifications)() == {
        "scanned": 0,
        "due": 0,
        "reminded": 0,
        "skipped": 0,
    }

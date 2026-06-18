"""RecoveryScheduler 路由 / 重试上限 / 排除集合测试。"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from resumable import recovery
from resumable.models import ResumableTask, ResumableTaskKind, ResumableTaskStatus

pytestmark = pytest.mark.django_db


def _running(target_id: str, *, attempt: int = 0, expired: bool = True, max_attempts: int = 3):
    lease = (
        timezone.now() - datetime.timedelta(seconds=30)
        if expired
        else timezone.now() + datetime.timedelta(seconds=60)
    )
    return ResumableTask.objects.create(
        kind=ResumableTaskKind.INDEX,
        target_id=target_id,
        status=ResumableTaskStatus.RUNNING,
        payload={"repository_id": target_id},
        lease_owner="dead",
        lease_expires_at=lease,
        attempt=attempt,
        max_attempts=max_attempts,
    )


def test_run_recovery_routes_expired_to_handler(monkeypatch) -> None:
    calls: list[str] = []

    def fake_handler(task: ResumableTask) -> None:
        calls.append(task.target_id)

    monkeypatch.setitem(recovery.RESUME_HANDLERS, ResumableTaskKind.INDEX, fake_handler)

    _running("repo-1")
    _running("repo-2", expired=False)  # 活租约 → 不恢复

    summary = recovery.run_recovery()

    assert calls == ["repo-1"]
    assert summary["recovered"] == 1
    # repo-1 被领取后 attempt+1。
    t = ResumableTask.objects.get(target_id="repo-1")
    assert t.attempt == 1


def test_run_recovery_marks_exhausted_failed(monkeypatch) -> None:
    monkeypatch.setitem(
        recovery.RESUME_HANDLERS, ResumableTaskKind.INDEX, lambda task: None
    )
    _running("repo-exhausted", attempt=3, max_attempts=3)

    summary = recovery.run_recovery()

    assert summary["exhausted"] == 1
    t = ResumableTask.objects.get(target_id="repo-exhausted")
    assert t.status == ResumableTaskStatus.FAILED
    assert "最大重试次数" in t.last_error


def test_run_recovery_skips_unknown_kind(monkeypatch) -> None:
    # 清空 handler 注册 → 无 handler 的 kind 跳过，不动状态。
    monkeypatch.setattr(recovery, "RESUME_HANDLERS", {})
    _running("repo-skip")

    summary = recovery.run_recovery()

    assert summary["skipped"] == 1
    t = ResumableTask.objects.get(target_id="repo-skip")
    assert t.status == ResumableTaskStatus.RUNNING  # 未被改动


def test_recoverable_target_ids_filters_attempt() -> None:
    _running("repo-ok", attempt=1, max_attempts=3)
    _running("repo-maxed", attempt=3, max_attempts=3)
    ResumableTask.objects.create(
        kind=ResumableTaskKind.INDEX,
        target_id="repo-completed",
        status=ResumableTaskStatus.COMPLETED,
        attempt=0,
        max_attempts=3,
    )

    ids = recovery.recoverable_target_ids(ResumableTaskKind.INDEX)
    assert "repo-ok" in ids
    assert "repo-maxed" not in ids
    assert "repo-completed" not in ids


def test_default_handlers_registered() -> None:
    from resumable.handlers import register_default_handlers

    register_default_handlers()
    assert ResumableTaskKind.INDEX in recovery.RESUME_HANDLERS
    assert ResumableTaskKind.GRAPH in recovery.RESUME_HANDLERS

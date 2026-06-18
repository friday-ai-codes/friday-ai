"""ResumableTask 租约 / 心跳 / 终态 / CAS 领取单元测试。"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from resumable import service
from resumable.models import ResumableTask, ResumableTaskKind, ResumableTaskStatus

pytestmark = pytest.mark.django_db


def _expired_task(**overrides) -> ResumableTask:
    defaults = dict(
        kind=ResumableTaskKind.INDEX,
        target_id="repo-1",
        status=ResumableTaskStatus.RUNNING,
        payload={"repository_id": "repo-1"},
        lease_owner="dead-instance",
        lease_expires_at=timezone.now() - datetime.timedelta(seconds=30),
        attempt=0,
        max_attempts=3,
    )
    defaults.update(overrides)
    return ResumableTask.objects.create(**defaults)


def test_register_running_creates_row_with_lease() -> None:
    task = service.register_running(
        kind=ResumableTaskKind.GRAPH,
        target_id="repo-x",
        payload={"a": 1},
        name="graph-build-repo-x",
    )
    assert task.status == ResumableTaskStatus.RUNNING
    assert task.lease_owner == service.INSTANCE_ID
    assert task.lease_expires_at is not None
    assert task.attempt == 1


def test_register_running_idempotent_update_or_create() -> None:
    service.register_running(
        kind=ResumableTaskKind.INDEX, target_id="repo-y", payload={}, name="n1"
    )
    again = service.register_running(
        kind=ResumableTaskKind.INDEX, target_id="repo-y", payload={"k": "v"}, name="n2"
    )
    # 同 (kind, target_id) 复用单行（唯一约束），不再新增 attempt（bump_attempt 默认 False）。
    assert ResumableTask.objects.filter(kind=ResumableTaskKind.INDEX, target_id="repo-y").count() == 1
    assert again.payload == {"k": "v"}
    assert again.attempt == 1


def test_claim_expired_is_exactly_once() -> None:
    task = _expired_task()
    first = service.claim_expired(str(task.id))
    second = service.claim_expired(str(task.id))
    assert first is True
    assert second is False  # 第一次已续租到未来，第二次 CAS 不命中

    task.refresh_from_db()
    assert task.lease_owner == service.INSTANCE_ID
    assert task.attempt == 1
    assert task.lease_expires_at > timezone.now()


def test_claim_expired_skips_live_lease() -> None:
    # 租约未过期（他人正在跑）→ 不可被领取。
    task = _expired_task(
        lease_expires_at=timezone.now() + datetime.timedelta(seconds=60),
    )
    assert service.claim_expired(str(task.id)) is False


def test_heartbeat_only_for_owner() -> None:
    task = service.register_running(
        kind=ResumableTaskKind.INDEX, target_id="repo-hb", payload={}, name="n"
    )
    assert service.heartbeat(kind=ResumableTaskKind.INDEX, target_id="repo-hb") is True

    # 改为他人持有 → 本实例心跳失效。
    ResumableTask.objects.filter(id=task.id).update(lease_owner="someone-else")
    assert service.heartbeat(kind=ResumableTaskKind.INDEX, target_id="repo-hb") is False


def test_terminal_transitions_release_lease() -> None:
    service.register_running(
        kind=ResumableTaskKind.INDEX, target_id="repo-done", payload={}, name="n"
    )
    service.mark_completed(kind=ResumableTaskKind.INDEX, target_id="repo-done")
    t = ResumableTask.objects.get(kind=ResumableTaskKind.INDEX, target_id="repo-done")
    assert t.status == ResumableTaskStatus.COMPLETED
    assert t.lease_owner == ""
    assert t.lease_expires_at is None

    service.register_running(
        kind=ResumableTaskKind.GRAPH, target_id="repo-fail", payload={}, name="n"
    )
    service.mark_failed(
        kind=ResumableTaskKind.GRAPH, target_id="repo-fail", error="boom"
    )
    f = ResumableTask.objects.get(kind=ResumableTaskKind.GRAPH, target_id="repo-fail")
    assert f.status == ResumableTaskStatus.FAILED
    assert f.last_error == "boom"


def test_sweep_expired_returns_only_expired_running() -> None:
    _expired_task(target_id="repo-a")
    _expired_task(
        target_id="repo-b",
        lease_expires_at=timezone.now() + datetime.timedelta(seconds=60),
    )
    _expired_task(target_id="repo-c", status=ResumableTaskStatus.COMPLETED)

    targets = {t.target_id for t in service.sweep_expired()}
    assert "repo-a" in targets
    assert "repo-b" not in targets
    assert "repo-c" not in targets

"""一次性迁移命令 migrate_resumable_to_durable 守护（MIGRATE-02 / SC2）。

锁定四类 Pitfall：

- migrates（postgres_queue）：seed PENDING index + RUNNING graph 行 → 跑命令 → 旧行标
  MIGRATED + legacy_durable_job_id 非空 + 按 deterministic key 的 durable job 在途。
- idempotent（postgres_queue）：连续跑两次 → 第二次 migrated=0（已 MIGRATED 行不再进扫描集）、
  不产生重复 durable job（deterministic key 命中既有）。
- sqlite_safe（默认 SQLite）：非 durable 后端跑命令 → 不抛、打印非 durable 提示、**不静默**
  把行标 MIGRATED（skipped 统计）。
- no_double_run（默认 SQLite）：行标 MIGRATED 后 recoverable_target_ids 天然排除该 target_id，
  recovery/reconcile 不再驱动（不与 durable 双跑）。

postgres 专项用例带 postgres_queue + enable_socket（需真实 durable 才能断言 defer + key 去重），
默认 SQLite 套件经 addopts 排除；sqlite_safe / no_double_run 走默认 SQLite 路径。
"""

from __future__ import annotations

from io import StringIO

import pytest
from asgiref.sync import async_to_sync
from django.core.management import call_command

from resumable.models import ResumableTask, ResumableTaskKind, ResumableTaskStatus


# ---------------------------------------------------------------------------
# migrates / idempotent：真实 durable（postgres_queue）
# ---------------------------------------------------------------------------


@pytest.mark.postgres_queue
@pytest.mark.enable_socket
@pytest.mark.django_db(transaction=True)
def test_migrates_inflight_rows_to_durable(procrastinate_app, settings) -> None:
    """seed 在途 index/graph 行 → 命令 defer durable job、旧行标 MIGRATED 记 legacy id。"""
    settings.DURABLE_TASK_BACKEND = "procrastinate"
    from durable.service import DurableTaskService

    idx = ResumableTask.objects.create(
        kind=ResumableTaskKind.INDEX,
        target_id="repo-mig-1",
        status=ResumableTaskStatus.PENDING,
        # 含额外键（name），验证命令按白名单重建 payload、不透传原始 payload。
        payload={"repository_id": "repo-mig-1", "branch": "main", "name": "bg-x"},
    )
    grp = ResumableTask.objects.create(
        kind=ResumableTaskKind.GRAPH,
        target_id="repo-mig-2",
        status=ResumableTaskStatus.RUNNING,
        payload={"repository_id": "repo-mig-2"},
    )

    call_command("migrate_resumable_to_durable")

    idx.refresh_from_db()
    grp.refresh_from_db()
    assert idx.status == ResumableTaskStatus.MIGRATED
    assert idx.legacy_durable_job_id
    assert grp.status == ResumableTaskStatus.MIGRATED
    assert grp.legacy_durable_job_id

    # deterministic key 对应的 durable job 在途。
    assert async_to_sync(DurableTaskService.has_active_by_key)("index:repo-mig-1") is True
    assert async_to_sync(DurableTaskService.has_active_by_key)("graph:repo-mig-2") is True


@pytest.mark.postgres_queue
@pytest.mark.enable_socket
@pytest.mark.django_db(transaction=True)
def test_idempotent_rerun_no_duplicate(procrastinate_app, settings) -> None:
    """连续两次跑命令：第二次 migrated=0（MIGRATED 行被状态过滤排除），无重复 durable job。"""
    settings.DURABLE_TASK_BACKEND = "procrastinate"

    idx = ResumableTask.objects.create(
        kind=ResumableTaskKind.INDEX,
        target_id="repo-idem",
        status=ResumableTaskStatus.PENDING,
        payload={"repository_id": "repo-idem"},
    )

    out1 = StringIO()
    call_command("migrate_resumable_to_durable", stdout=out1)
    assert "migrated=1" in out1.getvalue()
    idx.refresh_from_db()
    legacy_first = idx.legacy_durable_job_id
    assert idx.status == ResumableTaskStatus.MIGRATED
    assert legacy_first

    out2 = StringIO()
    call_command("migrate_resumable_to_durable", stdout=out2)
    # 第二次：已 MIGRATED 行不再进扫描集（状态过滤）→ scanned=0 migrated=0。
    assert "scanned=0" in out2.getvalue()
    assert "migrated=0" in out2.getvalue()
    idx.refresh_from_db()
    # legacy id 未被二次覆盖（无重复处理）。
    assert idx.legacy_durable_job_id == legacy_first


# ---------------------------------------------------------------------------
# sqlite_safe：非 durable 后端安全降级（默认 SQLite）
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sqlite_safe_degraded_no_silent_migrate() -> None:
    """SQLite/非 durable 路径：不抛、打印非 durable 提示、不静默把行标 MIGRATED。"""
    task = ResumableTask.objects.create(
        kind=ResumableTaskKind.INDEX,
        target_id="repo-sqlite",
        status=ResumableTaskStatus.PENDING,
        payload={"repository_id": "repo-sqlite"},
    )

    out = StringIO()
    # 不抛异常即过半（命令对非 durable 后端安全降级）。
    call_command("migrate_resumable_to_durable", stdout=out)
    output = out.getvalue()

    assert "非 durable 后端" in output
    assert "backend=in-process" in output
    # 关键：未静默"迁移"——旧行仍为 PENDING，未被标 MIGRATED。
    task.refresh_from_db()
    assert task.status == ResumableTaskStatus.PENDING
    assert task.legacy_durable_job_id == ""


# ---------------------------------------------------------------------------
# no_double_run：MIGRATED 行被 recoverable_target_ids 天然排除（不双跑）
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_no_double_run_migrated_excluded_from_recovery() -> None:
    """迁移标 MIGRATED 后 recoverable_target_ids(INDEX) 不含该 target_id（recovery 不再驱动）。"""
    from resumable.recovery import recoverable_target_ids

    # 已迁移行：标 MIGRATED → 应被恢复集排除。
    ResumableTask.objects.create(
        kind=ResumableTaskKind.INDEX,
        target_id="repo-migrated",
        status=ResumableTaskStatus.MIGRATED,
        legacy_durable_job_id="123",
    )
    # 对照：仍 RUNNING 的同 kind 行应仍可被恢复（确认排除是状态驱动而非全空）。
    ResumableTask.objects.create(
        kind=ResumableTaskKind.INDEX,
        target_id="repo-running",
        status=ResumableTaskStatus.RUNNING,
        attempt=0,
        max_attempts=3,
    )

    ids = recoverable_target_ids(ResumableTaskKind.INDEX)
    assert "repo-migrated" not in ids
    assert "repo-running" in ids

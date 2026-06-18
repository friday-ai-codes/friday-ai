"""启动时孤儿 RUNNING GraphBuildHistory 回收逻辑测试。

后台图谱构建任务（``run_in_background``）随进程内存存活，进程重启后 DB 里的
RUNNING 行不会被收尾，永久卡住「准备中」并触发 rebuild 的 ``graph already
running`` 互斥。``codegraph.apps.reconcile_orphaned_graph_builds`` 在服务进程
启动时把超时仍 RUNNING 的行回收为 FAILED 并归位仓库聚合态。
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from codegraph.apps import reconcile_orphaned_graph_builds
from repositories.models import (
    GraphBuildHistory,
    GraphBuildHistoryStatus,
    GraphBuildHistoryTrigger,
    IndexStatus,
    Repository,
    RepositoryGraphStatus,
)


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="orphan-reconcile-repo",
        git_url="https://github.com/test/orphan.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        graph_build_status=RepositoryGraphStatus.RUNNING,
    )


@pytest.mark.django_db
def test_orphan_running_row_older_than_timeout_marked_failed(repo: Repository) -> None:
    """超过阈值仍 RUNNING 的行 → FAILED + finished_at + error_message，仓库归位 FAILED。"""
    stale = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.AUTO_AFTER_INDEX,
        status=GraphBuildHistoryStatus.RUNNING,
        started_at=timezone.now() - timezone.timedelta(minutes=120),
    )

    reconciled = reconcile_orphaned_graph_builds(timeout_minutes=30)

    assert reconciled == 1
    stale.refresh_from_db()
    assert stale.status == GraphBuildHistoryStatus.FAILED
    assert stale.finished_at is not None
    assert stale.error_message

    repo.refresh_from_db()
    assert repo.graph_build_status == RepositoryGraphStatus.FAILED
    assert repo.graph_stage == ""
    assert repo.current_graph_file == ""


@pytest.mark.django_db
def test_recent_running_row_within_timeout_left_untouched(repo: Repository) -> None:
    """未超阈值的 RUNNING 行不回收（给多 worker 部署留安全边界）。"""
    fresh = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.RUNNING,
        started_at=timezone.now() - timezone.timedelta(minutes=2),
    )

    reconciled = reconcile_orphaned_graph_builds(timeout_minutes=30)

    assert reconciled == 0
    fresh.refresh_from_db()
    assert fresh.status == GraphBuildHistoryStatus.RUNNING
    repo.refresh_from_db()
    assert repo.graph_build_status == RepositoryGraphStatus.RUNNING


@pytest.mark.django_db
def test_terminal_rows_not_touched(repo: Repository) -> None:
    """已是终态的行（COMPLETED/CANCELLED/FAILED）不受影响。"""
    completed = GraphBuildHistory.objects.create(
        repository=repo,
        trigger_type=GraphBuildHistoryTrigger.MANUAL,
        status=GraphBuildHistoryStatus.COMPLETED,
        started_at=timezone.now() - timezone.timedelta(minutes=120),
        finished_at=timezone.now() - timezone.timedelta(minutes=119),
    )

    reconciled = reconcile_orphaned_graph_builds(timeout_minutes=30)

    assert reconciled == 0
    completed.refresh_from_db()
    assert completed.status == GraphBuildHistoryStatus.COMPLETED

"""服务启动时孤儿状态兜底：

- Repository.index_status == INDEXING 在重启后必为 FAILED（已有逻辑）
- IndexHistory.status == RUNNING 在重启后必为 FAILED + finished_at 写入
  （新增：避免"索引历史"列表里看到永远在 RUNNING 的僵尸记录）
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from repositories.apps import RepositoriesConfig
from repositories.models import (
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    Repository,
    TriggerType,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_reset_stuck_indexing_also_marks_running_history_as_failed() -> None:
    repo = Repository.objects.create(
        name="stuck-repo",
        git_url="https://github.com/test/stuck.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXING,
    )
    history = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.RUNNING,
        started_at=timezone.now(),
    )

    RepositoriesConfig._reset_stuck_indexing()

    repo.refresh_from_db()
    history.refresh_from_db()

    assert repo.index_status == IndexStatus.FAILED
    assert history.status == IndexHistoryStatus.FAILED
    assert history.finished_at is not None
    assert history.error_message is not None
    assert "服务重启" in history.error_message


def test_reset_does_not_touch_completed_or_failed_history() -> None:
    repo = Repository.objects.create(
        name="finished-repo",
        git_url="https://github.com/test/finished.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )
    completed = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.COMPLETED,
        started_at=timezone.now(),
        finished_at=timezone.now(),
    )
    failed = IndexHistory.objects.create(
        repository=repo,
        trigger_type=TriggerType.MANUAL,
        status=IndexHistoryStatus.FAILED,
        started_at=timezone.now(),
        finished_at=timezone.now(),
        error_message="原始错误",
    )

    RepositoriesConfig._reset_stuck_indexing()

    completed.refresh_from_db()
    failed.refresh_from_db()
    assert completed.status == IndexHistoryStatus.COMPLETED
    assert failed.status == IndexHistoryStatus.FAILED
    assert failed.error_message == "原始错误"


def test_reset_with_no_stuck_records_is_noop() -> None:
    Repository.objects.create(
        name="clean-repo",
        git_url="https://github.com/test/clean.git",
        git_platform="github",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
    )
    RepositoriesConfig._reset_stuck_indexing()
    # 不抛异常即可

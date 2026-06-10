"""SyncStatusView 集成测试。

GET /api/repositories/{id}/sync-status/ 响应结构、最近历史记录上限、404 处理、
next_sync_at 数据源及 last_sync_result 映射的完整验证。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from repositories.models import IndexHistory, IndexHistoryStatus, Repository


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="sync_test_user",
        email="sync@example.com",
        password="syncpass123",
    )


@pytest.fixture
def auth_client(api_client, user) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="Sync Test Repo",
        git_url="https://github.com/test/sync-repo.git",
        git_platform="github",
        default_branch="main",
        last_indexed_commit_sha="abc123def456",
    )


def _sync_status_url(repository_id: uuid.UUID) -> str:
    return f"/api/repositories/{repository_id}/sync-status/"


# ============================================================================
# 测试用例
# ============================================================================


@pytest.mark.django_db
def test_sync_status_response_shape(auth_client: APIClient, repo: Repository) -> None:
    """存在的仓库 → 200，响应包含所有必要字段（work item）。"""
    with patch(
        "repositories.sync_status_views.sync_to_async",
        side_effect=lambda fn: lambda *a, **kw: None,
    ):
        response = auth_client.get(_sync_status_url(repo.id))

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["repository_id"] == str(repo.id)
    assert "last_synced_sha" in data
    assert "last_synced_at" in data
    assert "last_sync_result" in data
    assert "next_sync_at" in data
    assert data["interval_seconds"] == 7200
    assert isinstance(data["recent_history"], list)


@pytest.mark.django_db
def test_sync_status_recent_history_max_5(auth_client: APIClient, repo: Repository) -> None:
    """仓库有 10 条 IndexHistory，recent_history 最多返回 5 条（contract）。"""
    for i in range(10):
        IndexHistory.objects.create(
            repository=repo,
            trigger_type="scheduled",
            status=IndexHistoryStatus.COMPLETED,
        )

    with patch(
        "repositories.sync_status_views.sync_to_async",
        side_effect=lambda fn: lambda *a, **kw: None,
    ):
        response = auth_client.get(_sync_status_url(repo.id))

    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()["recent_history"]) <= 5


@pytest.mark.django_db
def test_sync_status_404_for_missing_repo(auth_client: APIClient) -> None:
    """不存在的 repo_id → 404 + {"detail": "仓库不存在"}（work item）。"""
    fake_id = uuid.uuid4()
    response = auth_client.get(_sync_status_url(fake_id))
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"] == "仓库不存在"


@pytest.mark.django_db
def test_sync_status_next_sync_at_from_djangojob(
    auth_client: APIClient, repo: Repository
) -> None:
    """DjangoJob.objects.get 返回 next_run_time，响应的 next_sync_at 与其一致（contract）。"""
    mock_next_run = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)

    mock_job = MagicMock()
    mock_job.next_run_time = mock_next_run

    with patch("django_apscheduler.models.DjangoJob.objects") as mock_objects:
        mock_objects.get.return_value = mock_job
        response = auth_client.get(_sync_status_url(repo.id))

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    # next_sync_at 应为 ISO 格式时间字符串（与 mock_next_run 对应）
    assert data["next_sync_at"] is not None
    assert "2026-05-12" in data["next_sync_at"]


@pytest.mark.django_db
def test_sync_status_last_sync_result_mapping(
    auth_client: APIClient, repo: Repository
) -> None:
    """last_sync_result 映射：COMPLETED → success；FAILED → failed；无历史 → never（contract）。"""
    # 无历史记录时应返回 "never"
    with patch(
        "repositories.sync_status_views.sync_to_async",
        side_effect=lambda fn: lambda *a, **kw: None,
    ):
        response = auth_client.get(_sync_status_url(repo.id))
    assert response.json()["last_sync_result"] == "never"

    # 创建 COMPLETED 记录
    IndexHistory.objects.create(
        repository=repo,
        trigger_type="scheduled",
        status=IndexHistoryStatus.COMPLETED,
    )
    with patch(
        "repositories.sync_status_views.sync_to_async",
        side_effect=lambda fn: lambda *a, **kw: None,
    ):
        response = auth_client.get(_sync_status_url(repo.id))
    assert response.json()["last_sync_result"] == "success"

    # 再创建 FAILED 记录（更新时间更晚）
    IndexHistory.objects.create(
        repository=repo,
        trigger_type="scheduled",
        status=IndexHistoryStatus.FAILED,
    )
    with patch(
        "repositories.sync_status_views.sync_to_async",
        side_effect=lambda fn: lambda *a, **kw: None,
    ):
        response = auth_client.get(_sync_status_url(repo.id))
    assert response.json()["last_sync_result"] == "failed"

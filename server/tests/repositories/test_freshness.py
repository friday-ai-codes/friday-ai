"""contract：compute_freshness_status 三态单测 + refresh-remote-head 集成测试。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from repositories.models import Repository


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
        username="freshness_test_user",
        email="freshness@example.com",
        password="freshnesspass123",
    )


@pytest.fixture
def auth_client(api_client, user) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(
        name="测试仓库",
        git_url="https://github.com/example/repo.git",
        last_indexed_commit_sha="abc123",
        remote_head_sha="abc123",
        remote_head_checked_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
    )


# ============================================================================
# compute_freshness_status 三态单测
# ============================================================================


@pytest.mark.django_db
def test_freshness_fresh(repo):
    """local SHA == remote SHA → fresh。"""
    from repositories.freshness_service import compute_freshness_status

    repo.last_indexed_commit_sha = "abc123"
    repo.remote_head_sha = "abc123"
    repo.remote_head_checked_at = datetime(2026, 5, 11, tzinfo=timezone.utc)

    assert compute_freshness_status(repo) == "fresh"


@pytest.mark.django_db
def test_freshness_stale(repo):
    """local SHA != remote SHA（两者都有值）→ stale。"""
    from repositories.freshness_service import compute_freshness_status

    repo.last_indexed_commit_sha = "abc123"
    repo.remote_head_sha = "def456"
    repo.remote_head_checked_at = datetime(2026, 5, 11, tzinfo=timezone.utc)

    assert compute_freshness_status(repo) == "stale"


@pytest.mark.django_db
def test_freshness_unknown_no_remote(repo):
    """remote_head_sha 为空 → unknown。"""
    from repositories.freshness_service import compute_freshness_status

    repo.last_indexed_commit_sha = "abc123"
    repo.remote_head_sha = ""
    repo.remote_head_checked_at = datetime(2026, 5, 11, tzinfo=timezone.utc)

    assert compute_freshness_status(repo) == "unknown"


@pytest.mark.django_db
def test_freshness_unknown_no_checked_at(repo):
    """remote_head_sha 有值但 remote_head_checked_at = None → unknown。"""
    from repositories.freshness_service import compute_freshness_status

    repo.last_indexed_commit_sha = "abc123"
    repo.remote_head_sha = "abc123"
    repo.remote_head_checked_at = None

    assert compute_freshness_status(repo) == "unknown"


@pytest.mark.django_db
def test_freshness_unknown_no_local(repo):
    """remote_head_sha 有值但 last_indexed_commit_sha 为空 → unknown。"""
    from repositories.freshness_service import compute_freshness_status

    repo.last_indexed_commit_sha = ""
    repo.remote_head_sha = "abc123"
    repo.remote_head_checked_at = datetime(2026, 5, 11, tzinfo=timezone.utc)

    assert compute_freshness_status(repo) == "unknown"


# ============================================================================
# refresh-remote-head 端点集成测试
# ============================================================================


@pytest.mark.django_db
def test_refresh_remote_head_updates_sha(auth_client, repo):
    """POST refresh-remote-head → 更新 DB + 返回 freshness 字段。"""
    new_sha = "newsha789"

    with patch(
        "repositories.refresh_remote_head_views._get_remote_head_sha",
        new=AsyncMock(return_value=new_sha),
    ):
        url = f"/api/repositories/{repo.id}/refresh-remote-head/"
        response = auth_client.post(url)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["remote_head_sha"] == new_sha
    assert "freshness" in data

    repo.refresh_from_db()
    assert repo.remote_head_sha == new_sha
    assert repo.remote_head_checked_at is not None


@pytest.mark.django_db
def test_refresh_remote_head_404(auth_client):
    """不存在的仓库 → 404。"""
    url = f"/api/repositories/{uuid.uuid4()}/refresh-remote-head/"
    response = auth_client.post(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_refresh_remote_head_unauthenticated(api_client, repo):
    """未登录 → 403。"""
    url = f"/api/repositories/{repo.id}/refresh-remote-head/"
    response = api_client.post(url)
    assert response.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )

"""批量建仓（BATCH-02）+ 超管全部更新索引（BATCH-01）守护。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from projects.models import Space
from repositories.models import IndexStatus, Repository

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


async def _auth_headers(user: User) -> dict[str, str]:
    refresh = await sync_to_async(RefreshToken.for_user)(user)
    return {"authorization": f"Bearer {refresh.access_token}"}


@pytest.fixture
def superuser(db) -> User:
    return User.objects.create_superuser(
        username="su", email="su@example.com", password="x"
    )


@pytest.fixture
def normal_user(db) -> User:
    return User.objects.create_user(
        username="nu", email="nu@example.com", password="x"
    )


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="space-1")


# ---------------------------------------------------------------------------
# 全部更新索引（BATCH-01）
# ---------------------------------------------------------------------------


async def test_reindex_all_forbidden_for_normal_user(normal_user: User) -> None:
    """普通用户不可调用 reindex-all（IsSuperUser fail-closed）。"""
    client = AsyncClient()
    resp = await client.post(
        "/api/repositories/reindex-all/", headers=await _auth_headers(normal_user)
    )
    assert resp.status_code == 403


async def test_reindex_all_queues_non_deleted_repos(superuser: User) -> None:
    """超管触发把全部未删除仓库入队，跳过已索引中的，返回 queued/skipped/total。"""
    r1 = await Repository.objects.acreate(
        name="r1", git_url="https://github.com/t/r1.git", git_platform="github",
        index_status=IndexStatus.NOT_INDEXED,
    )
    await Repository.objects.acreate(
        name="r2", git_url="https://github.com/t/r2.git", git_platform="github",
        index_status=IndexStatus.INDEXED,
    )
    # 已在索引中 → 跳过
    await Repository.objects.acreate(
        name="r3", git_url="https://github.com/t/r3.git", git_platform="github",
        index_status=IndexStatus.INDEXING,
    )
    # 软删除 → 不计入
    await Repository.objects.acreate(
        name="r4", git_url="https://github.com/t/r4.git", git_platform="github",
        is_deleted=True,
    )

    captured: list = []

    def _fake_schedule(repo_id, history_id, *, branch=None, trigger="manual"):
        captured.append(repo_id)
        return f"index:{repo_id}"

    with patch("repositories.index_views._schedule_index", side_effect=_fake_schedule):
        client = AsyncClient()
        resp = await client.post(
            "/api/repositories/reindex-all/", headers=await _auth_headers(superuser)
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3  # r1/r2/r3（r4 软删排除）
    assert data["queued"] == 2  # r1 + r2
    assert data["skipped"] == 1  # r3 已索引中
    assert len(captured) == 2

    await r1.arefresh_from_db()
    assert r1.index_status == IndexStatus.INDEXING


# ---------------------------------------------------------------------------
# 批量建仓（BATCH-02）
# ---------------------------------------------------------------------------


async def test_batch_create_creates_multiple_repos(normal_user: User, space: Space) -> None:
    """批量建仓逐项创建，返回 created/failed 计数。"""
    payload = {
        "repositories": [
            {
                "name": "batch-a",
                "git_url": "https://github.com/t/a.git",
                "git_platform": "github",
                "access_token": "tok-a",
                "space_ids": [str(space.id)],
            },
            {
                "name": "batch-b",
                "git_url": "https://github.com/t/b.git",
                "git_platform": "github",
                "access_token": "tok-b",
                "space_ids": [str(space.id)],
            },
        ]
    }
    with patch("repositories.summary_service.enqueue_repo_summary"):
        client = AsyncClient()
        resp = await client.post(
            "/api/repositories/batch/",
            data=payload,
            content_type="application/json",
            headers=await _auth_headers(normal_user),
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["created_count"] == 2
    assert data["failed_count"] == 0
    assert await Repository.objects.filter(name__startswith="batch-").acount() == 2


async def test_batch_create_isolates_per_item_failure(
    normal_user: User, space: Space
) -> None:
    """单项校验失败不影响其余（缺 git_url 的项落 failed，合法项仍 created）。"""
    payload = {
        "repositories": [
            {
                "name": "ok-repo",
                "git_url": "https://github.com/t/ok.git",
                "git_platform": "github",
                "access_token": "tok",
                "space_ids": [str(space.id)],
            },
            {"name": "bad-repo"},  # 缺必填字段
        ]
    }
    with patch("repositories.summary_service.enqueue_repo_summary"):
        client = AsyncClient()
        resp = await client.post(
            "/api/repositories/batch/",
            data=payload,
            content_type="application/json",
            headers=await _auth_headers(normal_user),
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["created_count"] == 1
    assert data["failed_count"] == 1
    assert data["failed"][0]["index"] == 1


async def test_batch_create_rejects_empty(normal_user: User) -> None:
    client = AsyncClient()
    resp = await client.post(
        "/api/repositories/batch/",
        data={"repositories": []},
        content_type="application/json",
        headers=await _auth_headers(normal_user),
    )
    assert resp.status_code == 400

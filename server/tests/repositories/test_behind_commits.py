"""：_calculate_commit_distance commit 数计算链路测试。"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from repositories.models import Repository
# ============================================================================
# Fixtures
# ============================================================================
@pytest.fixture
def repo(db) -> Repository:
 return Repository.objects.create(
 name="behind_commits 测试仓库",
 git_url="https://github.com/example/repo.git",
 last_indexed_commit_sha="abc123oldsha",
 remote_head_sha="def456newsha",
 remote_head_checked_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
 default_branch="main",
 )
# ============================================================================
# _calculate_commit_distance 单测
# ============================================================================
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_calculates_commit_distance(repo, tmp_path):
 """本地 clone 存在时，调用 git fetch + git rev-list --count 返回整数。"""
 from repositories.freshness_service import _calculate_commit_distance
 mock_fetch_proc = MagicMock
 mock_fetch_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_fetch_proc.returncode = 0
 mock_count_proc = MagicMock
 mock_count_proc.communicate = AsyncMock(return_value=(b"7\n", b""))
 call_args_list =
 async def fake_create_subprocess_exec(*args, **kwargs):
 call_args_list.append(list(args))
 if "fetch" in args:
 return mock_fetch_proc
 return mock_count_proc
 with (
 patch(
 "repositories.freshness_service.settings.REPO_CLONE_DIR",
 tmp_path,
 ),
 patch(
 "repositories.freshness_service.asyncio.create_subprocess_exec",
 side_effect=fake_create_subprocess_exec,
 ),
 ):
 clone_dir = tmp_path / str(repo.id)
 clone_dir.mkdir
 result = await _calculate_commit_distance(repo)
 assert result == 7
 assert any(
 "fetch" in args and "--depth=100" in args for args in call_args_list
 ), "应调用 git fetch --depth=100"
 assert any(
 "rev-list" in args and "--count" in args for args in call_args_list
 ), "应调用 git rev-list --count"
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_calculates_commit_distance_no_local_clone(repo, tmp_path):
 """本地 clone 不存在时返回 None。"""
 from repositories.freshness_service import _calculate_commit_distance
 with patch(
 "repositories.freshness_service.settings.REPO_CLONE_DIR",
 tmp_path,
 ):
 # tmp_path/{repo.id} 不创建，模拟不存在
 result = await _calculate_commit_distance(repo)
 assert result is None
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_calculates_commit_distance_same_sha(db, tmp_path):
 """local SHA == remote SHA → 直接返回 0，不调用 git。
 NOTE: 必须 transaction=True。否则 `sync_to_async(Repository.objects.create)`
 会把 ORM 写入派发到 asgiref 的 sync thread → 跨连接，无法被 pytest-django
 默认 transaction rollback 清理，导致这条 "相同 SHA 仓库" 行残留下来污染
 后续按字典序运行的 `test_repositories.py:test_list_repositories_*`
 （结果就是 list 应该返 0/1 条结果，但实际多了一条）。
 """
 from asgiref.sync import sync_to_async
 from repositories.freshness_service import _calculate_commit_distance
 repo = await sync_to_async(Repository.objects.create)(
 name="相同 SHA 仓库",
 git_url="https://github.com/example/same.git",
 last_indexed_commit_sha="samesha123",
 remote_head_sha="samesha123",
 remote_head_checked_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
 )
 with patch(
 "repositories.freshness_service.asyncio.create_subprocess_exec"
 ) as mock_exec:
 result = await _calculate_commit_distance(repo)
 assert result == 0
 mock_exec.assert_not_called

"""backfill_branch_metadata 命令与查询兼容层工具函数测试。"""
from __future__ import annotations
import uuid
from unittest.mock import MagicMock, patch
import pytest
from django.core.management import call_command
from repositories.models import (
 BranchIndexStatus,
 IndexStatus,
 Repository,
 RepositoryBranchIndex,
)
from services.branch_utils import get_effective_collection_name, is_branch_index_enabled
from services.qdrant_service import QdrantService
@pytest.mark.django_db
class TestBackfillCommand:
 """backfill_branch_metadata 管理命令测试。"""
 def _create_indexed_repo(self, name: str = "repo") -> Repository:
 return Repository.objects.create(
 name=name,
 git_url=f"https://example.com/{name}.git",
 index_status=IndexStatus.INDEXED,
 default_branch="main",
 )
 @patch.object(QdrantService, "get_client")
 @patch.object(QdrantService, "check_collection_health")
 def test_dry_run_no_changes(
 self, mock_health: MagicMock, mock_get_client: MagicMock
 ) -> None:
 """dry-run 模式不修改任何数据。"""
 repo = self._create_indexed_repo("dry-run-repo")
 mock_health.return_value = {"collection_exists": True, "points_count": 10}
 mock_client = MagicMock
 mock_get_client.return_value = mock_client
 point = MagicMock
 point.id = "p1"
 mock_client.scroll.return_value = ([point], None)
 call_command("backfill_branch_metadata", "--dry-run")
 assert RepositoryBranchIndex.objects.filter(repository=repo).count == 0
 mock_client.set_payload.assert_not_called
 mock_client.create_payload_index.assert_not_called
 @patch.object(QdrantService, "get_client")
 @patch.object(QdrantService, "check_collection_health")
 def test_backfill_creates_branch_index(
 self, mock_health: MagicMock, mock_get_client: MagicMock
 ) -> None:
 """正常模式创建 RepositoryBranchIndex 记录。"""
 repo = self._create_indexed_repo("bf-repo")
 mock_health.return_value = {"collection_exists": True, "points_count": 5}
 mock_client = MagicMock
 mock_get_client.return_value = mock_client
 point = MagicMock
 point.id = "p1"
 mock_client.scroll.return_value = ([point], None)
 call_command("backfill_branch_metadata")
 bi = RepositoryBranchIndex.objects.get(repository=repo)
 assert bi.is_base_branch is True
 assert bi.status == BranchIndexStatus.INDEXED
 assert bi.branch_name == "main"
 assert bi.collection_name == QdrantService.get_collection_name(str(repo.id))
 mock_client.set_payload.assert_called_once
 @patch.object(QdrantService, "get_client")
 @patch.object(QdrantService, "check_collection_health")
 def test_backfill_specific_repo(
 self, mock_health: MagicMock, mock_get_client: MagicMock
 ) -> None:
 """指定 --repo-id 时只处理该仓库。"""
 repo1 = self._create_indexed_repo("specific-1")
 repo2 = self._create_indexed_repo("specific-2")
 mock_health.return_value = {"collection_exists": True, "points_count": 3}
 mock_client = MagicMock
 mock_get_client.return_value = mock_client
 point = MagicMock
 point.id = "p1"
 mock_client.scroll.return_value = ([point], None)
 call_command("backfill_branch_metadata", "--repo-id", str(repo1.id))
 assert RepositoryBranchIndex.objects.filter(repository=repo1).count == 1
 assert RepositoryBranchIndex.objects.filter(repository=repo2).count == 0
 @patch.object(QdrantService, "get_client")
 @patch.object(QdrantService, "check_collection_health")
 def test_backfill_skips_already_migrated(
 self, mock_health: MagicMock, mock_get_client: MagicMock
 ) -> None:
 """预创建 RepositoryBranchIndex 记录的仓库应被跳过。"""
 repo = self._create_indexed_repo("migrated-repo")
 RepositoryBranchIndex.objects.create(
 repository=repo,
 branch_name="main",
 is_base_branch=True,
 status=BranchIndexStatus.INDEXED,
 )
 mock_client = MagicMock
 mock_get_client.return_value = mock_client
 call_command("backfill_branch_metadata")
 mock_health.assert_not_called
 mock_client.scroll.assert_not_called
 @patch.object(QdrantService, "get_client")
 @patch.object(QdrantService, "check_collection_health")
 def test_backfill_continues_on_single_failure(
 self, mock_health: MagicMock, mock_get_client: MagicMock
 ) -> None:
 """第一个仓库失败不影响第二个仓库处理。"""
 repo1 = self._create_indexed_repo("fail-repo")
 repo2 = self._create_indexed_repo("ok-repo")
 mock_client = MagicMock
 mock_get_client.return_value = mock_client
 call_count = 0
 def health_side_effect(repo_id: str) -> dict:
 nonlocal call_count
 call_count += 1
 if repo_id == str(repo1.id):
 raise RuntimeError("simulated failure")
 return {"collection_exists": True, "points_count": 2}
 mock_health.side_effect = health_side_effect
 point = MagicMock
 point.id = "p1"
 mock_client.scroll.return_value = ([point], None)
 call_command("backfill_branch_metadata")
 assert RepositoryBranchIndex.objects.filter(
 repository=repo2, is_base_branch=True
 ).exists
@pytest.mark.django_db
class TestQueryCompatLayer:
 """查询兼容层工具函数测试。"""
 def _create_repo(self, name: str = "compat-repo") -> Repository:
 return Repository.objects.create(
 name=name,
 git_url=f"https://example.com/{name}.git",
 default_branch="main",
 )
 def test_no_branch_index_returns_base_collection(self) -> None:
 """无 RepositoryBranchIndex 时返回旧的 code_index_{repo_id}。"""
 repo = self._create_repo("no-bi")
 result = get_effective_collection_name(str(repo.id))
 assert result == f"code_index_{repo.id}"
 def test_with_branch_index_returns_base_collection(self) -> None:
 """有 base 记录且 branch_name 匹配时返回 base collection。"""
 repo = self._create_repo("with-bi")
 RepositoryBranchIndex.objects.create(
 repository=repo,
 branch_name="main",
 is_base_branch=True,
 collection_name=f"code_index_{repo.id}",
 status=BranchIndexStatus.INDEXED,
 )
 result = get_effective_collection_name(str(repo.id), "main")
 assert result == f"code_index_{repo.id}"
 def test_overlay_branch_returns_overlay_collection(self) -> None:
 """有 overlay 记录时返回 overlay collection。"""
 repo = self._create_repo("overlay-bi")
 RepositoryBranchIndex.objects.create(
 repository=repo,
 branch_name="main",
 is_base_branch=True,
 collection_name=f"code_index_{repo.id}",
 status=BranchIndexStatus.INDEXED,
 )
 overlay_name = f"code_index_{repo.id}_br_feature_abc123"
 RepositoryBranchIndex.objects.create(
 repository=repo,
 branch_name="feature/test",
 is_base_branch=False,
 collection_name=overlay_name,
 status=BranchIndexStatus.INDEXED,
 )
 result = get_effective_collection_name(str(repo.id), "feature/test")
 assert result == overlay_name
 def test_overlay_not_exist_falls_back_to_base(self) -> None:
 """overlay 不存在时降级到 base collection。"""
 repo = self._create_repo("fallback-bi")
 RepositoryBranchIndex.objects.create(
 repository=repo,
 branch_name="main",
 is_base_branch=True,
 collection_name=f"code_index_{repo.id}",
 status=BranchIndexStatus.INDEXED,
 )
 result = get_effective_collection_name(str(repo.id), "feature/nonexist")
 assert result == f"code_index_{repo.id}"
 def test_is_branch_index_enabled_true(self) -> None:
 """有 base 记录返回 True。"""
 repo = self._create_repo("enabled")
 RepositoryBranchIndex.objects.create(
 repository=repo,
 branch_name="main",
 is_base_branch=True,
 status=BranchIndexStatus.INDEXED,
 )
 assert is_branch_index_enabled(str(repo.id)) is True
 def test_is_branch_index_enabled_false(self) -> None:
 """无记录返回 False。"""
 repo = self._create_repo("disabled")
 assert is_branch_index_enabled(str(repo.id)) is False

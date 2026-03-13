"""Phase: 索引可观测性测试
测试覆盖：
-: IndexHistory 操作记录查询 API（分页、筛选）
-: 统计 API（chunk 数、语言分布、覆盖率）
-: Qdrant 健康校验 API（collection 存在性 + points_count）
-: 索引新鲜度指示（last_indexed_commit_sha vs 远端 HEAD）
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from django.utils import timezone
from repositories.models import (
 IndexHistory,
 IndexHistoryStatus,
 Repository,
 TriggerType,
)
from services.qdrant_service import QdrantService
pytestmark = pytest.mark.django_db(transaction=True)
# ============================================================================
#: IndexHistory 查询 API
# ============================================================================
class TestIndexHistoryListView:
 """IndexHistory 分页查询测试。"""
 @pytest.fixture
 def repo_with_history(self, repository: Repository) -> Repository:
 """创建带有多条 IndexHistory 记录的仓库。"""
 for i in range(5):
 IndexHistory.objects.create(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.COMPLETED,
 files_added=i,
 files_modified=i * 2,
 files_deleted=0,
 summary_text=f"本次增量：新增 {i} 文件、修改 {i * 2} 文件",
 started_at=timezone.now,
 finished_at=timezone.now,
 )
 IndexHistory.objects.create(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.FAILED,
 error_message="测试错误",
 )
 return repository
 def test_list_returns_paginated(
 self, authenticated_client, repo_with_history: Repository
 ) -> None:
 response = authenticated_client.get(
 f"/api/repositories/{repo_with_history.id}/index/history/?limit=3&offset=0"
 )
 assert response.status_code == 200
 data = response.json
 assert data["total"] == 6
 assert len(data["items"]) == 3
 def test_list_second_page(
 self, authenticated_client, repo_with_history: Repository
 ) -> None:
 response = authenticated_client.get(
 f"/api/repositories/{repo_with_history.id}/index/history/?limit=3&offset=3"
 )
 assert response.status_code == 200
 data = response.json
 assert data["total"] == 6
 assert len(data["items"]) == 3
 def test_filter_by_status(
 self, authenticated_client, repo_with_history: Repository
 ) -> None:
 response = authenticated_client.get(
 f"/api/repositories/{repo_with_history.id}/index/history/?status=failed"
 )
 assert response.status_code == 200
 data = response.json
 assert data["total"] == 1
 assert data["items"][0]["status"] == "failed"
 def test_history_fields_complete(
 self, authenticated_client, repo_with_history: Repository
 ) -> None:
 response = authenticated_client.get(
 f"/api/repositories/{repo_with_history.id}/index/history/?limit=1"
 )
 data = response.json
 item = data["items"][0]
 expected_fields = {
 "id", "trigger_type", "status", "from_sha", "to_sha",
 "files_added", "files_modified", "files_deleted",
 "summary_text", "error_message", "started_at", "finished_at", "created_at",
 }
 assert expected_fields == set(item.keys)
 def test_404_for_nonexistent_repo(self, authenticated_client) -> None:
 response = authenticated_client.get(
 "/api/repositories/00000000-0000-0000-0000-000000000001/index/history/"
 )
 assert response.status_code == 404
# ============================================================================
#: 统计 API
# ============================================================================
class TestIndexStatsView:
 """索引统计 API 测试。"""
 @patch("repositories.index_views.QdrantService.get_collection_stats")
 def test_stats_response(
 self, mock_stats: MagicMock, authenticated_client, repository: Repository
 ) -> None:
 repository.index_total_chunks = 100
 repository.save
 mock_stats.return_value = {
 "exists": True,
 "points_count": 80,
 "language_distribution": {"python": 50, "javascript": 30},
 "indexed_files_count": 15,
 }
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/stats/"
 )
 assert response.status_code == 200
 data = response.json
 assert data["chunks_total"] == 80
 assert data["language_distribution"]["python"] == 50
 assert data["indexed_files_count"] == 15
 assert data["coverage_percent"] == 80.0
 @patch("repositories.index_views.QdrantService.get_collection_stats")
 def test_stats_zero_chunks(
 self, mock_stats: MagicMock, authenticated_client, repository: Repository
 ) -> None:
 mock_stats.return_value = {
 "exists": False,
 "points_count": 0,
 "language_distribution": {},
 "indexed_files_count": 0,
 }
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/stats/"
 )
 assert response.status_code == 200
 data = response.json
 assert data["chunks_total"] == 0
 assert data["coverage_percent"] == 0.0
 def test_404_for_nonexistent_repo(self, authenticated_client) -> None:
 response = authenticated_client.get(
 "/api/repositories/00000000-0000-0000-0000-000000000001/index/stats/"
 )
 assert response.status_code == 404
# ============================================================================
#: Qdrant 健康校验 API
# ============================================================================
class TestRepositoryCollectionHealthView:
 """仓库 Qdrant 集合健康校验测试。"""
 @patch("repositories.index_views.QdrantService.check_collection_health")
 def test_healthy_collection(
 self, mock_health: MagicMock, authenticated_client, repository: Repository
 ) -> None:
 repository.index_total_chunks = 50
 repository.save
 mock_health.return_value = {
 "status": "healthy",
 "collection_exists": True,
 "points_count": 50,
 }
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/health/"
 )
 assert response.status_code == 200
 data = response.json
 assert data["status"] == "healthy"
 assert data["collection_exists"] is True
 assert data["points_count"] == 50
 assert data["expected_points"] == 50
 assert data["points_match"] is True
 @patch("repositories.index_views.QdrantService.check_collection_health")
 def test_unhealthy_collection(
 self, mock_health: MagicMock, authenticated_client, repository: Repository
 ) -> None:
 mock_health.return_value = {
 "status": "unhealthy",
 "collection_exists": False,
 "points_count": 0,
 }
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/health/"
 )
 assert response.status_code == 200
 data = response.json
 assert data["status"] == "unhealthy"
 assert data["collection_exists"] is False
 @patch("repositories.index_views.QdrantService.check_collection_health")
 def test_points_mismatch(
 self, mock_health: MagicMock, authenticated_client, repository: Repository
 ) -> None:
 repository.index_total_chunks = 100
 repository.save
 mock_health.return_value = {
 "status": "healthy",
 "collection_exists": True,
 "points_count": 80,
 }
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/health/"
 )
 data = response.json
 assert data["points_match"] is False
 assert data["expected_points"] == 100
 assert data["points_count"] == 80
# ============================================================================
#: 索引新鲜度指示 API
# ============================================================================
class TestIndexFreshnessView:
 """索引新鲜度指示测试。"""
 @patch("repositories.index_views.IndexFreshnessView._get_remote_head", new_callable=AsyncMock)
 def test_fresh_index(
 self, mock_remote: AsyncMock, authenticated_client, repository: Repository
 ) -> None:
 sha = "a" * 40
 repository.last_indexed_commit_sha = sha
 repository.save
 mock_remote.return_value = sha
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/freshness/"
 )
 assert response.status_code == 200
 data = response.json
 assert data["local_sha"] == sha
 assert data["remote_sha"] == sha
 assert data["is_fresh"] is True
 @patch("repositories.index_views.IndexFreshnessView._get_remote_head", new_callable=AsyncMock)
 def test_stale_index(
 self, mock_remote: AsyncMock, authenticated_client, repository: Repository
 ) -> None:
 local_sha = "a" * 40
 remote_sha = "b" * 40
 repository.last_indexed_commit_sha = local_sha
 repository.save
 mock_remote.return_value = remote_sha
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/freshness/"
 )
 data = response.json
 assert data["is_fresh"] is False
 assert data["local_sha"] == local_sha
 assert data["remote_sha"] == remote_sha
 @patch("repositories.index_views.IndexFreshnessView._get_remote_head", new_callable=AsyncMock)
 def test_no_local_sha(
 self, mock_remote: AsyncMock, authenticated_client, repository: Repository
 ) -> None:
 mock_remote.return_value = "c" * 40
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/freshness/"
 )
 data = response.json
 assert data["local_sha"] == ""
 assert data["is_fresh"] is False
 @patch("repositories.index_views.IndexFreshnessView._get_remote_head", new_callable=AsyncMock)
 def test_remote_error(
 self, mock_remote: AsyncMock, authenticated_client, repository: Repository
 ) -> None:
 mock_remote.side_effect = RuntimeError("网络超时")
 repository.last_indexed_commit_sha = "d" * 40
 repository.save
 response = authenticated_client.get(
 f"/api/repositories/{repository.id}/index/freshness/"
 )
 data = response.json
 assert data["error"] == "网络超时"
 assert data["is_fresh"] is None
# ============================================================================
# QdrantService 新方法单元测试
# ============================================================================
class TestQdrantServiceCollectionStats:
 """QdrantService.get_collection_stats 单元测试。"""
 @patch("services.qdrant_service.QdrantService.get_client")
 def test_collection_not_exists(self, mock_client: MagicMock) -> None:
 client = MagicMock
 mock_client.return_value = client
 collections = MagicMock
 collections.collections =
 client.get_collections.return_value = collections
 result = QdrantService.get_collection_stats("test-repo-id")
 assert result["exists"] is False
 assert result["points_count"] == 0
 @patch("services.qdrant_service.QdrantService.get_client")
 def test_collection_with_data(self, mock_client: MagicMock) -> None:
 client = MagicMock
 mock_client.return_value = client
 col = MagicMock
 col.name = "code_index_test-repo-id"
 collections = MagicMock
 collections.collections = [col]
 client.get_collections.return_value = collections
 count_result = MagicMock
 count_result.count = 3
 client.count.return_value = count_result
 point1 = MagicMock
 point1.payload = {"language": "python", "file_path": "a.py"}
 point2 = MagicMock
 point2.payload = {"language": "python", "file_path": "b.py"}
 point3 = MagicMock
 point3.payload = {"language": "javascript", "file_path": "c.js"}
 client.scroll.return_value = ([point1, point2, point3], None)
 result = QdrantService.get_collection_stats("test-repo-id")
 assert result["exists"] is True
 assert result["points_count"] == 3
 assert result["language_distribution"] == {"python": 2, "javascript": 1}
 assert result["indexed_files_count"] == 3
class TestQdrantServiceCollectionHealth:
 """QdrantService.check_collection_health 单元测试。"""
 @patch("services.qdrant_service.QdrantService.get_client")
 def test_healthy(self, mock_client: MagicMock) -> None:
 client = MagicMock
 mock_client.return_value = client
 col = MagicMock
 col.name = "code_index_repo-id"
 collections = MagicMock
 collections.collections = [col]
 client.get_collections.return_value = collections
 count_result = MagicMock
 count_result.count = 42
 client.count.return_value = count_result
 result = QdrantService.check_collection_health("repo-id")
 assert result["status"] == "healthy"
 assert result["collection_exists"] is True
 assert result["points_count"] == 42
 @patch("services.qdrant_service.QdrantService.get_client")
 def test_unhealthy_no_collection(self, mock_client: MagicMock) -> None:
 client = MagicMock
 mock_client.return_value = client
 collections = MagicMock
 collections.collections =
 client.get_collections.return_value = collections
 result = QdrantService.check_collection_health("repo-id")
 assert result["status"] == "unhealthy"
 assert result["collection_exists"] is False

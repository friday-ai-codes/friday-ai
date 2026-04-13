"""分支感知索引管线测试：payload 注入、branch payload index、DB 记录管理。"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from django.utils import timezone
from services.indexer import IndexerService
class TestBaseBranchMetadata:
 """测试 _build_points 的分支元数据注入。"""
 @staticmethod
 def _make_chunk(**overrides):
 """构造最小化的 CodeChunk mock。"""
 chunk = MagicMock
 chunk.file_path = overrides.get("file_path", "src/main.py")
 chunk.file_hash = overrides.get("file_hash", "abc123")
 chunk.language = overrides.get("language", "python")
 chunk.node_type = overrides.get("node_type", "function")
 chunk.start_line = overrides.get("start_line", 1)
 chunk.end_line = overrides.get("end_line", 10)
 chunk.content = overrides.get("content", "def hello: pass")
 chunk.context_header = overrides.get("context_header", "module:main")
 return chunk
 def test_build_points_with_branch_name_includes_metadata(self):
 """传入 branch_name 时，payload 应包含 branch_name 和 is_base_branch。"""
 chunk = self._make_chunk
 embedding = [0.1] * 3
 points = IndexerService._build_points(
 [chunk], [embedding], None, False,
 branch_name="main", is_base_branch=True,
 )
 assert len(points) == 1
 payload = points[0]["payload"]
 assert payload["branch_name"] == "main"
 assert payload["is_base_branch"] is True
 def test_build_points_without_branch_name_no_metadata(self):
 """不传 branch_name 时，payload 不应包含 branch 相关字段（向后兼容）。"""
 chunk = self._make_chunk
 embedding = [0.1] * 3
 points = IndexerService._build_points(
 [chunk], [embedding], None, False,
 )
 assert len(points) == 1
 payload = points[0]["payload"]
 assert "branch_name" not in payload
 assert "is_base_branch" not in payload
 def test_build_points_branch_metadata_with_hybrid(self):
 """hybrid 模式下，branch 元数据同样正确注入。"""
 chunk = self._make_chunk
 embedding = [0.1] * 3
 sparse = {"indices": [0, 1], "values": [0.5, 0.3]}
 with patch("qdrant_client.http.models.SparseVector") as mock_sv:
 mock_sv.return_value = MagicMock
 points = IndexerService._build_points(
 [chunk], [embedding], [sparse], True,
 branch_name="develop", is_base_branch=False,
 )
 assert len(points) == 1
 payload = points[0]["payload"]
 assert payload["branch_name"] == "develop"
 assert payload["is_base_branch"] is False
 @patch("services.qdrant_service.QdrantService.get_client")
 def test_create_branch_payload_index_success(self, mock_get_client):
 """create_branch_payload_index 应调用 create_payload_index 创建 keyword index。"""
 from services.qdrant_service import QdrantService
 mock_client = MagicMock
 mock_get_client.return_value = mock_client
 result = QdrantService.create_branch_payload_index("test_collection")
 assert result is True
 mock_client.create_payload_index.assert_called_once
 call_kwargs = mock_client.create_payload_index.call_args
 assert call_kwargs[1]["collection_name"] == "test_collection"
 assert call_kwargs[1]["field_name"] == "branch_name"
 @patch("services.qdrant_service.QdrantService.get_client")
 def test_create_branch_payload_index_already_exists(self, mock_get_client):
 """index 已存在时应返回 False 而非崩溃。"""
 from qdrant_client.http.exceptions import UnexpectedResponse
 from services.qdrant_service import QdrantService
 mock_client = MagicMock
 mock_get_client.return_value = mock_client
 import httpx
 mock_client.create_payload_index.side_effect = UnexpectedResponse(
 status_code=400, reason_phrase="Bad Request",
 content=b"already exists", headers=httpx.Headers,
 )
 result = QdrantService.create_branch_payload_index("test_collection")
 assert result is False
@pytest.mark.django_db(transaction=True)
class TestBranchIndexRecord:
 """测试 _update_branch_index_record 创建/更新 DB 记录。"""
 @pytest.fixture
 def repository(self):
 from repositories.models import Repository
 return Repository.objects.create(
 name="test-repo",
 git_url="https://github.com/test/repo.git",
 default_branch="main",
 )
 @pytest.fixture
 def indexer(self, repository):
 return IndexerService(str(repository.id))
 @pytest.mark.asyncio
 @patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="abc1234567890abcdef1234567890abcdef123456")
 async def test_creates_branch_index_record(self, mock_sha, repository, indexer):
 """run_full_index 后应创建 RepositoryBranchIndex 记录。"""
 from repositories.models import BranchIndexStatus, RepositoryBranchIndex
 await indexer._update_branch_index_record(
 repo_path="/tmp/fake",
 branch_name="main",
 is_base_branch=True,
 points_count=42,
 )
 record = await RepositoryBranchIndex.objects.aget(
 repository=repository, branch_name="main",
 )
 assert record.is_base_branch is True
 assert record.head_sha == "abc1234567890abcdef1234567890abcdef123456"
 assert record.status == BranchIndexStatus.INDEXED
 assert record.effective_chunks_count == 42
 assert record.is_stale is False
 @pytest.mark.asyncio
 @patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="def456")
 async def test_updates_existing_branch_index_record(self, mock_sha, repository, indexer):
 """重新索引时应更新已有记录。"""
 from repositories.models import BranchIndexStatus, RepositoryBranchIndex
 await RepositoryBranchIndex.objects.acreate(
 repository=repository,
 branch_name="main",
 is_base_branch=True,
 status=BranchIndexStatus.INDEXED,
 effective_chunks_count=10,
 )
 await indexer._update_branch_index_record(
 repo_path="/tmp/fake",
 branch_name="main",
 is_base_branch=True,
 points_count=99,
 )
 record = await RepositoryBranchIndex.objects.aget(
 repository=repository, branch_name="main",
 )
 assert record.effective_chunks_count == 99
 assert record.head_sha == "def456"
@pytest.mark.django_db(transaction=True)
class TestStalePropagate:
 """测试 base 重索引后 overlay stale 传播。"""
 @pytest.fixture
 def repository(self):
 from repositories.models import Repository
 return Repository.objects.create(
 name="test-repo-stale",
 git_url="https://github.com/test/stale-repo.git",
 default_branch="main",
 )
 @pytest.fixture
 def indexer(self, repository):
 return IndexerService(str(repository.id))
 @pytest.mark.asyncio
 @patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="head123")
 async def test_base_reindex_marks_overlays_stale(self, mock_sha, repository, indexer):
 """base 分支重索引后，所有非 base 的 overlay 应标记为 is_stale=True。"""
 from repositories.models import BranchIndexStatus, RepositoryBranchIndex
 overlay1 = await RepositoryBranchIndex.objects.acreate(
 repository=repository,
 branch_name="feature/a",
 is_base_branch=False,
 is_stale=False,
 status=BranchIndexStatus.INDEXED,
 )
 overlay2 = await RepositoryBranchIndex.objects.acreate(
 repository=repository,
 branch_name="feature/b",
 is_base_branch=False,
 is_stale=False,
 status=BranchIndexStatus.INDEXED,
 )
 await indexer._update_branch_index_record(
 repo_path="/tmp/fake",
 branch_name="main",
 is_base_branch=True,
 points_count=50,
 )
 await overlay1.arefresh_from_db
 await overlay2.arefresh_from_db
 assert overlay1.is_stale is True
 assert overlay2.is_stale is True
 @pytest.mark.asyncio
 @patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="head456")
 async def test_non_base_reindex_does_not_mark_stale(self, mock_sha, repository, indexer):
 """非 base 分支索引不应触发 stale 传播。"""
 from repositories.models import BranchIndexStatus, RepositoryBranchIndex
 overlay = await RepositoryBranchIndex.objects.acreate(
 repository=repository,
 branch_name="feature/c",
 is_base_branch=False,
 is_stale=False,
 status=BranchIndexStatus.INDEXED,
 )
 await indexer._update_branch_index_record(
 repo_path="/tmp/fake",
 branch_name="feature/x",
 is_base_branch=False,
 points_count=10,
 )
 await overlay.arefresh_from_db
 assert overlay.is_stale is False

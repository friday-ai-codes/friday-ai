"""Phase: 索引去重幂等性和 shallow clone 回退测试。"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from django.test import TransactionTestCase
from repositories.models import FileIndex, IndexHistory, IndexHistoryStatus, Repository, TriggerType
@pytest.mark.django_db(transaction=True)
class TestFileIndexDedup(TransactionTestCase):
 """: DB 级文件去重幂等性测试。"""
 def setUp(self) -> None:
 self.repo = Repository.objects.create(
 name="test-repo",
 git_url="https://github.com/test/repo.git",
 )
 self.repo_id = str(self.repo.id)
 def test_update_or_create_idempotent(self) -> None:
 """同一 (repository_id, file_path) 多次 update_or_create 只产生一条记录。"""
 for i in range(3):
 FileIndex.objects.update_or_create(
 repository_id=self.repo_id,
 file_path="src/main.py",
 defaults={"file_hash": f"hash_{i}"},
 )
 assert FileIndex.objects.filter(
 repository_id=self.repo_id, file_path="src/main.py"
 ).count == 1
 record = FileIndex.objects.get(
 repository_id=self.repo_id, file_path="src/main.py"
 )
 # 最后一次写入的 hash
 assert record.file_hash == "hash_2"
 def test_unique_constraint_prevents_duplicates(self) -> None:
 """unique_together 约束阻止对同一文件的重复插入。"""
 FileIndex.objects.create(
 repository_id=self.repo_id,
 file_path="src/app.py",
 file_hash="abc123",
 )
 from django.db import IntegrityError
 with pytest.raises(IntegrityError):
 FileIndex.objects.create(
 repository_id=self.repo_id,
 file_path="src/app.py",
 file_hash="def456",
 )
 def test_different_files_allowed(self) -> None:
 """同一仓库的不同文件可以各自创建记录。"""
 FileIndex.objects.create(
 repository_id=self.repo_id,
 file_path="src/a.py",
 file_hash="hash_a",
 )
 FileIndex.objects.create(
 repository_id=self.repo_id,
 file_path="src/b.py",
 file_hash="hash_b",
 )
 assert FileIndex.objects.filter(repository_id=self.repo_id).count == 2
 def test_different_repos_same_path_allowed(self) -> None:
 """不同仓库的相同文件路径可以各自创建记录。"""
 repo2 = Repository.objects.create(
 name="test-repo-2",
 git_url="https://github.com/test/repo2.git",
 )
 FileIndex.objects.create(
 repository_id=self.repo_id,
 file_path="src/main.py",
 file_hash="hash_1",
 )
 FileIndex.objects.create(
 repository_id=str(repo2.id),
 file_path="src/main.py",
 file_hash="hash_2",
 )
 assert FileIndex.objects.count == 2
@pytest.mark.django_db(transaction=True)
class TestShallowCloneFallback(TransactionTestCase):
 """: Shallow clone 回退测试。"""
 def setUp(self) -> None:
 self.repo = Repository.objects.create(
 name="test-repo",
 git_url="https://github.com/test/repo.git",
 last_indexed_commit_sha="abc123def456",
 )
 self.repo_id = str(self.repo.id)
 def _make_repo_mock(self) -> Repository:
 """返回一个预设了 credential 缓存的 repo 实例，避免同步 DB 查询。"""
 # 通过 Django 内部缓存机制避免 getattr 触发同步 DB 访问
 self.repo._state.fields_cache["credential"] = None # type: ignore[attr-defined]
 return self.repo
 @pytest.mark.asyncio
 async def test_shallow_clone_git_diff_fails_fallback_to_full(self) -> None:
 """shallow clone 环境 git diff 失败时回退到 run_full_index。"""
 from services.indexer import clone_and_index_repository
 mock_full_result = {"status": "success", "files_processed": 5, "chunks_indexed": 10, "added": 5}
 with (
 patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="new_sha_123"),
 patch("services.indexer._fetch_commit", new_callable=AsyncMock, return_value=True),
 patch("services.indexer._is_shallow_clone", new_callable=AsyncMock, return_value=True),
 patch("services.indexer.IndexerService.run_git_diff_index", new_callable=AsyncMock) as mock_diff,
 patch("services.indexer.IndexerService.run_full_index", new_callable=AsyncMock, return_value=mock_full_result) as mock_full,
 patch("services.indexer.IndexerService.run_incremental_index", new_callable=AsyncMock) as mock_incr,
 patch("tempfile.mkdtemp", return_value="/tmp/fake_clone"),
 patch("shutil.rmtree"),
 patch("os.path.exists", return_value=True),
 patch("asyncio.create_subprocess_exec") as mock_proc,
 ):
 from services.indexer import GitDiffError
 mock_diff.side_effect = GitDiffError("shallow clone cannot diff")
 # mock git clone 成功
 process_mock = AsyncMock
 process_mock.communicate = AsyncMock(return_value=(b"", b""))
 process_mock.returncode = 0
 mock_proc.return_value = process_mock
 # 需要 mock get_repository_data
 with patch.object(Repository.objects, "select_related") as mock_sr:
 mock_qs = MagicMock
 mock_qs.aget = AsyncMock(return_value=self._make_repo_mock)
 mock_sr.return_value = mock_qs
 with patch("common.encryption.decrypt_value", return_value=None):
 _result = await clone_and_index_repository(self.repo_id)
 # 应该调用 full_index 而非 incremental
 mock_full.assert_called_once
 mock_incr.assert_not_called
 @pytest.mark.asyncio
 async def test_non_shallow_git_diff_fails_fallback_to_incremental(self) -> None:
 """非 shallow clone 环境 git diff 失败时回退到 run_incremental_index。"""
 from services.indexer import GitDiffError, clone_and_index_repository
 mock_incr_result = {"status": "success", "added": 1, "updated": 0, "deleted": 0, "skipped": 3}
 with (
 patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="new_sha_123"),
 patch("services.indexer._fetch_commit", new_callable=AsyncMock, return_value=True),
 patch("services.indexer._is_shallow_clone", new_callable=AsyncMock, return_value=False),
 patch("services.indexer.IndexerService.run_git_diff_index", new_callable=AsyncMock, side_effect=GitDiffError("diff failed")),
 patch("services.indexer.IndexerService.run_full_index", new_callable=AsyncMock) as mock_full,
 patch("services.indexer.IndexerService.run_incremental_index", new_callable=AsyncMock, return_value=mock_incr_result) as mock_incr,
 patch("tempfile.mkdtemp", return_value="/tmp/fake_clone"),
 patch("shutil.rmtree"),
 patch("os.path.exists", return_value=True),
 patch("asyncio.create_subprocess_exec") as mock_proc,
 ):
 process_mock = AsyncMock
 process_mock.communicate = AsyncMock(return_value=(b"", b""))
 process_mock.returncode = 0
 mock_proc.return_value = process_mock
 with patch.object(Repository.objects, "select_related") as mock_sr:
 mock_qs = MagicMock
 mock_qs.aget = AsyncMock(return_value=self._make_repo_mock)
 mock_sr.return_value = mock_qs
 with patch("common.encryption.decrypt_value", return_value=None):
 _result = await clone_and_index_repository(self.repo_id)
 # 非 shallow 应该调用 incremental 而非 full
 mock_incr.assert_called_once
 mock_full.assert_not_called
 @pytest.mark.asyncio
 async def test_fetch_fails_shallow_fallback_to_full(self) -> None:
 """git fetch 失败 + shallow clone 时回退到 run_full_index。"""
 from services.indexer import clone_and_index_repository
 mock_full_result = {"status": "success", "files_processed": 3, "chunks_indexed": 6, "added": 3}
 with (
 patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="new_sha_123"),
 patch("services.indexer._fetch_commit", new_callable=AsyncMock, return_value=False),
 patch("services.indexer._is_shallow_clone", new_callable=AsyncMock, return_value=True),
 patch("services.indexer.IndexerService.run_full_index", new_callable=AsyncMock, return_value=mock_full_result) as mock_full,
 patch("services.indexer.IndexerService.run_incremental_index", new_callable=AsyncMock) as mock_incr,
 patch("tempfile.mkdtemp", return_value="/tmp/fake_clone"),
 patch("shutil.rmtree"),
 patch("os.path.exists", return_value=True),
 patch("asyncio.create_subprocess_exec") as mock_proc,
 ):
 process_mock = AsyncMock
 process_mock.communicate = AsyncMock(return_value=(b"", b""))
 process_mock.returncode = 0
 mock_proc.return_value = process_mock
 with patch.object(Repository.objects, "select_related") as mock_sr:
 mock_qs = MagicMock
 mock_qs.aget = AsyncMock(return_value=self._make_repo_mock)
 mock_sr.return_value = mock_qs
 with patch("common.encryption.decrypt_value", return_value=None):
 _result = await clone_and_index_repository(self.repo_id)
 mock_full.assert_called_once
 mock_incr.assert_not_called
 @pytest.mark.asyncio
 async def test_fallback_records_reason_in_history(self) -> None:
 """回退后 IndexHistory.error_message 包含 [fallback] 前缀。"""
 from services.indexer import GitDiffError, clone_and_index_repository
 history = await IndexHistory.objects.acreate(
 repository_id=self.repo_id,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 )
 history_id = str(history.id)
 mock_full_result = {"status": "success", "files_processed": 2, "chunks_indexed": 4, "added": 2}
 with (
 patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="new_sha_456"),
 patch("services.indexer._fetch_commit", new_callable=AsyncMock, return_value=True),
 patch("services.indexer._is_shallow_clone", new_callable=AsyncMock, return_value=True),
 patch("services.indexer.IndexerService.run_git_diff_index", new_callable=AsyncMock, side_effect=GitDiffError("fatal: bad object")),
 patch("services.indexer.IndexerService.run_full_index", new_callable=AsyncMock, return_value=mock_full_result),
 patch("tempfile.mkdtemp", return_value="/tmp/fake_clone"),
 patch("shutil.rmtree"),
 patch("os.path.exists", return_value=True),
 patch("asyncio.create_subprocess_exec") as mock_proc,
 ):
 process_mock = AsyncMock
 process_mock.communicate = AsyncMock(return_value=(b"", b""))
 process_mock.returncode = 0
 mock_proc.return_value = process_mock
 # 直接 patch select_related.aget
 with patch.object(Repository.objects, "select_related") as mock_sr:
 mock_qs = MagicMock
 mock_qs.aget = AsyncMock(return_value=self._make_repo_mock)
 mock_sr.return_value = mock_qs
 with patch("common.encryption.decrypt_value", return_value=None):
 await clone_and_index_repository(self.repo_id, history_id=history_id)
 await history.arefresh_from_db
 assert history.error_message is not None
 assert history.error_message.startswith("[fallback]")
 assert "git diff 失败" in history.error_message
 @pytest.mark.asyncio
 async def test_normal_git_diff_no_fallback(self) -> None:
 """非 shallow clone 正常 git diff 成功时不触发回退。"""
 from services.indexer import clone_and_index_repository
 mock_diff_result = {"status": "success", "added": 1, "updated": 0, "deleted": 0, "renamed": 0}
 with (
 patch("services.indexer._get_head_sha", new_callable=AsyncMock, return_value="new_sha_789"),
 patch("services.indexer._fetch_commit", new_callable=AsyncMock, return_value=True),
 patch("services.indexer._is_shallow_clone", new_callable=AsyncMock) as mock_shallow,
 patch("services.indexer.IndexerService.run_git_diff_index", new_callable=AsyncMock, return_value=mock_diff_result) as mock_diff,
 patch("services.indexer.IndexerService.run_full_index", new_callable=AsyncMock) as mock_full,
 patch("services.indexer.IndexerService.run_incremental_index", new_callable=AsyncMock) as mock_incr,
 patch("tempfile.mkdtemp", return_value="/tmp/fake_clone"),
 patch("shutil.rmtree"),
 patch("os.path.exists", return_value=True),
 patch("asyncio.create_subprocess_exec") as mock_proc,
 ):
 process_mock = AsyncMock
 process_mock.communicate = AsyncMock(return_value=(b"", b""))
 process_mock.returncode = 0
 mock_proc.return_value = process_mock
 with patch.object(Repository.objects, "select_related") as mock_sr:
 mock_qs = MagicMock
 mock_qs.aget = AsyncMock(return_value=self._make_repo_mock)
 mock_sr.return_value = mock_qs
 with patch("common.encryption.decrypt_value", return_value=None):
 _result = await clone_and_index_repository(self.repo_id)
 # git diff 成功时不应调用 _is_shallow_clone
 mock_shallow.assert_not_called
 mock_diff.assert_called_once
 mock_full.assert_not_called
 mock_incr.assert_not_called

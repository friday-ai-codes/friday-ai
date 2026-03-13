"""Phase 数据基础修复测试：
测试覆盖：
-: asyncio.create_subprocess_exec 替换 subprocess.run
-: 模块级强引用集合防止 GC 回收
-: select_for_update(skip_locked=True) 并发保护
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from repositories.models import (
 IndexHistory,
 IndexHistoryStatus,
 IndexStatus,
 Repository,
 TriggerType,
)
# ============================================================================
#: asyncio.create_subprocess_exec 替换 subprocess.run
# ============================================================================
class TestAsyncSubprocess:
 """验证 clone_and_index_repository 使用 asyncio 子进程而非阻塞的 subprocess.run。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db
 async def test_git_clone_uses_create_subprocess_exec(self, repository):
 """clone_and_index_repository 使用 asyncio.create_subprocess_exec，不调用 subprocess.run"""
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ) as mock_create_subprocess,
 patch("services.indexer.qdrant_get_stored_file_hashes", return_value={}),
 patch("services.indexer.IndexerService.run_full_index", new_callable=AsyncMock, return_value={"status": "success"}),
 patch("subprocess.run", side_effect=AssertionError("subprocess.run 不应被调用")),
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(str(repository.id))
 mock_create_subprocess.assert_called_once
 @pytest.mark.asyncio
 @pytest.mark.django_db
 async def test_git_clone_timeout_uses_wait_for(self, repository):
 """超时通过 asyncio.wait_for 实现（TimeoutError 时 kill 进程）"""
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
 mock_proc.kill = MagicMock
 # kill 后再次 communicate 清理
 mock_proc.communicate.side_effect = [asyncio.TimeoutError, (b"", b"")]
 with (
 patch(
 "services.indexer.asyncio.create_subprocess_exec",
 return_value=mock_proc,
 ),
 patch("services.indexer.asyncio.wait_for", side_effect=asyncio.TimeoutError),
 ):
 from services.indexer import clone_and_index_repository
 result = await clone_and_index_repository(str(repository.id))
 assert result["status"] == "error"
 assert "timed out" in result["message"].lower or "timeout" in result["message"].lower
# ============================================================================
#: 模块级强引用集合防止 GC 回收
# ============================================================================
class TestTaskReferenceManagement:
 """验证 asyncio.create_task 后任务被强引用保护。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db
 async def test_module_level_index_tasks_set_exists(self):
 """index_views.py 模块级 _index_tasks 集合存在且为 set 类型"""
 from repositories.index_views import _index_tasks
 assert isinstance(_index_tasks, set)
 @pytest.mark.asyncio
 @pytest.mark.django_db
 async def test_task_added_to_index_tasks_set(self):
 """_schedule_index 创建的任务被添加到 _index_tasks 集合"""
 from repositories.index_views import _index_tasks, _schedule_index
 # mock clone_and_index_repository 防止实际执行
 async def fake_index(repo_id, *, history_id=None):
 return {"status": "success"}
 with patch("repositories.index_views.clone_and_index_repository", side_effect=fake_index):
 initial_count = len(_index_tasks)
 task = _schedule_index("fake-repo-id", "fake-history-id")
 assert len(_index_tasks) == initial_count + 1
 assert task in _index_tasks
 # 等待任务完成以清理
 await task
 @pytest.mark.asyncio
 @pytest.mark.django_db
 async def test_task_removed_from_set_after_completion(self):
 """任务完成后 _index_tasks 自动移除（add_done_callback discard）"""
 from repositories.index_views import _index_tasks, _schedule_index
 async def fake_index(repo_id, *, history_id=None):
 return {"status": "success"}
 with patch("repositories.index_views.clone_and_index_repository", side_effect=fake_index):
 task = _schedule_index("fake-repo-id", "fake-history-id")
 await task
 # 完成后等待 callback 执行
 await asyncio.sleep(0.01)
 assert task not in _index_tasks
# ============================================================================
#: select_for_update(skip_locked=True) 并发保护
# ============================================================================
class TestConcurrencyLock:
 """验证 DB 级 select_for_update 并发锁。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_acquire_index_lock_returns_repo_when_free(self, repository):
 """单次触发正常获得锁，返回 Repository 实例"""
 from repositories.index_views import _acquire_index_lock_async
 result = await _acquire_index_lock_async(str(repository.id))
 assert result is not None
 assert str(result.id) == str(repository.id)
 @pytest.mark.asyncio
 @pytest.mark.django_db(transaction=True)
 async def test_acquire_index_lock_returns_none_for_nonexistent(self):
 """不存在的仓库返回 None"""
 from repositories.index_views import _acquire_index_lock_async
 result = await _acquire_index_lock_async(str(uuid.uuid4))
 assert result is None
 @pytest.mark.asyncio
 @pytest.mark.django_db
 async def test_index_trigger_creates_index_history(self, repository):
 """IndexTriggerView.post 触发时创建 IndexHistory 记录"""
 from django.test import RequestFactory
 from adrf.views import APIView
 from repositories.index_views import IndexTriggerView
 async def fake_index(repo_id, *, history_id=None):
 return {"status": "success"}
 with (
 patch("repositories.index_views.clone_and_index_repository", side_effect=fake_index),
 patch("repositories.index_views._acquire_index_lock_async", return_value=repository),
 ):
 factory = RequestFactory
 request = factory.post(f"/api/repositories/{repository.id}/index/")
 request.user = MagicMock
 request.auth = None
 view = IndexTriggerView
 response = await view.post(request, repository.id)
 assert response.status_code == 202
 assert "history_id" in response.data
 # 验证 IndexHistory 记录已创建
 history = await IndexHistory.objects.aget(id=response.data["history_id"])
 assert history.trigger_type == TriggerType.MANUAL
 assert history.status == IndexHistoryStatus.RUNNING
# ============================================================================
# IndexHistory 状态更新测试
# ============================================================================
class TestIndexHistoryStatusUpdate:
 """验证 clone_and_index_repository 完成后更新 IndexHistory 状态。"""
 @pytest.mark.asyncio
 @pytest.mark.django_db
 async def test_successful_index_updates_history_to_completed(self, repository):
 """索引成功后 IndexHistory 状态更新为 COMPLETED"""
 from django.utils import timezone
 history = await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.returncode = 0
 with (
 patch("services.indexer.asyncio.create_subprocess_exec", return_value=mock_proc),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch("services.indexer.qdrant_get_stored_file_hashes", return_value={}),
 patch("services.indexer.IndexerService.run_full_index", new_callable=AsyncMock, return_value={"status": "success"}),
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(str(repository.id), history_id=str(history.id))
 await history.arefresh_from_db
 assert history.status == IndexHistoryStatus.COMPLETED
 assert history.finished_at is not None
 @pytest.mark.asyncio
 @pytest.mark.django_db
 async def test_failed_index_updates_history_to_failed(self, repository):
 """索引失败后 IndexHistory 状态更新为 FAILED 并记录错误信息"""
 from django.utils import timezone
 history = await IndexHistory.objects.acreate(
 repository=repository,
 trigger_type=TriggerType.MANUAL,
 status=IndexHistoryStatus.RUNNING,
 started_at=timezone.now,
 )
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b"clone error"))
 mock_proc.returncode = 1
 with (
 patch("services.indexer.asyncio.create_subprocess_exec", return_value=mock_proc),
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"clone error")),
 ):
 from services.indexer import clone_and_index_repository
 result = await clone_and_index_repository(str(repository.id), history_id=str(history.id))
 await history.arefresh_from_db
 assert history.status == IndexHistoryStatus.FAILED
 assert history.finished_at is not None
 assert history.error_message is not None

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
 TriggerType,
)
# SQLite 内存数据库 + async 需要 transaction=True 避免跨线程锁冲突
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]
# ============================================================================
#: asyncio.create_subprocess_exec 替换 subprocess.run
# ============================================================================
class TestAsyncSubprocess:
 """验证 clone_and_index_repository 使用 asyncio 子进程而非阻塞的 subprocess.run。"""
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
 patch("services.indexer.asyncio.wait_for", return_value=(b"", b"")),
 patch("services.indexer.qdrant_get_stored_file_hashes", return_value={}),
 patch("services.indexer.IndexerService.run_full_index", new_callable=AsyncMock, return_value={"status": "success"}),
 ):
 from services.indexer import clone_and_index_repository
 await clone_and_index_repository(str(repository.id))
 # 至少调用一次：clone 和 rev-parse HEAD
 assert mock_create_subprocess.call_count >= 1
 # 第一次调用是 git clone
 first_call_args = mock_create_subprocess.call_args_list[0]
 assert "clone" in first_call_args[0]
 async def test_git_clone_timeout_uses_wait_for(self, repository):
 """超时通过 asyncio.wait_for 实现（TimeoutError 时 kill 进程）"""
 mock_proc = AsyncMock
 mock_proc.communicate = AsyncMock(return_value=(b"", b""))
 mock_proc.kill = MagicMock
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
#: 后台 indexing 任务必须脱离请求 event loop
# ============================================================================
class TestBackgroundRunnerIntegration:
 """验证 _schedule_index 把任务调度到独立 worker loop 而非请求 loop。
 历史问题（2026-05-12）：原实现 `asyncio.create_task(...)` 把任务绑死在 ASGI
 请求 event loop。HTTP 响应一返回，asgiref CurrentThreadExecutor 关闭 →
 后台 task 后续 ORM `sync_to_async` 全部抛 `CurrentThreadExecutor already
 quit or is broken`。
 """
 async def test_schedule_index_returns_concurrent_future(self):
 """_schedule_index 返回 concurrent.futures.Future（来自 worker loop）。"""
 from concurrent.futures import Future
 from repositories.index_views import _schedule_index
 async def fake_index(repo_id, *, history_id=None, branch=None):
 return {"status": "success"}
 with patch(
 "repositories.index_views.clone_and_index_repository",
 side_effect=fake_index,
 ):
 future = _schedule_index("fake-repo-id", "fake-history-id")
 try:
 assert isinstance(future, Future)
 # .result 会阻塞直到 worker loop 完成 task —
 # 之所以能成功跑完，正说明 task 在 worker loop 上运行。
 result = await asyncio.get_event_loop.run_in_executor(
 None, future.result, 5.0,
 )
 assert result == {"status": "success"}
 finally:
 if not future.done:
 future.cancel
 async def test_task_runs_on_worker_thread_not_request_thread(self):
 """worker loop 跑在独立线程：task 看到的 thread ident 与请求线程不同。"""
 import threading
 from repositories.index_views import _schedule_index
 request_thread_id = threading.get_ident
 observed: dict[str, int] = {}
 async def fake_index(repo_id, *, history_id=None, branch=None):
 observed["task_thread_id"] = threading.get_ident
 return {"status": "success"}
 with patch(
 "repositories.index_views.clone_and_index_repository",
 side_effect=fake_index,
 ):
 future = _schedule_index("fake-repo-id", "fake-history-id")
 try:
 await asyncio.get_event_loop.run_in_executor(
 None, future.result, 5.0,
 )
 finally:
 if not future.done:
 future.cancel
 assert observed.get("task_thread_id") not in (None, request_thread_id), (
 "后台 task 必须运行在 worker 线程，不能复用请求线程"
 )
# ============================================================================
#: select_for_update(skip_locked=True) 并发保护
# ============================================================================
class TestConcurrencyLock:
 """验证 DB 级 select_for_update 并发锁。"""
 async def test_acquire_index_lock_returns_repo_when_free(self, repository):
 """单次触发正常获得锁，返回 Repository 实例"""
 from repositories.index_views import _acquire_index_lock_async
 result = await _acquire_index_lock_async(str(repository.id))
 assert result is not None
 assert str(result.id) == str(repository.id)
 async def test_acquire_index_lock_returns_none_for_nonexistent(self):
 """不存在的仓库返回 None"""
 from repositories.index_views import _acquire_index_lock_async
 result = await _acquire_index_lock_async(str(uuid.uuid4))
 assert result is None
 async def test_index_trigger_creates_index_history(self, repository):
 """IndexTriggerView.post 触发时创建 IndexHistory 记录"""
 from django.test import RequestFactory
 from repositories.index_views import IndexTriggerView
 async def fake_index(repo_id, *, history_id=None):
 return {"status": "success"}
 with (
 patch("repositories.index_views.clone_and_index_repository", side_effect=fake_index),
 patch("repositories.index_views._acquire_index_lock_async", return_value=repository),
 ):
 from rest_framework.test import APIRequestFactory
 from rest_framework.request import Request
 from rest_framework.parsers import JSONParser
 factory = APIRequestFactory
 wsgi_request = factory.post(f"/api/repositories/{repository.id}/index/", format="json")
 wsgi_request.user = MagicMock
 wsgi_request.auth = None
 request = Request(wsgi_request, parsers=[JSONParser])
 view = IndexTriggerView
 response = await view.post(request, repository.id)
 assert response.status_code == 202
 assert "history_id" in response.data
 history = await IndexHistory.objects.aget(id=response.data["history_id"])
 assert history.trigger_type == TriggerType.MANUAL
 assert history.status == IndexHistoryStatus.RUNNING
# ============================================================================
# IndexHistory 状态更新测试
# ============================================================================
class TestIndexHistoryStatusUpdate:
 """验证 clone_and_index_repository 完成后更新 IndexHistory 状态。"""
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
 _result = await clone_and_index_repository(str(repository.id), history_id=str(history.id))
 await history.arefresh_from_db
 assert history.status == IndexHistoryStatus.FAILED
 assert history.finished_at is not None
 assert history.error_message is not None

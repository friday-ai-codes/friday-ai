"""implementation 数据基础修复测试：work item/04/05

测试覆盖：
- asyncio.create_subprocess_exec 替换 subprocess.run
- 模块级强引用集合防止 GC 回收
- select_for_update(skip_locked=True) 并发保护
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repositories.models import (
    IndexHistory,
    IndexHistoryStatus,
    IndexStatus,
    RepositoryBranchIndex,
    TriggerType,
)

# SQLite 内存数据库 + async 需要 transaction=True 避免跨线程锁冲突
pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# ============================================================================
# asyncio.create_subprocess_exec 替换 subprocess.run
# ============================================================================


class TestAsyncSubprocess:
    """验证 clone_and_index_repository 使用 asyncio 子进程而非阻塞的 subprocess.run。"""

    async def test_git_clone_uses_create_subprocess_exec(self, repository):
        """clone_and_index_repository 使用 asyncio.create_subprocess_exec，不调用 subprocess.run"""
        mock_proc = AsyncMock()
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

    async def test_git_clone_checks_out_repository_default_branch(self, repository):
        """基础索引必须 clone 当前 default_branch，默认分支变更后才能滚动更新新分支。"""
        await type(repository).objects.filter(id=repository.id).aupdate(
            default_branch="develop",
        )
        mock_proc = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0

        with (
            patch(
                "services.indexer.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ) as mock_create_subprocess,
            patch("services.indexer.qdrant_get_stored_file_hashes", return_value={}),
            patch(
                "services.indexer.IndexerService.run_full_index",
                new_callable=AsyncMock,
                return_value={"status": "success"},
            ),
        ):
            from services.indexer import clone_and_index_repository

            await clone_and_index_repository(str(repository.id))

        first_call_args = mock_create_subprocess.call_args_list[0].args
        assert first_call_args[:5] == (
            "git",
            "clone",
            "--depth",
            "1",
            "--progress",
        )
        assert "--branch" in first_call_args
        assert "develop" in first_call_args

    async def test_git_clone_timeout_uses_wait_for(self, repository):
        """超时通过 asyncio.wait_for 实现（TimeoutError 时 kill 进程）"""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.kill = MagicMock()

        with (
            patch(
                "services.indexer.asyncio.create_subprocess_exec",
                return_value=mock_proc,
            ),
            patch("services.indexer.asyncio.wait_for", side_effect=asyncio.TimeoutError()),
        ):
            from services.indexer import clone_and_index_repository

            result = await clone_and_index_repository(str(repository.id))
            assert result["status"] == "error"
            assert "timed out" in result["message"].lower() or "timeout" in result["message"].lower()


# ============================================================================
# 后台 indexing 任务必须脱离请求 event loop
# ============================================================================


class TestBackgroundRunnerIntegration:
    """验证 _schedule_index 把索引任务投递到 durable 队列（Phase 61 迁移后契约）。

    历史问题（2026-05-12）：原实现 `asyncio.create_task(...)` 把任务绑死在 ASGI
    请求 event loop，HTTP 响应一返回 asgiref CurrentThreadExecutor 关闭 → 后台
    task 后续 ORM `sync_to_async` 全炸。Phase 61 把入队迁移到 `DurableTaskService`：
    `_schedule_index` 不再返回 `concurrent.futures.Future`，改返回 durable job id
    字符串，并经 `DurableTaskService.defer("durable_index", ..., queue=QUEUE_INDEX,
    idempotency_key="index:{repo_id}")` 投递（worker-loop 隔离语义下沉到 durable
    in-process 后端层，另由 `test_background_runner_does_not_inherit_request_executor_context`
    守护）。
    """

    async def test_schedule_index_defers_durable_index(self):
        """_schedule_index 投递 durable_index 任务并返回 durable job id（不再返回 Future）。"""
        from unittest.mock import AsyncMock

        from asgiref.sync import sync_to_async

        from durable import QUEUE_INDEX
        from repositories.index_views import _schedule_index

        with patch(
            "durable.service.DurableTaskService.defer",
            new_callable=AsyncMock,
            return_value="index:fake-repo-id",
        ) as mock_defer:
            # _schedule_index 是同步 helper（内部 async_to_sync(defer)），调用方
            # 经 sync_to_async 在工作线程执行，避免在事件循环线程上裸 async_to_sync
            # 抛 RuntimeError（沿用生产 IndexTriggerView.post 范式）。
            job_id = await sync_to_async(_schedule_index)("fake-repo-id", "fake-history-id")

        assert job_id == "index:fake-repo-id"
        mock_defer.assert_awaited_once()
        args, kwargs = mock_defer.call_args
        assert args[0] == "durable_index"
        payload = args[1]
        assert payload["repository_id"] == "fake-repo-id"
        assert payload["history_id"] == "fake-history-id"
        assert kwargs["queue"] == QUEUE_INDEX
        assert kwargs["idempotency_key"] == "index:fake-repo-id"

    async def test_schedule_index_forwards_branch_and_trigger(self):
        """_schedule_index 把 branch / trigger 透传进 durable payload（缺省 branch=None、trigger=manual）。"""
        from unittest.mock import AsyncMock

        from asgiref.sync import sync_to_async

        from repositories.index_views import _schedule_index

        with patch(
            "durable.service.DurableTaskService.defer",
            new_callable=AsyncMock,
            return_value="index:repo-x",
        ) as mock_defer:
            await sync_to_async(_schedule_index)("repo-1", "hist-1")
            await sync_to_async(_schedule_index)(
                "repo-2", "hist-2", branch="feature/x", trigger="webhook"
            )

        first_payload = mock_defer.call_args_list[0].args[1]
        assert first_payload["branch"] is None
        assert first_payload["trigger"] == "manual"

        second_call = mock_defer.call_args_list[1]
        second_payload = second_call.args[1]
        assert second_payload["branch"] == "feature/x"
        assert second_payload["trigger"] == "webhook"
        assert second_call.kwargs["idempotency_key"] == "index:repo-2"

    async def test_background_runner_does_not_inherit_request_executor_context(self):
        """后台 task 不应继承请求上下文里已关闭的 CurrentThreadExecutor。"""
        from concurrent.futures import Future

        from asgiref.current_thread_executor import CurrentThreadExecutor
        from asgiref.sync import AsyncToSync, sync_to_async

        from services.background_runner import run_in_background

        broken_executor = CurrentThreadExecutor(None)
        done: Future[None] = Future()
        done.set_result(None)
        broken_executor.run_until_future(done)

        old_executor = getattr(AsyncToSync.executors, "current", None)
        AsyncToSync.executors.current = broken_executor
        try:
            future = run_in_background(
                lambda: sync_to_async(lambda: "ok")(),
                name="context-leak-regression",
            )
        finally:
            if old_executor is None:
                del AsyncToSync.executors.current
            else:
                AsyncToSync.executors.current = old_executor

        result = await asyncio.get_event_loop().run_in_executor(
            None, future.result, 5.0,
        )

        assert result == "ok"

    async def test_named_background_task_can_be_cancelled(self):
        """按名称取消后台 task，供停止索引接口使用。"""
        from services.background_runner import cancel_background_task, run_in_background

        started = asyncio.Event()

        async def wait_forever():
            started.set()
            await asyncio.Event().wait()

        future = run_in_background(wait_forever, name="cancel-index-test")
        await asyncio.wait_for(started.wait(), timeout=5.0)

        assert cancel_background_task("cancel-index-test") is True
        assert future.cancelled()

    async def test_cancel_unknown_background_task_returns_false(self):
        """取消不存在的 task 返回 False，接口可据此区分是否已有可取消任务。"""
        from services.background_runner import cancel_background_task

        assert cancel_background_task("missing-index-task") is False


# ============================================================================
# select_for_update(skip_locked=True) 并发保护
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

        result = await _acquire_index_lock_async(str(uuid.uuid4()))
        assert result is None

    async def test_index_trigger_creates_index_history(self, repository, admin_user):
        """IndexTriggerView.post 触发时创建 IndexHistory 记录（durable defer 已 mock）。

        索引触发受 #11 仓库管理守卫（仅空间管理员/超管）保护，故用 DRF
        ``force_authenticate`` 注入超管身份 —— 直接给 WSGIRequest 挂 MagicMock 无效，
        DRF ``Request.user`` 会重新走认证链而落到 AnonymousUser。
        """
        from repositories.index_views import IndexTriggerView

        with (
            # 入队迁移到 durable：patch defer seam 而非旧 clone_and_index_repository，
            # 避免触发真实 clone，并验证 view 仍创建 RUNNING IndexHistory 并返回 202。
            patch(
                "durable.service.DurableTaskService.defer",
                new_callable=AsyncMock,
                return_value="index:fake-job",
            ),
            patch("repositories.index_views._acquire_index_lock_async", return_value=repository),
        ):
            from rest_framework.parsers import JSONParser
            from rest_framework.request import Request
            from rest_framework.test import APIRequestFactory, force_authenticate

            factory = APIRequestFactory()
            wsgi_request = factory.post(f"/api/repositories/{repository.id}/index/", format="json")
            force_authenticate(wsgi_request, user=admin_user)
            request = Request(wsgi_request, parsers=[JSONParser()])

            view = IndexTriggerView()
            response = await view.post(request, repository.id)

            assert response.status_code == 202
            assert "history_id" in response.data

            history = await IndexHistory.objects.aget(id=response.data["history_id"])
            assert history.trigger_type == TriggerType.MANUAL
            assert history.status == IndexHistoryStatus.RUNNING


class TestIndexCancelView:
    """验证停止索引接口把运行中状态落为已停止。"""

    async def test_cancel_running_index_updates_repository_and_history(
        self, repository, admin_user
    ):
        from django.utils import timezone
        from rest_framework.parsers import JSONParser
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory, force_authenticate

        from repositories.index_views import IndexCancelView

        await type(repository).objects.filter(id=repository.id).aupdate(
            index_status=IndexStatus.INDEXING,
            index_error=None,
        )
        history = await IndexHistory.objects.acreate(
            repository=repository,
            trigger_type=TriggerType.MANUAL,
            status=IndexHistoryStatus.RUNNING,
            started_at=timezone.now(),
        )

        factory = APIRequestFactory()
        wsgi_request = factory.post(
            f"/api/repositories/{repository.id}/index/cancel/",
            format="json",
        )
        # 停止索引同受 #11 仓库管理守卫，需真实认证身份（见 trigger 用例说明）
        force_authenticate(wsgi_request, user=admin_user)
        request = Request(wsgi_request, parsers=[JSONParser()])

        with patch("repositories.index_views.cancel_background_task", return_value=True):
            response = await IndexCancelView().post(request, repository.id)

        assert response.status_code == 200
        await repository.arefresh_from_db()
        await history.arefresh_from_db()
        assert repository.index_status == IndexStatus.CANCELLED
        assert repository.index_error == "用户已停止索引"
        assert history.status == IndexHistoryStatus.CANCELLED
        assert history.error_message == "用户已停止索引"
        assert history.finished_at is not None


class TestRepositoryDefaultBranchUpdate:
    """默认分支变更后应滚动更新索引并重置新鲜度。"""

    async def test_default_branch_change_schedules_rolling_index_and_resets_freshness(
        self,
        repository,
    ):
        from django.utils import timezone

        from repositories.serializers import RepositorySerializer
        from repositories.views import RepositoryViewSet

        await type(repository).objects.filter(id=repository.id).aupdate(
            default_branch="main",
            index_status=IndexStatus.INDEXED,
            last_indexed_commit_sha="oldsha",
            remote_head_sha="oldremote",
            remote_head_checked_at=timezone.now(),
            behind_commits=2,
            behind_commits_calculated_at=timezone.now(),
        )
        await RepositoryBranchIndex.objects.acreate(
            repository=repository,
            branch_name="feature/demo",
            is_base_branch=False,
            is_stale=False,
        )
        await repository.arefresh_from_db()

        serializer = RepositorySerializer(
            repository,
            data={"default_branch": "develop"},
            partial=True,
        )
        assert serializer.is_valid(), serializer.errors

        # 默认分支变更后的滚动索引经 durable defer 入队（Phase 61 迁移）：
        # patch defer seam 并断言被调用，而非旧 services.background_runner.run_in_background。
        with patch(
            "durable.service.DurableTaskService.defer",
            new_callable=AsyncMock,
            return_value="index:fake-job",
        ) as mock_defer:
            await RepositoryViewSet().perform_aupdate(serializer)

        await repository.arefresh_from_db()
        history = await IndexHistory.objects.aget(repository=repository)
        branch_index = await RepositoryBranchIndex.objects.aget(repository=repository)

        assert repository.default_branch == "develop"
        assert repository.index_status == IndexStatus.INDEXING
        assert repository.index_error is None
        assert repository.index_stage == "默认分支已变更，准备更新索引..."
        assert repository.last_indexed_commit_sha == "oldsha"
        assert repository.remote_head_sha == ""
        assert repository.remote_head_checked_at is None
        assert repository.behind_commits is None
        assert repository.behind_commits_calculated_at is None
        assert history.status == IndexHistoryStatus.RUNNING
        assert history.from_sha == "oldsha"
        assert branch_index.is_stale is True
        mock_defer.assert_awaited_once()
        assert mock_defer.call_args.args[0] == "durable_index"
        assert mock_defer.call_args.kwargs["idempotency_key"] == f"index:{repository.id}"


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
            started_at=timezone.now(),
        )

        mock_proc = AsyncMock()
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

        await history.arefresh_from_db()
        assert history.status == IndexHistoryStatus.COMPLETED
        assert history.finished_at is not None

    async def test_failed_index_updates_history_to_failed(self, repository):
        """索引失败后 IndexHistory 状态更新为 FAILED 并记录错误信息"""
        from django.utils import timezone

        history = await IndexHistory.objects.acreate(
            repository=repository,
            trigger_type=TriggerType.MANUAL,
            status=IndexHistoryStatus.RUNNING,
            started_at=timezone.now(),
        )

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"clone error"))
        mock_proc.returncode = 1

        with (
            patch("services.indexer.asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("services.indexer.asyncio.wait_for", return_value=(b"", b"clone error")),
        ):
            from services.indexer import clone_and_index_repository

            _result = await clone_and_index_repository(str(repository.id), history_id=str(history.id))

        await history.arefresh_from_db()
        assert history.status == IndexHistoryStatus.FAILED
        assert history.finished_at is not None
        assert history.error_message is not None

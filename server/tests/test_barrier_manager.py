"""BarrierManager 单元测试 — all_of 汇聚逻辑。
纯 asyncio 测试，不依赖 Django ORM。
_persist_progress 通过 mock 跳过 DB 操作。
"""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock
import pytest
from orchestration.barrier import BarrierManager, get_barrier_manager
from orchestration.contracts import BlockingTaskRequest, BlockingTaskResult
@pytest.fixture
def manager -> BarrierManager:
 mgr = BarrierManager
 mgr._persist_progress = AsyncMock # type: ignore[assignment]
 return mgr
@pytest.fixture
def on_complete -> AsyncMock:
 return AsyncMock
def _make_request(task_id: str, task_type: str = "deep_analysis") -> BlockingTaskRequest:
 return {"task_type": task_type, "task_id": task_id, "params": {}}
def _make_result(
 task_id: str, *, success: bool = True, output: str = "ok", error: str = ""
) -> BlockingTaskResult:
 return {
 "task_id": task_id,
 "task_type": "deep_analysis",
 "success": success,
 "output": output,
 "error": error,
 }
# ── Test 1: register + 单个任务完成 → barrier 满足 ──
@pytest.mark.asyncio
async def test_single_task_completes_satisfies_barrier(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 tasks = [_make_request("t1")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 satisfied = await manager.task_completed("t1", _make_result("t1"))
 assert satisfied is True
 on_complete.assert_awaited_once
 results = on_complete.call_args[0][0]
 assert len(results) == 1
 assert results[0]["task_id"] == "t1"
 assert results[0]["success"] is True
# ── Test 2: 2 个任务 + 第一个完成 → barrier 未满足 ──
@pytest.mark.asyncio
async def test_first_of_two_does_not_satisfy(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 satisfied = await manager.task_completed("t1", _make_result("t1"))
 assert satisfied is False
 on_complete.assert_not_awaited
# ── Test 3: 2 个任务 + 都完成 → barrier 满足 ──
@pytest.mark.asyncio
async def test_all_tasks_complete_satisfies_barrier(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 await manager.task_completed("t1", _make_result("t1"))
 satisfied = await manager.task_completed("t2", _make_result("t2"))
 assert satisfied is True
 on_complete.assert_awaited_once
 results = on_complete.call_args[0][0]
 assert len(results) == 2
# ── Test 4: 任务失败 → 仍等待其余 ──
@pytest.mark.asyncio
async def test_failed_task_waits_for_remaining(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 result_fail = _make_result("t1", success=False, output="", error="task error")
 satisfied = await manager.task_completed("t1", result_fail)
 assert satisfied is False
 on_complete.assert_not_awaited
 satisfied = await manager.task_completed("t2", _make_result("t2"))
 assert satisfied is True
 on_complete.assert_awaited_once
 results = on_complete.call_args[0][0]
 failed = [r for r in results if r["task_id"] == "t1"]
 assert failed[0]["success"] is False
 assert failed[0]["error"] == "task error"
# ── Test 5: 全局安全超时 → 未完成标记 timed_out ──
@pytest.mark.asyncio
async def test_global_timeout_marks_pending_timed_out(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register(
 "run-1", "thread-1", tasks, {}, on_complete, timeout_seconds=0.1
 )
 await manager.task_completed("t1", _make_result("t1"))
 # t2 未完成，等超时触发
 await asyncio.sleep(0.3)
 on_complete.assert_awaited_once
 results = on_complete.call_args[0][0]
 timed_out = [r for r in results if r["task_id"] == "t2"]
 assert len(timed_out) == 1
 assert timed_out[0]["success"] is False
 assert "timeout" in timed_out[0]["error"].lower
# ── Test 6: cancel_all → 未完成标记 cancelled ──
@pytest.mark.asyncio
async def test_cancel_all_marks_pending_cancelled(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 await manager.task_completed("t1", _make_result("t1"))
 await manager.cancel_all("run-1")
 on_complete.assert_awaited_once
 results = on_complete.call_args[0][0]
 cancelled = [r for r in results if r["task_id"] == "t2"]
 assert len(cancelled) == 1
 assert cancelled[0]["success"] is False
 assert "取消" in cancelled[0]["error"] or "cancel" in cancelled[0]["error"].lower
# ── Test 7: 并发回调 → on_complete 只调用一次 ──
@pytest.mark.asyncio
async def test_concurrent_callbacks_fire_once(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 await asyncio.gather(
 manager.task_completed("t1", _make_result("t1")),
 manager.task_completed("t2", _make_result("t2")),
 )
 on_complete.assert_awaited_once
# ── Test 8: 未注册 task_id → 无错误，返回 False ──
@pytest.mark.asyncio
async def test_unknown_task_id_returns_false(manager: BarrierManager) -> None:
 satisfied = await manager.task_completed("unknown", _make_result("unknown"))
 assert satisfied is False
# ── 补充: has_barrier_for_thread ──
@pytest.mark.asyncio
async def test_has_barrier_for_thread(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 assert manager.has_barrier_for_thread("thread-1") is False
 tasks = [_make_request("t1")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 assert manager.has_barrier_for_thread("thread-1") is True
 await manager.task_completed("t1", _make_result("t1"))
 assert manager.has_barrier_for_thread("thread-1") is False
# ── 补充: get_pending_tasks ──
@pytest.mark.asyncio
async def test_get_pending_tasks(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 tasks = [_make_request("t1"), _make_request("t2"), _make_request("t3")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 pending = manager.get_pending_tasks("run-1")
 assert len(pending) == 3
 await manager.task_completed("t1", _make_result("t1"))
 pending = manager.get_pending_tasks("run-1")
 assert len(pending) == 2
 assert all(p["task_id"] != "t1" for p in pending)
# ── 补充: get_barrier_manager 单例 ──
def test_get_barrier_manager_singleton -> None:
 import orchestration.barrier as mod
 mod._barrier_manager = None
 m1 = get_barrier_manager
 m2 = get_barrier_manager
 assert m1 is m2
 mod._barrier_manager = None # cleanup
# ── 进度持久化测试 ──
@pytest.mark.asyncio
async def test_task_completed_persists_progress(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 """task_completed 每次记录结果后调用 _persist_progress。"""
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 await manager.task_completed("t1", _make_result("t1"))
 manager._persist_progress.assert_awaited # type: ignore[union-attr]
 call_args = manager._persist_progress.call_args # type: ignore[union-attr]
 assert call_args[0] == ("run-1", 1, 2)
@pytest.mark.asyncio
async def test_task_completed_final_persists_full_progress(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 """全部完成时进度持久化为 completed == total。"""
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register("run-1", "thread-1", tasks, {}, on_complete)
 await manager.task_completed("t1", _make_result("t1"))
 await manager.task_completed("t2", _make_result("t2"))
 calls = manager._persist_progress.call_args_list # type: ignore[union-attr]
 assert len(calls) == 2
 assert calls[0][0] == ("run-1", 1, 2)
 assert calls[1][0] == ("run-1", 2, 2)
@pytest.mark.asyncio
async def test_on_complete_exception_does_not_crash(manager: BarrierManager) -> None:
 """on_complete 抛异常时 task_completed 不应传播异常。"""
 failing_callback = AsyncMock(side_effect=RuntimeError("callback boom"))
 tasks = [_make_request("t1")]
 await manager.register("run-1", "thread-1", tasks, {}, failing_callback)
 satisfied = await manager.task_completed("t1", _make_result("t1"))
 assert satisfied is True
 failing_callback.assert_awaited_once
# ── TASK_PROGRESS 事件契约 + 增量回调测试 ──
@pytest.mark.asyncio
async def test_task_progress_event_emitted -> None:
 """TASK_PROGRESS 事件 data 格式与前端 SSEEvent 接口一致。"""
 from agents.core.events import TASK_PROGRESS
 event = {
 "type": TASK_PROGRESS,
 "data": {"completed_count": 0, "total_count": 3},
 }
 assert event["type"] == "task_progress"
 data = event["data"]
 assert "completed_count" in data
 assert "total_count" in data
 assert isinstance(data["completed_count"], int)
 assert isinstance(data["total_count"], int)
@pytest.mark.asyncio
async def test_barrier_incremental_progress_callback(
 manager: BarrierManager, on_complete: AsyncMock
) -> None:
 """task_completed 在每个任务完成后通过 on_progress 回调发射增量进度。"""
 on_progress = AsyncMock
 tasks = [_make_request("t1"), _make_request("t2")]
 await manager.register(
 "run-1", "thread-1", tasks, {}, on_complete, on_progress=on_progress,
 )
 await manager.task_completed("t1", _make_result("t1"))
 on_progress.assert_awaited_once_with(1, 2)
 await manager.task_completed("t2", _make_result("t2"))
 assert on_progress.await_count == 2
 on_progress.assert_awaited_with(2, 2)
@pytest.mark.asyncio
async def test_cancel_all_on_complete_exception_does_not_crash(
 manager: BarrierManager,
) -> None:
 """cancel_all 中 on_complete 抛异常时不应传播异常。"""
 failing_callback = AsyncMock(side_effect=RuntimeError("cancel callback boom"))
 mgr = BarrierManager
 mgr._persist_progress = AsyncMock # type: ignore[assignment]
 tasks = [_make_request("t1")]
 await mgr.register("run-1", "thread-1", tasks, {}, failing_callback)
 await mgr.cancel_all("run-1")
 failing_callback.assert_awaited_once

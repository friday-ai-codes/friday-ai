"""Phase Plan：IndexHistory lifecycle wrapper（不修改 tasks.py / payload_sync.py）。
为 Phase `enqueue_edge_build` 加一层**外部** lifecycle 埋点，
把 IndexHistory.graph_build_status / edge_count / payload_synced_at 三字段
（Plan 落地）接入 reconcile 链路：
- 调度前：`graph_build_status = RUNNING`
- 调度完（成功）：`graph_build_status = COMPLETED` + edge_count（累计快照口径，
 per CONTEXT ）+ payload_synced_at = now
- 调度完（失败 / cancelled）：`graph_build_status = FAILED`，payload_synced_at 保 None
- 空 dirty：`graph_build_status = SKIPPED`，不调 enqueue（避免 tasks.py 内部
 "skip_empty_dirty" log 路径与 IndexHistory 状态语义不一致）
**关键约束**（per Plan frontmatter）：本模块仅消费 `enqueue_edge_build` 公共 API，
**tasks.py / payload_sync.py 在本 plan 末态 git diff 必须为 0**。
**完成回调实现**（per Plan deviations）：
1. wrapper 先 `await _mark_running(history_id)`
2. 调 `enqueue_edge_build(repo_id, dirty)`（Phase 公共 API，零修改）
3. 从 `code_relations.tasks._BACKGROUND_TASKS` 取出新增的 Task（spawned-after diff
 判断）。访问私有符号是技术债（T- mitigate），但只读不写风险可控；若
 Phase 改 `_BACKGROUND_TASKS` 字段名，单测 import 会立刻失败，问题可见。
4. `task.add_done_callback(...)` 注册同步回调，内部 `asyncio.create_task` 开新
 协程跑 `_handle_completion` 写回 IndexHistory（done_callback 本身是同步上下文，
 无法直接 `await`）。
**异常隔离**（per CONTEXT / threat T- mitigate）：所有 IndexHistory
更新失败 catch + structlog warning + 不重抛——reconcile 链路应永远可见，单点
ORM 故障不允许把 indexer 主流程拉下水。
"""
from __future__ import annotations
import asyncio
import uuid
from typing import Any
import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone
from code_relations import tasks as _tasks_module
from code_relations.models import ChunkEdge
__all__ = ["enqueue_edge_build_for_history"]
logger = structlog.get_logger(__name__)
async def _update_history(history_id: uuid.UUID | str, **fields: Any) -> None:
 """更新 IndexHistory 单行；任何异常 catch + warn 不重抛。
 `thread_sensitive=True`（默认）：在 Django 主线程跑 sync ORM 调用，避免
 SQLite 多线程写锁竞争（test_db 单文件锁；prod Postgres 不受影响）。
 """
 from repositories.models import IndexHistory
 try:
 await sync_to_async(IndexHistory.objects.filter(id=history_id).update)(
 **fields
 )
 except Exception as exc:
 logger.warning(
 "lifecycle_index_history_update_failed",
 history_id=str(history_id),
 fields=list(fields.keys),
 error=str(exc),
 error_type=type(exc).__name__,
 )
async def _count_edges_or_none(repository_id: str) -> int | None:
 """累计快照口径，统计失败时返回 None（与"真实为 0"区分，per ）。
 返回 None 时 `_handle_completion` 不写 edge_count（保留模型 default 0），
 并在 log 中 surface "edge_count unavailable"，避免静默把 reconcile 失败
 展示成"真无边"。
 """
 try:
 return await sync_to_async(
 ChunkEdge.objects.filter(repository_id=repository_id).count
 )
 except Exception as exc:
 logger.warning(
 "lifecycle_edge_count_failed",
 repository_id=repository_id,
 error=str(exc),
 error_type=type(exc).__name__,
 )
 return None
async def _handle_completion(
 task: asyncio.Task[Any],
 history_id: uuid.UUID | str,
 repository_id: str,
 remaining: list[int] | None = None,
) -> None:
 """task 完成 → 根据 cancelled/exception 决定 COMPLETED 或 FAILED。
 `remaining` 是共享计数器（list 包 int 模拟可变 ref，per fix）：
 多 task spawn 时只有最后一个 done_callback 才写 COMPLETED；任一 task
 cancelled / exception 时立即写 FAILED 并把计数器归零（避免后续 task
 再覆盖）。单 task 场景（remaining 长度 1）等价于旧行为。
 """
 from repositories.models import GraphBuildStatus
 try:
 if task.cancelled:
 logger.warning(
 "lifecycle_task_cancelled",
 history_id=str(history_id),
 repository_id=repository_id,
 )
 if remaining is not None:
 remaining[0] = 0
 await _update_history(
 history_id, graph_build_status=GraphBuildStatus.FAILED
 )
 return
 exc = task.exception
 if exc is not None:
 logger.warning(
 "lifecycle_task_failed",
 history_id=str(history_id),
 repository_id=repository_id,
 error=str(exc),
 error_type=type(exc).__name__,
 )
 if remaining is not None:
 remaining[0] = 0
 await _update_history(
 history_id, graph_build_status=GraphBuildStatus.FAILED
 )
 return
 if remaining is not None:
 remaining[0] -= 1
 if remaining[0] > 0:
 logger.debug(
 "lifecycle_task_completed_pending_others",
 history_id=str(history_id),
 repository_id=repository_id,
 remaining=remaining[0],
 )
 return
 edge_count = await _count_edges_or_none(repository_id)
 update_fields: dict[str, Any] = {
 "graph_build_status": GraphBuildStatus.COMPLETED,
 "payload_synced_at": timezone.now,
 }
 if edge_count is not None:
 update_fields["edge_count"] = edge_count
 await _update_history(history_id, **update_fields)
 logger.info(
 "lifecycle_task_completed",
 history_id=str(history_id),
 repository_id=repository_id,
 edge_count=edge_count,
 )
 except Exception as exc:
 logger.exception(
 "lifecycle_handle_completion_unhandled",
 history_id=str(history_id),
 repository_id=repository_id,
 error=str(exc),
 error_type=type(exc).__name__,
 )
def _schedule_completion_callback(
 task: asyncio.Task[Any],
 history_id: uuid.UUID | str,
 repository_id: str,
 remaining: list[int] | None = None,
) -> None:
 """task done_callback：同步上下文 + 创建新协程跑 ORM 回写。
 done_callback 本身在 task 所在 event loop 调用；用 `asyncio.create_task`
 把 `_handle_completion` 投递到同一 loop 异步执行。
 ** race-fix**：把新建的 completion task 也注册到 `_BACKGROUND_TASKS`，
 便于测试侧 `_drain_background_tasks` 循环 await 至空 —— 否则 builder task
 完成后 done_callback 派生的 ORM 回写 task 没法被 deterministic 等待，
 造成 `test_completion_marks_completed_with_edge_count` 套件运行时 race fail。
 生产路径同样受益：mgmt 命令 / verify 等显式 drain 时不再漏掉 completion task。
 """
 try:
 loop = asyncio.get_running_loop
 completion_task = loop.create_task(
 _handle_completion(task, history_id, repository_id, remaining)
 )
 _tasks_module._BACKGROUND_TASKS.add(completion_task)
 completion_task.add_done_callback(_tasks_module._BACKGROUND_TASKS.discard)
 except RuntimeError as exc:
 logger.warning(
 "lifecycle_callback_no_running_loop",
 history_id=str(history_id),
 repository_id=repository_id,
 error=str(exc),
 )
 except Exception as exc:
 logger.warning(
 "lifecycle_schedule_completion_failed",
 history_id=str(history_id),
 repository_id=repository_id,
 error=str(exc),
 error_type=type(exc).__name__,
 )
async def enqueue_edge_build_for_history(
 repository_id: str,
 dirty_chunk_ids: list[uuid.UUID],
 history_id: uuid.UUID | str | None,
) -> None:
 """`enqueue_edge_build` lifecycle wrapper：埋点 IndexHistory 状态机。
 Args:
 repository_id: 仓库 UUID 字符串
 dirty_chunk_ids: 本次 indexer 写入/更新的 chunk_id 列表
 history_id: 关联的 IndexHistory 行 ID；None 时跳过 lifecycle 更新，
 直接透传到 `enqueue_edge_build`（保兼容无 history 调用方）
 异常隔离（per CONTEXT ）：函数体顶层 try/except 包裹，任何失败仅 log
 warning，不重抛——indexer 主流程不会被 reconcile 异常拉下水。
 """
 from repositories.models import GraphBuildStatus
 try:
 if not dirty_chunk_ids:
 if history_id is not None:
 await _update_history(
 history_id, graph_build_status=GraphBuildStatus.SKIPPED
 )
 logger.debug(
 "lifecycle_skip_empty_dirty",
 repository_id=repository_id,
 history_id=str(history_id) if history_id else None,
 )
 return
 if history_id is not None:
 await _update_history(
 history_id, graph_build_status=GraphBuildStatus.RUNNING
 )
 # `_BACKGROUND_TASKS` before/after diff（per Plan frontmatter T-）：
 # 依赖 `enqueue_edge_build` 函数体内**无任何 `await`** 的隐式契约
 # （ / `tasks.py` line 86 同步 `asyncio.create_task`）。一旦
 # `enqueue_edge_build` 被改为先 await DB 查询再 spawn task，单线程 asyncio
 # 在该 await 点会让出控制权，并发 lifecycle 调用会把别人 spawn 的 task
 # 误归到自己 `new_tasks`。`test_enqueue_edge_build_no_await_in_body`
 # 单测固化此契约（inspect.getsource regex 检查），改动会立刻测试失败。
 before_tasks = set(_tasks_module._BACKGROUND_TASKS)
 await _tasks_module.enqueue_edge_build(repository_id, dirty_chunk_ids)
 if history_id is None:
 return
 new_tasks = _tasks_module._BACKGROUND_TASKS - before_tasks
 if not new_tasks:
 #：`enqueue_edge_build` 因合法分支（dedup / circuit breaker / 空
 # dirty）未 spawn task —— 不应误判为 FAILED。lifecycle 上层已在
 # line ~189 处理空 dirty_chunk_ids 走 SKIPPED，此处 fallthrough 仅
 # warn + 保 RUNNING，等 verify_payload_consistency 兜底校验。
 logger.warning(
 "lifecycle_no_background_task_spawned",
 repository_id=repository_id,
 history_id=str(history_id),
 dirty_chunks=len(dirty_chunk_ids),
 )
 return
 # fix：`max(new_tasks, key=id)` 用 CPython 内存地址判"最新"是错的
 # —— `id` 与 task 创建顺序无关。改成给所有 new_tasks 都注册 done_callback，
 # 用共享 `remaining` 计数器让"最后一个完成的 task"才写 COMPLETED；
 # 任一 task cancelled / exception 时立即把状态机跳到 FAILED 并把计数器
 # 归零，避免后续 task 再覆盖。单 task 场景（当前 `enqueue_edge_build`
 # 唯一 spawn 形态）等价于旧行为。
 remaining: list[int] = [len(new_tasks)]
 captured_history_id = history_id
 def _make_callback(
 rem: list[int],
 ) -> Any:
 def _cb(t: asyncio.Task[Any]) -> None:
 _schedule_completion_callback(
 t, captured_history_id, repository_id, rem
 )
 return _cb
 for new_task in new_tasks:
 new_task.add_done_callback(_make_callback(remaining))
 logger.info(
 "lifecycle_dispatch_with_history",
 repository_id=repository_id,
 history_id=str(history_id),
 dirty_chunks=len(dirty_chunk_ids),
 spawned_tasks=len(new_tasks),
 )
 except Exception as exc:
 logger.exception(
 "lifecycle_enqueue_unhandled",
 repository_id=repository_id,
 history_id=str(history_id) if history_id else None,
 error=str(exc),
 error_type=type(exc).__name__,
 )
 if history_id is not None:
 try:
 await _update_history(
 history_id, graph_build_status=GraphBuildStatus.FAILED
 )
 except Exception:
 pass

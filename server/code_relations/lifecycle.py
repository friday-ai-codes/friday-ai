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
 """更新 IndexHistory 单行；任何异常 catch + warn 不重抛。"""
 from repositories.models import IndexHistory
 try:
 await sync_to_async(
 IndexHistory.objects.filter(id=history_id).update,
 thread_sensitive=False,
 )(**fields)
 except Exception as exc:
 logger.warning(
 "lifecycle_index_history_update_failed",
 history_id=str(history_id),
 fields=list(fields.keys),
 error=str(exc),
 error_type=type(exc).__name__,
 )
async def _count_edges(repository_id: str) -> int:
 """累计快照口径：当前 ChunkEdge.objects.filter(repository_id=repo).count。"""
 try:
 return await sync_to_async(
 ChunkEdge.objects.filter(repository_id=repository_id).count,
 thread_sensitive=False,
 )
 except Exception as exc:
 logger.warning(
 "lifecycle_edge_count_failed",
 repository_id=repository_id,
 error=str(exc),
 error_type=type(exc).__name__,
 )
 return 0
async def _handle_completion(
 task: asyncio.Task[Any],
 history_id: uuid.UUID | str,
 repository_id: str,
) -> None:
 """task 完成 → 根据 cancelled/exception 决定 COMPLETED 或 FAILED。"""
 from repositories.models import GraphBuildStatus
 try:
 if task.cancelled:
 logger.warning(
 "lifecycle_task_cancelled",
 history_id=str(history_id),
 repository_id=repository_id,
 )
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
 await _update_history(
 history_id, graph_build_status=GraphBuildStatus.FAILED
 )
 return
 edge_count = await _count_edges(repository_id)
 await _update_history(
 history_id,
 graph_build_status=GraphBuildStatus.COMPLETED,
 edge_count=edge_count,
 payload_synced_at=timezone.now,
 )
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
) -> None:
 """task done_callback：同步上下文 + 创建新协程跑 ORM 回写。
 done_callback 本身在 task 所在 event loop 调用；用 `asyncio.create_task`
 把 `_handle_completion` 投递到同一 loop 异步执行。新 task 不再纳入
 `_BACKGROUND_TASKS`（lifecycle 侧自行 await `_handle_completion` 失败已
 log warning，主路径不依赖其结果）。
 """
 try:
 loop = asyncio.get_event_loop
 loop.create_task(_handle_completion(task, history_id, repository_id))
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
 before_tasks = set(_tasks_module._BACKGROUND_TASKS)
 await _tasks_module.enqueue_edge_build(repository_id, dirty_chunk_ids)
 if history_id is None:
 return
 new_tasks = _tasks_module._BACKGROUND_TASKS - before_tasks
 if not new_tasks:
 logger.warning(
 "lifecycle_no_background_task_spawned",
 repository_id=repository_id,
 history_id=str(history_id),
 dirty_chunks=len(dirty_chunk_ids),
 )
 await _update_history(
 history_id, graph_build_status=GraphBuildStatus.FAILED
 )
 return
 target_task = max(new_tasks, key=id)
 target_task.add_done_callback(
 lambda t: _schedule_completion_callback(t, history_id, repository_id)
 )
 logger.info(
 "lifecycle_dispatch_with_history",
 repository_id=repository_id,
 history_id=str(history_id),
 dirty_chunks=len(dirty_chunk_ids),
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

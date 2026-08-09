"""implementation EdgeBuilder 协调器（per contract / contract / contract / contract）。

**contract 实现路径决策（Claude's Discretion）：**

context contract 原文要求「APScheduler date trigger」异步触发，但 indexer 与
scheduler 跨进程（`runapscheduler` 是独立 mgmt command；indexer 跑在
`background_runner` 进程内），cross-process IPC 复杂度高（DjangoJobStore push
job 跨进程边界事务一致性需额外设计）。

本模块改采 `asyncio.create_task` **同进程 fire-and-forget**：
1. indexer 已在 async 上下文，`create_task` 是最自然的非阻塞模式
2. builders 与 indexer 同进程跑，零 IPC 开销
3. 所有错误 catch 内部 + structlog log + 不抛回 indexer（与 contract 异常隔离语义
   一致）

未来若需要跨进程调度（多 worker indexer），可在 `enqueue_edge_build` 内部
切换到 `DjangoJobStore.add_job` 而对调用方零破坏。

**协调器执行顺序（_run_all_builders_and_sync_payload）：**

1. 取 Repository（不存在 → log error + return，不抛）
2. `asyncio.gather(*[cls().build(repo, dirty) for cls in BUILDERS],
   return_exceptions=True)`：6 builder 并发；单 fail 不中断其余（per contract）
3. 异常 result log error 跳过；正常 result 的 ChunkEdge flatten
4. `bulk_insert_edges(all_edges)` 单次入库（ignore_conflicts 静默去重 per contract）
5. `aggregate_top_neighbors(...)` 单 SQL 聚合 top-20 邻居（per contract）
6. `QdrantService.batch_set_payload(...)` **恰好一次** sync（per contract / contract，
   不是每 builder 独立 sync）
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async

from code_relations.builders import BUILDERS
from code_relations.payload_sync import aggregate_top_neighbors
from code_relations.storage import bulk_insert_edges
from services.qdrant_service import QdrantService

if TYPE_CHECKING:
    from code_relations.models import ChunkEdge

logger = structlog.get_logger(__name__)

__all__ = ["enqueue_edge_build", "snapshot_background_tasks"]

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
"""work item 修复：保存 `asyncio.create_task` 强引用避免 GC 中途回收（CPython event
loop 对 task 仅持弱引用，IO-wait 期间触发 GC 理论上可 collect）。task 完成后由
`add_done_callback(_BACKGROUND_TASKS.discard)` 自动回收。

外部模块不应直接读 `_BACKGROUND_TASKS`，应通过 `snapshot_background_tasks()`
取浅拷贝快照（per implementation REVIEW work item）。"""


def snapshot_background_tasks() -> set[asyncio.Task[Any]]:
    """返回当前 ``_BACKGROUND_TASKS`` 的浅拷贝快照（per implementation REVIEW work item）。

    替代跨模块直读私有 ``_BACKGROUND_TASKS``。``verify_payload_consistency`` 与
    ``rebuild_chunk_edges`` 命令的 ``_dispatch_and_drain`` before/after diff 模式
    （work item lesson）专用：在 enqueue 前后各取一次快照、计算差集 = 本次
    dispatch 真正 spawn 的 task。

    返回 ``set`` 拷贝而非视图，调用方 mutate 不影响内部状态；内部模块（``tasks``
    本身、``lifecycle``）仍直读 ``_BACKGROUND_TASKS`` 以保 add/discard 原子性。
    """
    return set(_BACKGROUND_TASKS)


async def enqueue_edge_build(
    repository_id: str,
    dirty_chunk_ids: list[uuid.UUID],
    *,
    branch_name: str = "",
) -> None:
    """Fire-and-forget 触发 6 builder 并发构建 + payload 同步。

    立即 return（不等待 builders 完成），由 `asyncio.create_task` 在背景执行
    `_run_all_builders_and_sync_payload`。

    异常隔离（per contract）：所有错误在 `_run_all_builders_and_sync_payload`
    内部 catch + structlog log，不抛回 indexer。

    注：indexer 主任务结束时 `background_runner` 会 cancel 未完成 task；
    实践中 builders 通常远快于 indexer 主流程（semantic builder 10k chunks
    < 60s），不会被 cancel。即便被 cancel，下次 indexer 触发再补（最终一致）。

    Args:
        repository_id: 仓库 UUID 字符串
        dirty_chunk_ids: 本次 indexer 写入或更新的 chunk_id 列表；空 list →
            直接 return 不 spawn task
        branch_name: 写入侧归一化后的分支名（""=base，implementation 透传链）。
            透传给 orchestrator → 6 EdgeBuilder.build；feature 分支据此过滤
            Symbol/ChunkRegistry/ChunkEdge 查询并把 branch_name 打到写入的边上。

    **无 await 后再 spawn task 的隐式契约（work item）：** 本函数体内不得引入任何
    `await`（`lifecycle.py` 的 before/after `_BACKGROUND_TASKS` diff 依赖此契约，
    `test_enqueue_edge_build_no_await_in_body` 守门）。加 `branch_name` 形参不引
    入 await，仅在 `create_task` 闭包透传，安全。
    """
    if not dirty_chunk_ids:
        logger.debug(
            "enqueue_edge_build_skip_empty_dirty",
            repository_id=repository_id,
        )
        return

    task = asyncio.create_task(
        _run_all_builders_and_sync_payload(
            repository_id, dirty_chunk_ids, branch_name=branch_name
        )
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    logger.info(
        "enqueue_edge_build_dispatched",
        repository_id=repository_id,
        dirty_chunks=len(dirty_chunk_ids),
        builders=len(BUILDERS),
    )


async def _run_all_builders_and_sync_payload(
    repository_id: str,
    dirty_chunk_ids: list[uuid.UUID],
    *,
    branch_name: str = "",
) -> int:
    """6 builder 并发跑 + 统一 bulk_insert_edges + 单次 batch_set_payload。

    per contract：6 builder 全部完成后**统一**调一次 `batch_set_payload`，不是
        每 builder 独立 sync。
    per contract：`asyncio.gather(..., return_exceptions=True)` 单 builder fail
        不中断其余；fail builder log error 不抛。
    per contract：`bulk_insert_edges` ignore_conflicts 静默重复边。

    work item 修复：函数顶层包 try/except，兜住 `bulk_insert_edges` /
    `aggregate_top_neighbors` / `batch_set_payload` 的所有未捕获异常（fire-and-
    forget task 不会被 await，未 catch 异常会被静默吞噬）。

    成功路径 `return inserted`（`bulk_insert_edges`
    ignore_conflicts 去重后的本次真实新增数，per-run delta 语义），异常/早退
    路径 `return 0`。lifecycle `_handle_completion` 经 `task.result()` 读取此值
    回写 IndexHistory.chunk_edges_added（区别于全表累计 edge_count，Pitfall 7）。
    本改动不引入新 await，不破 `test_enqueue_edge_build_no_await_in_body` 契约
    （该测试只校验 `enqueue_edge_build` 函数体，不约束本 orchestrator）。

    Returns:
        int: 本次 bulk_insert_edges 去重后真实新增的 ChunkEdge 数；repo 不存在、
            获取失败或顶层异常时返回 0。
    """
    from repositories.models import Repository

    try:
        try:
            repo = await sync_to_async(Repository.objects.get)(id=repository_id)
        except Repository.DoesNotExist:
            logger.error(
                "edge_build_repo_not_found",
                repository_id=repository_id,
            )
            return 0
        except Exception as exc:
            logger.error(
                "edge_build_repo_fetch_failed",
                repository_id=repository_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return 0

        builders = [cls() for cls in BUILDERS]
        results: list[list[ChunkEdge] | BaseException] = (
            list(
                await asyncio.gather(
                    *[
                        b.build(repo, dirty_chunk_ids, branch_name=branch_name)
                        for b in builders
                    ],
                    return_exceptions=True,
                )
            )
            if builders
            else []
        )

        all_edges: list[ChunkEdge] = []
        for builder, res in zip(builders, results, strict=True):
            if isinstance(res, BaseException):
                logger.error(
                    "edge_builder_failed",
                    repository_id=repository_id,
                    builder=getattr(builder, "edge_type_label", type(builder).__name__),
                    error=str(res),
                    error_type=type(res).__name__,
                )
                continue
            all_edges.extend(res)

        inserted = await bulk_insert_edges(all_edges)
        logger.info(
            "edge_build_inserted",
            repository_id=repository_id,
            total_input=len(all_edges),
            inserted=inserted,
        )

        updates = await aggregate_top_neighbors(repository_id, dirty_chunk_ids)
        await QdrantService.batch_set_payload(repository_id, updates)

        logger.info(
            "edge_build_and_payload_sync_complete",
            repository_id=repository_id,
            dirty_chunks=len(dirty_chunk_ids),
            edges_inserted=inserted,
            payload_updates=len(updates),
        )

        # 边构建完成 → 主动刷新 Galaxy 文件缓存（refresh_repo 内部吞掉所有异常，
        # 失败时下次请求的签名对比仍会自动重建，不影响主流程）。
        if inserted > 0:
            from codegraph.galaxy.cache import GalaxyGraphCache

            # 🚨 必须从**包根**导入：``services.code_graph`` 的 ``__init__.py`` 是 curated
            # barrel，直连包内 ``cache`` 子模块正是它要挡住的架构违规（红线连钩子自己
            # 也不例外，否则那道守护测试形同虚设）。函数内 lazy import 同时避开与
            # ``code_relations`` 的模块级循环依赖。
            from services.code_graph import invalidate_repository

            await sync_to_async(GalaxyGraphCache.refresh_repo)(repository_id)

            # 边构建完成 → 驱逐本 worker 的内存符号图（Phase 121 / GRAPH-01）。
            # ⚠️ 这**只是优化，不是正确性保证**：钩子只对**本 worker** 生效，多 worker
            # 部署下其余进程里的旧图仍然只能靠取图时的**签名**复校发现陈旧——因此
            # ``GraphService._get_graph_sync`` 里那道签名比对**不可删除**。
            # 失效自身的异常在 ``invalidate_repository`` 内部吞掉，不反噬边构建。
            await sync_to_async(invalidate_repository)(repository_id)

            # Phase 125 / D-03：社区重建只 enqueue，⛔ 钩子内不内联 Louvain。
            try:
                from services.community_enqueue import enqueue_community_rebuild

                await enqueue_community_rebuild(
                    str(repository_id),
                    branch_name=branch_name or "",
                )
            except Exception:  # noqa: BLE001 — best-effort，不反噬边构建
                pass

        # 返回本次去重后真实新增数，供 lifecycle 回写 chunk_edges_added。
        return inserted
    except Exception as exc:
        logger.exception(
            "edge_build_orchestrator_unhandled",
            repository_id=repository_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return 0

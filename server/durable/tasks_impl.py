"""durable 业务任务体（与 procrastinate 无关的纯任务实现）。

本模块定义 index / graph / page_index 三个任务体，**对 procrastinate 零直接依赖**：
- procrastinate 路径经 ``durable.tasks`` 的 ``@app.task`` 包壳 import 本模块委托；
- in-process fallback 路径经 ``durable.handlers`` 的 ``**payload`` 展开 adapter
  import 本模块委托。

两后端共用同一任务体，是消除研究 Pitfall 1（双后端入参不一致）的关键：所有任务体
统一用 **keyword-only 形参**对齐 payload 键，调用方一律 ``**payload`` 展开传入，使
procrastinate ``defer_async(**payload)`` 与 in-process ``handler(**payload)`` 入参一致。

service 函数一律在**函数体内局部 import**，保持注册期（@app.task 收集）轻量、零
重依赖加载。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def run_index(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """代码索引任务体：克隆并索引仓库。

    复用既有 ``services.indexer.clone_and_index_repository``，进度 / 结果仍写
    IndexHistory，FileIndex 的 hash checkpoint 逻辑零改动（幂等真值源在 service 内）。
    ``trigger`` 仅承载入队点语义、本任务体不转发（History 已在入队点创建）。
    """
    from services.indexer import clone_and_index_repository

    return await clone_and_index_repository(repository_id, history_id=history_id, branch=branch)


async def run_graph(
    *,
    repository_id: str,
    history_id: str | None = None,
    branch: str | None = None,
    trigger: str = "manual",
) -> Any:
    """代码图谱构建任务体。

    复用既有 ``services.graph_builder.build_graph_for_repository``，结果写
    GraphBuildHistory，GraphFileIndex checkpoint（skip_unchanged）沿用 service 默认
    行为、本任务体不传 ``skip_unchanged``。
    """
    from services.graph_builder import build_graph_for_repository

    return await build_graph_for_repository(
        repository_id, trigger=trigger, history_id=history_id, branch=branch
    )


async def run_page_index(*, target_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """页面级索引占位任务体（Phase 62 接入实际 ingest）。

    当前仅记一条 debug 后返回恒等 dict，**不做任何写库 / 外部副作用**——重复执行
    恒等返回、零副作用即天然幂等（per CONTEXT「占位 handler + 幂等测试，实际接入留
    Phase 62」）。
    """
    logger.debug("durable_page_index_noop", target_id=target_id, extra=kwargs or None)
    return {"status": "noop", "target_id": target_id}

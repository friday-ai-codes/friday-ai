"""durable 任务底座适配层。

本 app 是 v0.12.0 所有后续阶段的地基：业务侧入队 / 查询 / 取消任务一律经
`DurableTaskService` 统一门面，看不见底层队列实现（Postgres → Procrastinate /
SQLite·无 DATABASE_URL → in-process 非 durable fallback）。队列命名走 `durable.queues`
常量，避免裸字符串漂移。

curated re-export：业务侧 `from durable import DurableTaskService, QUEUE_INDEX`
单点导入即可，无需也禁止直接 import procrastinate。
"""

from __future__ import annotations

from durable.queues import (
    ALL_QUEUES,
    QUEUE_CRAWL_INGEST,
    QUEUE_GRAPH,
    QUEUE_INDEX,
    QUEUE_MAINTENANCE,
    QUEUE_PAGE_INDEX,
)
from durable.service import DurableTaskService

default_app_config = "durable.apps.DurableConfig"

__all__ = [
    "DurableTaskService",
    "QUEUE_INDEX",
    "QUEUE_GRAPH",
    "QUEUE_CRAWL_INGEST",
    "QUEUE_PAGE_INDEX",
    "QUEUE_MAINTENANCE",
    "ALL_QUEUES",
]

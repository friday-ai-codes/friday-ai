"""durable 任务底座的逻辑队列命名常量。

一个底座、多条逻辑队列：业务侧入队时只引用这里的常量，不裸写字符串，
避免队列名漂移。本阶段只定义命名，实际接入（index/graph 迁移、爬取队列等）
由 Phase 61/62 消费。
"""

from __future__ import annotations

# 代码索引（仓库 reindex / 增量索引）
QUEUE_INDEX = "index"
# 代码图谱构建（codegraph / galaxy）
QUEUE_GRAPH = "graph"
# 爬取结果入库（crawl → ingest）
QUEUE_CRAWL_INGEST = "crawl_ingest"
# 页面级索引（page → index）
QUEUE_PAGE_INDEX = "page_index"
# 维护类周期任务（stalled rescue 等运维任务）
QUEUE_MAINTENANCE = "maintenance"

# 全部已声明队列的汇总，供注册 / 校验 / worker 启动参数等场景遍历。
ALL_QUEUES: tuple[str, ...] = (
    QUEUE_INDEX,
    QUEUE_GRAPH,
    QUEUE_CRAWL_INGEST,
    QUEUE_PAGE_INDEX,
    QUEUE_MAINTENANCE,
)

__all__ = [
    "QUEUE_INDEX",
    "QUEUE_GRAPH",
    "QUEUE_CRAWL_INGEST",
    "QUEUE_PAGE_INDEX",
    "QUEUE_MAINTENANCE",
    "ALL_QUEUES",
]

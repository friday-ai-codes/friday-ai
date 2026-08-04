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
# 仓库 AI 描述派发（repo_summary → Runner 容器）。durable job 只负责"可靠地发起一次
# 派发"，重活在 Runner 容器内执行；解决建仓时 fire-and-forget 派发随 server 重启丢失。
QUEUE_REPO_SUMMARY = "repo_summary"
# 维护类周期任务（stalled rescue 等运维任务）
QUEUE_MAINTENANCE = "maintenance"
# 飞书↔Friday 文档同步（pull/push/poll 对同一文档共用 lock=docsync-{feishu_document_id} 串行）
QUEUE_DOC_SYNC = "doc_sync"
# feature list 异步解析（父任务出模块 + fan-out 逐模块并发解析；lock=featparse-slot-{k} 控并发）
QUEUE_FEATURE_PARSE = "feature_parse"
# 蓝图编排续驱（作答/确认门动作后的状态机驱动；lock=blueprint-resume-{session_id} 同会话串行）
QUEUE_BLUEPRINT = "blueprint"

# 全部已声明队列的汇总，供注册 / 校验 / worker 启动参数等场景遍历。
ALL_QUEUES: tuple[str, ...] = (
    QUEUE_INDEX,
    QUEUE_GRAPH,
    QUEUE_CRAWL_INGEST,
    QUEUE_PAGE_INDEX,
    QUEUE_REPO_SUMMARY,
    QUEUE_MAINTENANCE,
    QUEUE_DOC_SYNC,
    QUEUE_FEATURE_PARSE,
    QUEUE_BLUEPRINT,
)

__all__ = [
    "QUEUE_INDEX",
    "QUEUE_GRAPH",
    "QUEUE_CRAWL_INGEST",
    "QUEUE_PAGE_INDEX",
    "QUEUE_REPO_SUMMARY",
    "QUEUE_MAINTENANCE",
    "QUEUE_DOC_SYNC",
    "QUEUE_FEATURE_PARSE",
    "QUEUE_BLUEPRINT",
    "ALL_QUEUES",
]

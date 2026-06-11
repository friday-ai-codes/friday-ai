"""统一知识摄取核心（Phase 13 / INGEST-06、INGEST-07、INGEST-08）。

触发点唯一入口 ``aschedule_ingestion``（``transaction.on_commit`` +
background runner 投递，异常全吞永不阻塞主流程）+ 后台执行体
``ingest`` / ``ingest_events``（六步版本翻转事务序 + 四层幂等 + 边精细置位）。

规划定案（13-02-PLAN.md"规划定案"节，供 verify-work 对照）：

1. **OQ-1 措辞映射**：REQUIREMENTS/ROADMAP"旧边写 ``expired_at``"按 Phase 12
   bi-temporal 已定型语义实现为 ``graph_store.invalidate_edge``（置位
   ``invalid_at``，业务时间线失效）——版本替代是业务失效而非记录纠错
   （``expired_at`` 是系统时间线纠错语义）。
2. **边写入位置**：边操作在 ``ingest_events`` 内、``sync_to_async(_persist_sync)``
   完成之后经 graph_store 原语异步执行（**非**严格同事务）。恢复保障三层：
   ① ``uniq_kedge_active`` 约束 + 置位原语幂等使边阶段可重入；
   ② skipped/needs_revector 短路事件仍执行边阶段（任意重触发即自愈）；
   ③ 13-04 reconcile 检查项 6 终极兜底。边阶段为公开函数 ``apply_edge_specs``。
3. **边精细置位**：重摄取**不调** ``invalidate_entity_version``（实体作废语义，
   会失效全部出入边）；只在关系目标变化时置位旧边 + 建新边（exclusive EdgeSpec）。
4. **EdgeSpec 方向语义**：``IngestionEvent.edges`` 表示以本事件实体为 source 的
   出边；多事件批内先持久化全部实体/版本，再统一处理边（两端实体保证已存在）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from services.background_runner import run_in_background

logger = structlog.get_logger(__name__)

__all__ = [
    "EdgeSpec",
    "IngestionEvent",
    "IngestionRequest",
    "aschedule_ingestion",
    "ingest",
]


@dataclass(frozen=True)
class IngestionRequest:
    """触发点传入的最小定位信息（hook 唯一构造的对象，RESEARCH Pattern 1）。"""

    source_kind: str  # natural key 规则表字面值：coding_plan / mcp_technical_plan / ...
    source_id: str  # 业务对象稳定 ID（CodingPlan UUID str / 飞书三元组拼接 ...）
    trigger: str  # 结构化日志用："chat_plan_created" / "mcp_plan_created" / ...


@dataclass(frozen=True)
class EdgeSpec:
    """出边规格：以本事件实体为 source 的出边（规划定案 4）。

    ``exclusive=True``（如 HAS_PLAN）表示同 relation 同时只允许指向一个 target：
    重摄取时指向其他 target 的活跃边被逐条 ``invalidate_edge``，再建新边。
    """

    relation: str  # EdgeRelation 字面值
    target_entity_id: uuid.UUID  # 已派生目标实体 id（generate_entity_id 产物）
    exclusive: bool = False


@dataclass(frozen=True)
class IngestionEvent:
    """normalizer 产出的统一事件（ingest 核心唯一消费的形态）。"""

    kind: str  # EntityKind 字面值
    origin: str  # EntityOrigin 字面值
    source_kind: str
    source_id: str
    title: str
    content: str  # 提炼后全文（embedding 输入；对话原文禁止出现在此）
    payload: dict  # 结构化原文快照（落 KnowledgeEntityVersion.payload）
    project_id: str | None
    repository_id: str | None
    event_time: datetime  # aware（naive 进 GraphStore / 模型层会被拒）
    edges: tuple[EdgeSpec, ...] = ()


async def aschedule_ingestion(request: IngestionRequest) -> None:
    """触发点唯一入口：注册 on_commit → run_in_background 投递后台摄取。

    A1 写法（RESEARCH Pattern 2，全仓唯一正确写法）：``transaction.on_commit``
    操作 per-thread connection 状态，必须经 ``sync_to_async``（thread_sensitive
    默认 True，与 ORM 写同线程）在 sync 线程内注册——autocommit 下回调立即执行，
    atomic 块内延迟到 commit，rollback 时被丢弃。

    任何异常 log warning 不上抛（"永不阻塞主流程"纪律，signals.py 同款）。
    """

    def _register() -> None:
        task_name = f"knowledge-ingest-{request.source_kind}-{request.source_id}"
        transaction.on_commit(lambda: run_in_background(lambda: ingest(request), name=task_name))

    try:
        await sync_to_async(_register)()
    except Exception as exc:
        logger.warning(
            "knowledge_ingest_schedule_failed",
            trigger=request.trigger,
            source_kind=request.source_kind,
            source_id=request.source_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


async def ingest(request: IngestionRequest) -> None:
    """background worker 内执行的完整摄取（normalizer → ingest_events）。

    Task 2 落地六步序；本任务先交付签名供调度层 factory 引用。
    失败 raise（由 background_runner 的 ``background_task_failed`` 日志兜底）。
    """
    raise NotImplementedError("ingest 执行体由 Plan 13-02 Task 2 落地")

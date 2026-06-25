"""趋势采样（RATE-03 采样侧）——把并发/队列/积压快照拍平成 GaugeSample 时序点。

由 apscheduler 周期任务（73-03，``IntervalTrigger`` ~45s）调用：调 73-01
``snapshot_service`` 的并发/主机采集器，取并发槽位 / durable 队列深 / runner 待派发 /
后台积压的**当前值**，按**受控 name 枚举**拍平成多行 ``GaugeSample``，一次
``abulk_create`` 落库，供 73-02 ``gauge:<name>`` 按时间桶聚合趋势。

设计红线（per observability-logging 规范 + 73-CONTEXT）：

- **整函数 best-effort**：采集/落库任一失败只 warning，返回 ``{"written": 0}``，
  **绝不抛、绝不打断 scheduler 主循环**（观测代码永不反噬业务）。
- **受控 name/labels**：``name`` 仅取 ``_GAUGE_NAMES`` 模块级枚举（``concurrency.`` /
  ``queue.`` / ``backlog.`` 前缀，与 73-02 ``_validate_gauge_name`` 受控前缀对齐）；
  ``labels`` 仅落 credential UUID / provider 枚举 / queue 名，**绝不落密钥或用户输入原文**。
- **不臆造空噪声**：源 envelope ``available=False`` / 取不到的块直接跳过，不落 0 行。
- **category=sampling**：高频内部步骤，事件名 snake_case，避免 INFO 刷屏。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.utils import timezone

logger = structlog.get_logger(__name__)

# 受控指标名枚举（禁用户输入原文；与 73-02 受控前缀 concurrency./queue./backlog. 对齐）。
_GAUGE_NAMES = frozenset(
    {
        "concurrency.provider_slots",
        "concurrency.rag",
        "queue.durable_todo",
        "queue.durable_doing",
        "queue.runner_pending",
        "queue.runner_local",
        "backlog.subagent_active",
        "backlog.background_tasks",
    }
)


def _is_unavailable(block: Any) -> bool:
    """源块 envelope 是否标记不可用（``{"available": False, ...}``）。

    并发快照各块成功时为 list / 普通 dict（无 available 键），失败时统一降级为
    ``{"available": False, "error": ...}``——据此跳过不落噪声行。
    """
    return isinstance(block, dict) and block.get("available") is False


async def sample_gauges() -> dict[str, int]:
    """采样并发/队列/积压快照 → 拍平成受控 name 的 GaugeSample 行并 bulk_create。

    整函数 ``try/except`` 兜底：异常只记 warning ``gauge_sample_failed`` 并返回
    ``{"written": 0}``，绝不抛、绝不反噬业务。所有行共用同一 ``ts``（便于按帧对齐）。
    返回 ``{"written": n}``（落库行数）。
    """
    from system.models import GaugeSample
    from system.snapshot_service import (
        collect_concurrency_snapshot,
        collect_host_snapshot,
    )

    try:
        ts = timezone.now()
        rows: list[GaugeSample] = []

        concurrency = await collect_concurrency_snapshot()
        host = await collect_host_snapshot()

        # 块一：provider 槽位占用（每凭证一行，labels 仅 credential UUID + provider 枚举）。
        provider_slots = concurrency.get("provider_slots") if concurrency.get("available") else None
        if isinstance(provider_slots, list):
            for slot in provider_slots:
                in_use = slot.get("in_use")
                if in_use is None:
                    continue  # 取不到不臆造（如该凭证 Redis 读失败）。
                rows.append(
                    GaugeSample(
                        ts=ts,
                        name="concurrency.provider_slots",
                        value=float(in_use),
                        labels={
                            "credential": str(slot.get("credential_id", "")),
                            "provider": str(slot.get("provider", "")),
                        },
                    )
                )

        # 块二：durable 队列深度（按 procrastinate 队列名 × todo/doing 分行）。
        durable = concurrency.get("durable_queues") if concurrency.get("available") else None
        if isinstance(durable, dict) and not _is_unavailable(durable):
            for item in durable.get("by_queue_status", []):
                status = str(item.get("status", ""))
                name = {"todo": "queue.durable_todo", "doing": "queue.durable_doing"}.get(status)
                if name is None:
                    continue  # 仅采 todo/doing（排队/在跑），其余状态不落趋势行。
                rows.append(
                    GaugeSample(
                        ts=ts,
                        name=name,
                        value=float(item.get("count", 0) or 0),
                        labels={"queue": str(item.get("queue", ""))},
                    )
                )

        # 块三：runner 待派发 + 本地在跑汇总。
        runner = concurrency.get("runner") if concurrency.get("available") else None
        if isinstance(runner, dict) and not _is_unavailable(runner):
            by_status = runner.get("assignments_by_status", {})
            pending = int(by_status.get("assigned", 0) or 0) if isinstance(by_status, dict) else 0
            rows.append(
                GaugeSample(ts=ts, name="queue.runner_pending", value=float(pending), labels={})
            )
            rows.append(
                GaugeSample(
                    ts=ts,
                    name="queue.runner_local",
                    value=float(runner.get("current_tasks", 0) or 0),
                    labels={},
                )
            )

        # 块四：RAG 并发——无显式信号量，源记 n/a，跳过不臆造（不落 0 噪声）。
        # （collect_concurrency_snapshot 的 rag 块恒为 {"available": False, "error": "n/a"}。）

        # 块五：后台积压（取 collect_host_snapshot 已聚合的 background_tasks 口径，逐项一行）。
        if host.get("available"):
            background = host.get("background_tasks")
            if isinstance(background, dict) and background:
                rows.append(
                    GaugeSample(
                        ts=ts,
                        name="backlog.subagent_active",
                        value=float(background.get("subagent_active", 0) or 0),
                        labels={},
                    )
                )
                rows.append(
                    GaugeSample(
                        ts=ts,
                        name="backlog.background_tasks",
                        value=float(background.get("total_active", 0) or 0),
                        labels={},
                    )
                )

        if rows:
            await GaugeSample.objects.abulk_create(rows)

        logger.info(
            "gauge_sampled",
            category="sampling",
            component="metric_sampling",
            source="scheduler",
            written=len(rows),
            names=sorted({r.name for r in rows}),
        )
        return {"written": len(rows)}
    except Exception as exc:  # noqa: BLE001 — 采样 best-effort，绝不抛、绝不反噬业务
        logger.warning(
            "gauge_sample_failed",
            category="sampling",
            component="metric_sampling",
            error=str(exc),
        )
        return {"written": 0}

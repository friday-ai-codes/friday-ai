"""系统告警周期评估器（ALERT-01 评估 + ALERT-02 firing/resolved/去重）。

apscheduler 周期任务 ``evaluate_system_alerts``：对每条 ``enabled`` 的
``SystemAlertRule`` 读"当前值"——时序类（``qps`` / ``error_rate`` / ``ttft``）经
Phase 73 ``metrics_query.query_timeseries`` 单桶聚合得窗口当前值；快照类（``cpu`` /
``memory`` / ``db_connections`` / ``redis_clients`` / ``qdrant`` / ``queue_depth``）经
``snapshot_service.collect_snapshot`` 取当前值——与阈值比较：

- **超阈触发 firing**：同 ``(rule, target_key)`` 去重一条（``aget_or_create`` 服务层
  收口 + 74-01 ``status=firing`` 条件唯一约束 DB 兜底双保险）。新 firing 写
  ``title_zh`` / ``rule_info(expr)`` / ``current_value`` / ``started_at`` 并调 74-03
  ``notify_channels`` 分发通知；重复超阈仅更新 ``current_value`` / ``last_seen_at``
  （**不刷屏、不重复通知**）。
- **恢复 resolved**：已有 firing 且本轮不再超阈 → ``status=resolved`` + ``ended_at`` +
  ``duration_s``，可选发恢复通知（best-effort）。
- **趋势类（RATE-03 ``gauge:*``）默认不参与**：``metric`` 不在受控集合 → 返回 ``None``
  跳过（per 74-CONTEXT）。

设计红线（绝不可破）：

- **单规则隔离 + best-effort**：逐规则独立 try/except，单规则失败只 ``warning`` 跳过，
  绝不连累其它规则；``evaluate_system_alerts`` 最外层兜底，绝不抛回 job wrapper、绝不
  反噬业务/打断 scheduler 主循环（观测代码惯例）。
- **归因**：作为后台任务经 ``_with_scheduler_log_context`` 绑 ``user_id=system`` /
  ``source=scheduler``（CTX-02）；评估周期高频事件 ``category=sampling`` 避免刷屏，
  firing/resolved ``category=caller`` + ``rule_id`` / ``duration_ms`` 可归因。
- **仅落元数据**：``rule_info`` / ``title_zh`` / ``target`` 仅承载 metric/阈值/当前值/
  受控维度，绝不落 raw payload / 凭证（T-74-02-04）。

async ORM 直接用异步 manager；同步聚合查询（``query_timeseries``）经 ``sync_to_async``
桥接。
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.utils import timezone

from system import metrics_query, snapshot_service
from system.models import AlertEvent, SystemAlertRule

logger = structlog.get_logger(__name__)

# 时序类 metric：经 metrics_query.query_timeseries 单桶聚合取窗口当前值。
_TIMESERIES_METRICS = frozenset({"qps", "error_rate", "ttft"})
# 快照类 metric：经 snapshot_service.collect_snapshot 取当前值。
_SNAPSHOT_METRICS = frozenset(
    {"cpu", "memory", "db_connections", "redis_clients", "qdrant", "queue_depth"}
)

# 比较操作符 → 表达式符号（rule_info.expr / 默认标题用）。
_OP_SYMBOL = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


# ---------------------------------------------------------------------------
# 纯函数 helper：阈值比较 / 维度规范化 / rule_info / title 渲染
# ---------------------------------------------------------------------------


def _breached(op: str, current: float, threshold: float) -> bool:
    """阈值比较纯函数：``gt`` / ``gte`` / ``lt`` / ``lte``；未知操作符回 False。"""
    if op == "gt":
        return current > threshold
    if op == "gte":
        return current >= threshold
    if op == "lt":
        return current < threshold
    if op == "lte":
        return current <= threshold
    return False


def _split_dimension(dimension: Any) -> tuple[dict[str, Any], str | None]:
    """把 rule.dimension 拆成 (目标维度 dict, agg)。

    ``agg`` 是时序分位查询参数（如 ttft 的 ``p95``），**非对象维度**——从目标维度剔除，
    避免污染 ``target_key`` 去重键与 ``dim_label``。
    """
    dim = dict(dimension) if isinstance(dimension, dict) else {}
    agg = dim.pop("agg", None)
    return dim, (str(agg) if agg is not None else None)


def _dimension_column(target_dim: dict[str, Any]) -> tuple[str, str | None]:
    """取目标维度的第一个键值对作为 (分组列名, 目标值)；overall 时回 ("", None)。"""
    for key, value in sorted(target_dim.items()):
        return str(key), str(value)
    return "", None


def _target_for(rule: SystemAlertRule) -> tuple[dict[str, Any], str]:
    """构造对象标识 + 规范化去重键：``target_key = json.dumps(target, sort_keys=True)``。"""
    target, _ = _split_dimension(rule.dimension)
    target_key = json.dumps(target, sort_keys=True, ensure_ascii=False)
    return target, target_key


def _window_human(seconds: int) -> str:
    """评估窗口秒 → 人类可读（``300`` → ``5m``，``3600`` → ``1h``，非整除回 ``Ns``）。"""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "0s"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _dim_label(target_dim: dict[str, Any]) -> str:
    """维度标签：overall（空）或 ``k=v`` 逗号拼接（REFERENCE-UI §1.4 同款）。"""
    if not target_dim:
        return "overall"
    return ",".join(f"{k}={v}" for k, v in sorted(target_dim.items()))


def _build_rule_info(rule: SystemAlertRule, current: float) -> dict[str, Any]:
    """构造机器可读 rule_info（REFERENCE-UI §1.4 expr 同款 + 结构化字段）。

    expr 形如 ``cpu > 85.00 (current 95.40) over last 5m (overall)``——机器可读规则 +
    当前值 + 窗口 + 维度，仅元数据绝不含凭证。
    """
    target_dim, _ = _split_dimension(rule.dimension)
    op_symbol = _OP_SYMBOL.get(rule.op, rule.op)
    window_human = _window_human(rule.window)
    dim_label = _dim_label(target_dim)
    expr = (
        f"{rule.metric} {op_symbol} {rule.value:.2f} "
        f"(current {current:.2f}) over last {window_human} ({dim_label})"
    )
    return {
        "metric": rule.metric,
        "op": rule.op,
        "threshold": rule.value,
        "current": current,
        "window_s": int(rule.window or 0),
        "dimension": target_dim,
        "expr": expr,
    }


def _render_title(rule: SystemAlertRule, current: float) -> str:
    """按 ``title_template`` 渲染中文标题（``{metric}`` / ``{current}`` / ``{value}`` 占位）。

    模板为空或渲染异常 → 默认拼接 ``f"{metric} {op} {value}（当前 {current}）"``。
    """
    template = (rule.title_template or "").strip()
    if template:
        try:
            return template.format(metric=rule.metric, current=current, value=rule.value)
        except (KeyError, IndexError, ValueError):
            pass  # 模板占位非法 → 退化默认拼接，绝不抛
    op_symbol = _OP_SYMBOL.get(rule.op, rule.op)
    return f"{rule.metric} {op_symbol} {rule.value}（当前 {round(current, 2)}）"


# ---------------------------------------------------------------------------
# metric → 当前值来源分派（取不到返回 None → 本轮该规则跳过，不臆造）
# ---------------------------------------------------------------------------


def _pick_latest_bucket(series: list[dict[str, Any]], dim_value: str | None) -> dict[str, Any] | None:
    """从时序桶序列（按 bucket 升序）取匹配维度的最近一桶；无匹配回 None。"""
    matching = [s for s in series if dim_value is None or s.get("dim") == dim_value]
    if not matching:
        return None
    return matching[-1]


async def _resolve_timeseries_value(rule: SystemAlertRule) -> float | None:
    """时序类 metric 取窗口当前值（单桶聚合 ``start=now-window`` / ``end=now`` / ``step=window``）。"""
    window = int(rule.window or 300)
    if window <= 0:
        window = 300
    now = timezone.now()
    start = (now - timedelta(seconds=window)).isoformat()
    end = now.isoformat()
    step = f"{window}s"

    target_dim, agg = _split_dimension(rule.dimension)
    dim_col, dim_val = _dimension_column(target_dim)

    if rule.metric == "qps":
        result = await sync_to_async(metrics_query.query_timeseries, thread_sensitive=True)(
            metric="qps", start=start, end=end, step=step, dimension=dim_col
        )
        bucket = _pick_latest_bucket(result.get("series") or [], dim_val)
        if bucket is None or bucket.get("value") is None:
            return None
        # qps 口径：单桶 COUNT(*) 折算每秒请求数（count / window）。
        return float(bucket["value"]) / window

    if rule.metric == "error_rate":
        # 用 SLA series 派生错误率（failures/eligible，与 SLA-01 口径一致：排除 business）。
        result = await sync_to_async(metrics_query.query_timeseries, thread_sensitive=True)(
            metric="sla", start=start, end=end, step=step, dimension=dim_col
        )
        bucket = _pick_latest_bucket(result.get("series") or [], dim_val)
        if bucket is None:
            return None
        eligible = int(bucket.get("eligible") or 0)
        failures = int(bucket.get("failures") or 0)
        if eligible <= 0:
            return None
        return failures / eligible

    if rule.metric == "ttft":
        result = await sync_to_async(metrics_query.query_timeseries, thread_sensitive=True)(
            metric="ttft", start=start, end=end, step=step, dimension=dim_col, agg=agg or "p95"
        )
        bucket = _pick_latest_bucket(result.get("series") or [], dim_val)
        if bucket is None or bucket.get("value") is None:
            return None
        return float(bucket["value"])

    return None


async def _resolve_snapshot_value(rule: SystemAlertRule) -> float | None:
    """快照类 metric 取当前值（一次 ``collect_snapshot``，按 metric 取相应字段）。"""
    snap = await snapshot_service.collect_snapshot()
    metric = rule.metric

    if metric in ("cpu", "memory"):
        host = snap.get("host") or {}
        if not host.get("available"):
            return None
        value = host.get("cpu_percent") if metric == "cpu" else host.get("mem_percent")
        return float(value) if value is not None else None

    if metric == "db_connections":
        db = snap.get("db") or {}
        if not db.get("available"):
            return None
        total = (db.get("connections") or {}).get("total")
        return float(total) if total is not None else None

    if metric == "redis_clients":
        redis = snap.get("redis") or {}
        if not redis.get("available"):
            return None
        # 多路 Redis 求和（仅计可用路的 connected_clients）。
        total = 0
        seen = False
        for route in (redis.get("clients") or {}).values():
            if isinstance(route, dict) and route.get("available"):
                clients = route.get("connected_clients")
                if clients is not None:
                    total += int(clients)
                    seen = True
        return float(total) if seen else None

    if metric == "qdrant":
        # 可用性布尔转 0/1（qdrant 告警语义为"是否在线"；collection_count 深度规则留 v2）。
        qdrant = snap.get("qdrant") or {}
        return 1.0 if qdrant.get("available") else 0.0

    if metric == "queue_depth":
        concurrency = snap.get("concurrency") or {}
        if not concurrency.get("available"):
            return None
        return _sum_queue_depth(concurrency.get("durable_queues"), rule.dimension)

    return None


def _sum_queue_depth(durable: Any, dimension: Any) -> float | None:
    """durable 队列深度：``todo`` + ``doing`` 计数汇总（按 ``rule.dimension.queue`` 过滤，缺省汇总）。"""
    if not isinstance(durable, dict) or "by_queue_status" not in durable:
        return None
    queue_filter = dimension.get("queue") if isinstance(dimension, dict) else None
    total = 0
    for row in durable.get("by_queue_status") or []:
        if row.get("status") not in ("todo", "doing"):
            continue
        if queue_filter and row.get("queue") != queue_filter:
            continue
        total += int(row.get("count") or 0)
    return float(total)


async def _resolve_current_value(rule: SystemAlertRule) -> float | None:
    """metric → 当前值分派（整函数 try/except 兜底，取值异常返回 None：单规则隔离绝不抛）。"""
    try:
        if rule.metric in _TIMESERIES_METRICS:
            return await _resolve_timeseries_value(rule)
        if rule.metric in _SNAPSHOT_METRICS:
            return await _resolve_snapshot_value(rule)
        # 趋势类 gauge:* / 未知 metric → 默认不参与评估（RATE-03，per 74-CONTEXT）。
        logger.warning(
            "alert_metric_unsupported",
            category="sampling",
            component="alerting",
            source="scheduler",
            rule_id=rule.id,
            metric=rule.metric,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — 取值失败局部降级，本轮跳过该规则，绝不抛
        logger.warning(
            "alert_metric_resolve_failed",
            category="sampling",
            component="alerting",
            source="scheduler",
            rule_id=rule.id,
            metric=rule.metric,
            error=str(exc),
        )
        return None


# ---------------------------------------------------------------------------
# 去重 / 恢复收口（服务层 get_or_create，配合 74-01 DB 条件唯一约束双保险）
# ---------------------------------------------------------------------------


async def _open_or_update_firing(
    rule: SystemAlertRule, current: float
) -> tuple[AlertEvent | None, bool]:
    """超阈触发 firing 去重一条：``aget_or_create`` 幂等 + DB 约束兜底 IntegrityError。

    新建（``created=True``）→ 写齐字段；已存在 → 仅更新 ``current_value`` /
    ``last_seen_at`` / ``rule_info``（不刷屏、不新建）。返回 ``(event, created)``。
    """
    target, target_key = _target_for(rule)
    now = timezone.now()
    rule_info = _build_rule_info(rule, current)
    title = _render_title(rule, current)

    try:
        event, created = await AlertEvent.objects.aget_or_create(
            rule=rule,
            target_key=target_key,
            status="firing",
            defaults={
                "severity": rule.severity,
                "title_zh": title,
                "rule_info": rule_info,
                "target": target,
                "current_value": current,
                "started_at": now,
                "last_seen_at": now,
            },
        )
    except IntegrityError:
        # 并发双开被 DB 条件唯一约束兜底 → 退化为取已存在 firing 更新。
        event = await AlertEvent.objects.filter(
            rule=rule, target_key=target_key, status="firing"
        ).afirst()
        if event is None:
            return None, False
        created = False

    if not created:
        event.current_value = current
        event.last_seen_at = now
        event.rule_info = rule_info
        await event.asave(update_fields=["current_value", "last_seen_at", "rule_info"])

    return event, created


async def _resolve_firing(rule: SystemAlertRule, target_key: str) -> AlertEvent | None:
    """恢复收尾：取该 ``(rule, target_key)`` 的 firing → ``resolved`` + ``ended_at`` + ``duration_s``。"""
    event = await AlertEvent.objects.filter(
        rule=rule, target_key=target_key, status="firing"
    ).afirst()
    if event is None:
        return None
    now = timezone.now()
    event.status = "resolved"
    event.ended_at = now
    started = event.started_at
    duration = int((now - started).total_seconds()) if started else 0
    event.duration_s = max(duration, 0)
    await event.asave(update_fields=["status", "ended_at", "duration_s"])
    return event


async def _maybe_notify(rule: SystemAlertRule, event: AlertEvent) -> None:
    """按 ``rule.channels`` 调 74-03 ``notify_channels`` 分发（best-effort 再兜底，绝不反噬）。

    cooldown 防抖天然成立：重复超阈不新建 firing（``created=False`` 不进本函数），
    故首次 firing 必通知、cooldown 内重复超阈不重复通知；恢复通知亦走此出口。
    """
    channels = rule.channels or []
    if not channels:
        return  # 空通道=仅落事件不通知（per SystemAlertRule.channels 语义）
    try:
        from system import alert_notifier

        await alert_notifier.notify_channels(event, channels)
    except Exception as exc:  # noqa: BLE001 — 通知绝不反噬评估（74-03 已 best-effort，此处再兜底）
        logger.warning(
            "alert_notify_dispatch_failed",
            category="caller",
            component="alerting",
            source="scheduler",
            rule_id=rule.id,
            event_id=getattr(event, "id", None),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# 评估循环主体
# ---------------------------------------------------------------------------


async def evaluate_system_alerts() -> dict[str, int]:
    """周期评估所有 enabled SystemAlertRule：读当前值比阈值，超阈 firing / 恢复 resolved。

    返回 ``{"evaluated": n, "firing": x, "resolved": y}``。逐规则独立 try/except 单规则
    隔离；最外层兜底——任何异常都吞掉返回 ``{"evaluated": 0}``，绝不抛回 job wrapper。
    """
    cycle_start = time.perf_counter()
    evaluated = 0
    firing = 0
    resolved = 0
    try:
        rules = [r async for r in SystemAlertRule.objects.filter(enabled=True)]
        for rule in rules:
            rule_start = time.perf_counter()
            try:
                evaluated += 1
                current = await _resolve_current_value(rule)
                if current is None:
                    continue  # 取不到当前值不评估（不臆造）

                _, target_key = _target_for(rule)
                if _breached(rule.op, current, rule.value):
                    event, created = await _open_or_update_firing(rule, current)
                    if created and event is not None:
                        firing += 1
                        logger.info(
                            "alert_firing",
                            category="caller",
                            component="alerting",
                            source="scheduler",
                            rule_id=rule.id,
                            metric=rule.metric,
                            current=current,
                            severity=rule.severity,
                            event_id=event.id,
                            duration_ms=int((time.perf_counter() - rule_start) * 1000),
                        )
                        await _maybe_notify(rule, event)
                    # 重复超阈（created=False）：仅更新值不刷屏、cooldown 内不重通知。
                else:
                    event = await _resolve_firing(rule, target_key)
                    if event is not None:
                        resolved += 1
                        logger.info(
                            "alert_resolved",
                            category="caller",
                            component="alerting",
                            source="scheduler",
                            rule_id=rule.id,
                            metric=rule.metric,
                            current=current,
                            severity=rule.severity,
                            event_id=event.id,
                            duration_s=event.duration_s,
                            duration_ms=int((time.perf_counter() - rule_start) * 1000),
                        )
                        await _maybe_notify(rule, event)
            except Exception as exc:  # noqa: BLE001 — 单规则隔离：失败只跳过，绝不连累其它规则
                logger.warning(
                    "alert_rule_eval_failed",
                    category="sampling",
                    component="alerting",
                    source="scheduler",
                    rule_id=getattr(rule, "id", None),
                    error=str(exc),
                )
                continue

        # 评估周期高频 → category=sampling（避免 INFO 刷屏，高频循环纪律）。
        logger.info(
            "alert_eval_cycle",
            category="sampling",
            component="alerting",
            source="scheduler",
            evaluated=evaluated,
            firing=firing,
            resolved=resolved,
            duration_ms=int((time.perf_counter() - cycle_start) * 1000),
        )
        return {"evaluated": evaluated, "firing": firing, "resolved": resolved}
    except Exception as exc:  # noqa: BLE001 — 最外层兜底：评估绝不反噬业务/打断 scheduler
        logger.warning(
            "alert_eval_failed",
            category="sampling",
            component="alerting",
            source="scheduler",
            error=str(exc),
        )
        return {"evaluated": 0}

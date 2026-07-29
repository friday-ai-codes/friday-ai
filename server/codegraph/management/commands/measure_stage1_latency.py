"""Stage 1（LLM 重排）调用延迟分位实测（O-6）——RELY-05 的延迟压降结论输入。

数据源是系统日志落库表里 ``repo_router_v2_stage1_completed`` 事件的
``payload.duration_ms``（``repo_router_v2._stage1_llm_reasoning`` 打点）。
**不能用** ``ModelUsageRecord``：Stage 1 直调 ``build_chat_model(...).ainvoke(...)``，
不经 ``interactions.ledger.record_model_usage`` 这个写入 chokepoint，故该表里查不到
``aux_repo_router`` 的行（107-RESEARCH §9 VERIFIED）。埋点补齐见 107-05。

口径三条（读数字前必须知道）：

- 测的是**缓存未命中时的上游真实延迟**——命中输入哈希缓存的路径不发 LLM 调用、
  也不打该事件（``if not cache_hit:`` 块内才打），所以这不是用户感知延迟。
- 该事件 ``category="sampling"`` 且是 ``logger.info``：落库量受运行时采样配置
  （``SettingKeys.LOG_*``）与组件日志级别影响，可能不是全量 → 解读时须带采样率。
- 分位口径与运维大盘一致：Postgres 用 ``percentile_cont``（LOGGING-SPEC §4.3
  明确纪律，不自研直方图/聚合器）；SQLite 本地 dev 无该函数 → 在 Python 侧用
  线性插值分位（与 ``repo_router_eval._quantile`` 同口径，stdlib，禁第三方数值库）。

输出只含聚合量（时间窗 / 样本量 / 三个分位 / 数据库 vendor），**绝不回显任何
payload 原文**——命令输出会被贴进工单与 MEASUREMENTS 文档（T-107-02）。

CLI 用例
========

::

    python manage.py measure_stage1_latency --days 7
    python manage.py measure_stage1_latency --days 30 --json

生产分位数字须在有真实流量的部署实例上执行才有意义；本地空库跑出的 ``n=0``
不得回填 ``107-MEASUREMENTS.md``（数据环境标注纪律，沿用 105/106）。
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timedelta
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

logger = structlog.get_logger(__name__)

DEFAULT_EVENT = "repo_router_v2_stage1_completed"
DEFAULT_WINDOW_DAYS = 7

_EVENT_MEASURED = "stage1_latency_measured"
_EVENT_FAILED = "stage1_latency_measure_failed"

# 命令由运维/scheduler 手动执行，无请求上下文 → 触发用户按规范记 system。
_LOG_KV = {
    "category": "sampling",
    "component": "repo_router_v2",
    "initiated_by_user_id": "system",
}

# 三个分位的受控字面量（进 SQL 的只有这三个模块常量，无用户输入）。
_QUANTILES: tuple[tuple[str, str, float], ...] = (
    ("p50_ms", "0.5", 0.50),
    ("p90_ms", "0.9", 0.90),
    ("p99_ms", "0.99", 0.99),
)

# payload 里 duration_ms 的合法数值形态；Postgres 侧用它先过滤再 ::numeric，
# 避免一条脏行（非数值）让整条聚合查询报错（Python 侧同口径跳过）。
_NUMERIC_PATTERN = r"^-?[0-9]+(\.[0-9]+)?$"

_DURATION_JSON_EXPR = "(payload->>'duration_ms')"

_EMPTY_HINT = (
    "n=0（时间窗内无样本）：确认 category=sampling 的运行时采样配置（SettingKeys.LOG_*）"
    "与 repo_router_v2 组件日志级别（该事件是 logger.info，级别调到 WARNING 即无行），"
    "或缓存命中率过高（命中路径不发 LLM 调用也不打该事件）"
)


def _quantile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位数（与 ``repo_router_eval._quantile`` 同口径；stdlib，禁第三方数值库）。

    ``sorted_vals`` 必须已升序且非空。
    """
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _coerce_duration_ms(raw: Any) -> float | None:
    """payload 值 → 毫秒浮点；缺键 / None / 非数值 / bool / NaN 一律返回 None（跳过该行）。"""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            return None
    else:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def _render_markdown(report: dict[str, Any]) -> str:
    """人读输出：只有聚合量的 markdown 表（可直接贴进 107-MEASUREMENTS.md）。"""

    def _cell(key: str) -> str:
        value = report[key]
        return "-" if value is None else str(value)

    lines = [
        "## Stage 1 延迟分位（O-6）",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| event | {report['event']} |",
        f"| window_days | {report['window_days']} |",
        f"| window_start | {report['window_start']} |",
        f"| db_vendor | {report['db_vendor']} |",
        f"| n（样本量） | {report['n']} |",
        f"| p50_ms | {_cell('p50_ms')} |",
        f"| p90_ms | {_cell('p90_ms')} |",
        f"| p99_ms | {_cell('p99_ms')} |",
        "",
        "口径：缓存未命中时的上游真实延迟（非用户感知延迟）；"
        "事件为采样类，落库量受采样配置与组件日志级别影响。",
    ]
    if report.get("note"):
        lines += ["", f"提示：{report['note']}"]
    return "\n".join(lines)


class Command(BaseCommand):
    help = (
        "统计 Stage 1（LLM 重排）调用延迟分位 p50/p90/p99 与样本量（O-6 / RELY-05）——"
        "Postgres 走 percentile_cont，SQLite 回退 Python 侧线性插值分位"
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_WINDOW_DAYS,
            help=f"统计时间窗（天，默认 {DEFAULT_WINDOW_DAYS}）",
        )
        parser.add_argument(
            "--event",
            type=str,
            default=DEFAULT_EVENT,
            help=f"事件名（默认 {DEFAULT_EVENT}）",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="输出机器可读 JSON（供转写 107-MEASUREMENTS.md）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        days = max(int(options["days"]), 1)
        event = str(options["event"])
        window_start = timezone.now() - timedelta(days=days)
        vendor = connection.vendor
        start = time.monotonic()

        try:
            if vendor == "postgresql":
                stats = self._percentiles_via_sql(event=event, window_start=window_start)
            else:
                stats = self._percentiles_in_python(event=event, window_start=window_start)
        except Exception as exc:
            from common.logging import redact_secrets_in_text

            # 异常文本可能携带连接串等敏感片段 —— 手动脱敏兜底后才留痕。
            reason = redact_secrets_in_text(str(exc))
            logger.warning(
                _EVENT_FAILED,
                error=reason,
                window_days=days,
                duration_ms=int((time.monotonic() - start) * 1000),
                **_LOG_KV,
            )
            # 命令是排障工具：查询失败必须以非零退出码可见，不静默返回 n=0。
            raise CommandError(f"延迟分位查询失败：{reason}") from exc

        report: dict[str, Any] = {
            "event": event,
            "window_days": days,
            "window_start": window_start.isoformat(),
            "db_vendor": vendor,
            **stats,
        }
        if report["n"] == 0:
            report["note"] = _EMPTY_HINT

        try:
            logger.info(
                _EVENT_MEASURED,
                window_days=days,
                sample_count=report["n"],
                p50_ms=report["p50_ms"],
                p90_ms=report["p90_ms"],
                p99_ms=report["p99_ms"],
                db_vendor=vendor,
                duration_ms=int((time.monotonic() - start) * 1000),
                **_LOG_KV,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬命令退出码
            pass

        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(_render_markdown(report))

    def _percentiles_via_sql(self, *, event: str, window_start: datetime) -> dict[str, Any]:
        """Postgres 精确分位：单条 ``percentile_cont`` 聚合（LOGGING-SPEC §4.3）。

        表名取自模型的 ``Meta.db_table``（不写死物理表名）；事件名 / 时间窗 / 数值
        正则全部走 ``%s`` 参数化绑定，SQL 里没有任何字符串拼接的用户输入（T-107-09）。
        """
        from system.models import SystemLogEntry

        table = SystemLogEntry._meta.db_table
        order_expr = _DURATION_JSON_EXPR + "::numeric"
        select_parts = ["count(*) AS n"]
        for alias, frac, _q in _QUANTILES:
            select_parts.append(
                "percentile_cont("
                + frac
                + ") WITHIN GROUP (ORDER BY "
                + order_expr
                + ") AS "
                + alias
            )
        sql = (
            "SELECT "
            + ", ".join(select_parts)
            + " FROM "
            + table
            + " WHERE event = %s AND ts >= %s AND "
            + _DURATION_JSON_EXPR
            + " ~ %s"
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, [event, window_start, _NUMERIC_PATTERN])
            row = cursor.fetchone()

        count = int(row[0]) if row else 0
        stats: dict[str, Any] = {"n": count}
        for index, (alias, _frac, _q) in enumerate(_QUANTILES, start=1):
            value = row[index] if row else None
            stats[alias] = round(float(value), 2) if count and value is not None else None
        return stats

    def _percentiles_in_python(self, *, event: str, window_start: datetime) -> dict[str, Any]:
        """非 Postgres 回退：拉 payload 后在 Python 侧算线性插值分位（dev 降级，§4.3 允许）。

        只取 ``payload`` 一列（不取 ``message`` 等自由文本），且只把其中的
        ``duration_ms`` 转成数值——其余键一律不进内存结果，杜绝原文外泄。
        """
        from system.models import SystemLogEntry

        durations: list[float] = []
        rows = (
            SystemLogEntry.objects.filter(event=event, ts__gte=window_start)
            .values_list("payload", flat=True)
            .iterator()
        )
        for payload in rows:
            if not isinstance(payload, dict):
                continue
            value = _coerce_duration_ms(payload.get("duration_ms"))
            if value is None:
                continue
            durations.append(value)

        durations.sort()
        stats: dict[str, Any] = {"n": len(durations)}
        for alias, _frac, quantile in _QUANTILES:
            stats[alias] = round(_quantile(durations, quantile), 2) if durations else None
        return stats

"""时序聚合查询服务（QUERY-01 / SLA-01 / RATE-03 查询侧）。

把 Phase 72 采集的精简事件行（``RequestMetric`` / ``ModelUsageRecord``）与 73-01/03
周期采样（``GaugeSample``）变成"可按任意时间段查询 + 出趋势"——单一只读聚合服务，
零自研聚合器/直方图/rollup 引擎（第一性原理 §A.2：原始行 + SQL 聚合）。

设计红线：

- **精确分位走 Postgres ``percentile_cont``**（``WITHIN GROUP``）；SQLite dev 无该函数
  → 降级用 ``MAX`` / ``AVG`` 近似兜底并打 ``degraded=true`` 标记，**功能绝不阻塞**
  （per MILESTONE-PROPOSAL §A.4）。后端经 ``connection.vendor`` 分支。
- **任意 step 时间桶**用 epoch-floor 分桶（``to_timestamp(floor(epoch/step)*step)`` /
  ``datetime((strftime('%s')/step)*step,'unixepoch')``），比 ``date_trunc`` 更通用。
- **无注入面**：metric/agg/dimension 全经 ``frozenset`` 白名单校验，列名仅取白名单常量；
  step 经 ``int()`` 收口；start/end 经参数化占位符（``%s``），绝不字符串拼用户原文。
- **synthetic 隔离**：轮询/health 打标行（``labels.synthetic=true``，72-01）在
  SLA/QPS 聚合中排除，不污染业务统计。
- **DoS 缓解**：``_MAX_BUCKETS`` 上限按比例抬高 step，防超大跨度 × 极小 step 拖垮 DB。

async 视图经 ``sync_to_async`` 桥接调用（raw cursor 为同步 ORM 访问）。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from datetime import timezone as _tz
from decimal import Decimal
from typing import Any

from django.db import connection
from django.utils import timezone

# ---------------------------------------------------------------------------
# 受控枚举常量（禁任意字符串污染/SQL 注入面）
# ---------------------------------------------------------------------------

_METRICS = frozenset({"qps", "tps", "sla", "error", "duration", "ttft", "upstream"})
_AGGS = frozenset({"p99", "p95", "p90", "p50", "avg", "max"})
# 白名单列名：**仅这些**可进 GROUP BY，杜绝任意列注入。
_DIMENSIONS = frozenset({"source", "provider", "call_source", "error_class", "route", "model"})
_PERCENTILE = {"p99": 0.99, "p95": 0.95, "p90": 0.90, "p50": 0.50}

# 各表实际可分组列（dimension 落到该表才分组，否则退化为 '__all__' 全量桶）。
_REQUEST_DIMS = frozenset({"source", "route", "error_class"})
_USAGE_DIMS = frozenset({"provider", "call_source", "model"})

# gauge 特例：metric=gauge:<name>，name 受控前缀（73-01/03 GaugeSample 写入命名）。
_GAUGE_PREFIX = "gauge:"
_GAUGE_NAME_PREFIXES = ("concurrency.", "queue.", "backlog.")

# step 解析边界（秒）与桶数上限。
_DEFAULT_STEP = 60
_MIN_STEP = 10
_MAX_STEP = 86400  # 1d
_MAX_BUCKETS = 2000


# ---------------------------------------------------------------------------
# 参数解析 / 校验 helper
# ---------------------------------------------------------------------------


def _parse_step(step: str | None) -> int:
    """解析 ``30s/1m/5m/1h/1d`` → 秒（默认 60s，最小 10s，最大 1d）；非法回默认。"""
    if not step:
        return _DEFAULT_STEP
    text = str(step).strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        if text and text[-1] in units:
            value = int(text[:-1]) * units[text[-1]]
        else:
            value = int(text)
    except (ValueError, IndexError):
        return _DEFAULT_STEP
    if value < _MIN_STEP:
        return _MIN_STEP
    if value > _MAX_STEP:
        return _MAX_STEP
    return value


def _parse_iso(value: str | None) -> datetime | None:
    """ISO8601 解析（兼容尾部 ``Z``）；非法/空返回 None；naive 补 UTC。"""
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, _tz.utc)
    return dt


def _parse_range(start: str | None, end: str | None) -> tuple[datetime, datetime]:
    """解析时间窗：缺省 end=now / start=end-1h；start>=end 时回退 end-1h。"""
    end_dt = _parse_iso(end) or timezone.now()
    start_dt = _parse_iso(start) or (end_dt - timedelta(hours=1))
    if start_dt >= end_dt:
        start_dt = end_dt - timedelta(hours=1)
    return start_dt, end_dt


def _cap_step(start_dt: datetime, end_dt: datetime, step_seconds: int) -> int:
    """上限保护：桶数（跨度/step）超过 ``_MAX_BUCKETS`` 时按比例抬高 step。

    防超大时间跨度 × 极小 step 返回海量桶拖垮 DB（T-73-02-02）。
    """
    span = (end_dt - start_dt).total_seconds()
    if span <= 0:
        return step_seconds
    if span / step_seconds <= _MAX_BUCKETS:
        return step_seconds
    needed = math.ceil(span / _MAX_BUCKETS)
    return min(max(needed, step_seconds), _MAX_STEP)


def _validate(metric: str, agg: str, dimension: str) -> str:
    """校验 metric/dimension（非法抛中文 ValueError），返回规范化 agg（非法回 p95）。"""
    if metric not in _METRICS and not metric.startswith(_GAUGE_PREFIX):
        raise ValueError(f"不支持的 metric：{metric!r}")
    if dimension and dimension not in _DIMENSIONS:
        raise ValueError(f"不支持的 dimension：{dimension!r}")
    if agg not in _AGGS:
        return "p95"
    return agg


def _validate_gauge_name(name: str) -> str:
    """gauge 名仅允许 73-01/03 写入的受控前缀（concurrency./queue./backlog.）。"""
    if not name or not any(name.startswith(p) for p in _GAUGE_NAME_PREFIXES):
        raise ValueError(f"未知的 gauge 名称：{name!r}")
    return name


# ---------------------------------------------------------------------------
# SQL 片段构造（列名/step 全取白名单常量 + int 收口，无用户原文进 SQL 文本）
# ---------------------------------------------------------------------------


def _bucket_expr(time_col: str, step_seconds: int, vendor: str) -> str:
    """任意 step 时间桶（epoch-floor 分桶，双后端）。time_col 取白名单，step 经 int。"""
    step = int(step_seconds)
    if vendor == "postgresql":
        return f"to_timestamp(floor(extract(epoch from {time_col})/{step})*{step})"
    # SQLite：``%s`` 与 Django cursor 的 ``%s`` 占位符冲突，需转义为 ``%%s``
    # （Django convert_query 会把 ``%%`` 还原为字面 ``%``）。
    return f"datetime((strftime('%%s',{time_col})/{step})*{step},'unixepoch')"


def _synthetic_where(vendor: str) -> str:
    """synthetic 隔离 WHERE 片段：排除 labels.synthetic=true 行（轮询/health）。"""
    if vendor == "postgresql":
        return " AND (labels->>'synthetic') IS DISTINCT FROM 'true'"
    return " AND json_extract(labels,'$.synthetic') IS NOT 1"


def _dim_sql(dimension: str, allowed: frozenset[str]) -> str:
    """dimension 落到该表实际列才分组；否则退化常量 '__all__'（全量桶）。"""
    return dimension if dimension in allowed else "'__all__'"


def _adapt(dt: datetime) -> Any:
    """datetime → 当前后端可比较的参数值（Postgres datetime / SQLite ISO 串）。"""
    return connection.ops.adapt_datetimefield_value(dt)


def _num(value: Any) -> Any:
    """Decimal → float；其余原样（COUNT/SUM 兼容）。"""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _norm_bucket(value: Any) -> str:
    """桶时间归一化为带时区的 ISO8601（UTC），保证前端按 UTC 解析后再转本地时区。

    - Postgres：``to_timestamp`` 返回 aware datetime → ``isoformat()`` 自带 ``+00:00``。
    - SQLite：``datetime(...,'unixepoch')`` 返回**朴素 UTC 字符串**（``YYYY-MM-DD HH:MM:SS``，
      无时区后缀）。若原样返回，前端 ``new Date(...)`` 会按浏览器**本地时区**解析，导致
      整条趋势横轴整体偏移（如本地 UTC+8 时显示成 UTC 时刻）。故此处显式补 ``+00:00``
      标记为 UTC，由前端 ``toLocaleTimeString`` 统一转本地展示。
    """
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return ""
    # 朴素 UTC 串：空格分隔 → ISO ``T``；无时区后缀（Z/±hh:mm）则补 UTC。
    normalized = text.replace(" ", "T", 1)
    time_part = normalized.split("T", 1)[1] if "T" in normalized else ""
    has_tz = normalized.endswith("Z") or "+" in time_part or "-" in time_part
    if not has_tz:
        normalized += "+00:00"
    return normalized


def _run(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    """执行参数化聚合 SQL，返回 ``[{bucket, dim, value}, ...]``。"""
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    return [
        {"bucket": _norm_bucket(r[0]), "dim": r[1], "value": _num(r[2])}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# 各 metric 聚合分支
# ---------------------------------------------------------------------------


def _query_count(
    *,
    table: str,
    time_col: str,
    start: datetime,
    end: datetime,
    step: int,
    vendor: str,
    dimension: str,
    where_extra: str,
    allowed_dims: frozenset[str],
) -> list[dict[str, Any]]:
    """QPS / 错误计数：每桶 COUNT(*)（按 dimension 分组，时间窗参数化）。"""
    bucket = _bucket_expr(time_col, step, vendor)
    dim = _dim_sql(dimension, allowed_dims)
    sql = (
        f"SELECT {bucket} AS bucket, {dim} AS dim, COUNT(*) AS value "
        f"FROM {table} WHERE {time_col} >= %s AND {time_col} < %s{where_extra} "
        f"GROUP BY bucket, dim ORDER BY bucket"
    )
    return _run(sql, [_adapt(start), _adapt(end)])


def _query_percentile(
    *,
    value_col: str,
    agg: str,
    start: datetime,
    end: datetime,
    step: int,
    vendor: str,
    dimension: str,
    where_extra: str,
    allowed_dims: frozenset[str],
) -> tuple[list[dict[str, Any]], bool, str]:
    """时长/TTFT 分位：Postgres ``percentile_cont`` 精确；SQLite 降级 MAX/AVG 兜底。

    返回 ``(series, degraded, note)``——SQLite 降级时 ``degraded=true`` +
    ``note='sqlite_percentile_approx'`` 让调用方知悉非精确（T-73-02-05）。
    """
    bucket = _bucket_expr("ts", step, vendor)
    dim = _dim_sql(dimension, allowed_dims)
    degraded = False
    note = ""
    if vendor == "postgresql":
        if agg in _PERCENTILE:
            frac = _PERCENTILE[agg]  # 受控 float，不拼用户原文
            value_expr = f"percentile_cont({frac}) WITHIN GROUP (ORDER BY {value_col})"
        elif agg == "avg":
            value_expr = f"AVG({value_col})"
        else:  # max
            value_expr = f"MAX({value_col})"
    else:
        # SQLite dev：无 percentile_cont → 分位降级（p95/p90→MAX、p50→AVG），不阻塞。
        degraded = True
        note = "sqlite_percentile_approx"
        value_expr = f"AVG({value_col})" if agg in ("p50", "avg") else f"MAX({value_col})"
    sql = (
        f"SELECT {bucket} AS bucket, {dim} AS dim, {value_expr} AS value "
        f"FROM request_metrics "
        f"WHERE ts >= %s AND ts < %s AND {value_col} IS NOT NULL{where_extra} "
        f"GROUP BY bucket, dim ORDER BY bucket"
    )
    return _run(sql, [_adapt(start), _adapt(end)]), degraded, note


def _query_sum(
    *,
    start: datetime,
    end: datetime,
    step: int,
    vendor: str,
    dimension: str,
) -> list[dict[str, Any]]:
    """TPS：``ModelUsageRecord``（时间列 ``created_at``）每桶 SUM(total_tokens)。

    按 dimension(provider/call_source/model) 分组；无 synthetic 概念，不排除。
    前端按 step 折算 TPS（token/秒）。
    """
    bucket = _bucket_expr("created_at", step, vendor)
    dim = _dim_sql(dimension, _USAGE_DIMS)
    sql = (
        f"SELECT {bucket} AS bucket, {dim} AS dim, COALESCE(SUM(total_tokens),0) AS value "
        f"FROM model_usage_records WHERE created_at >= %s AND created_at < %s "
        f"GROUP BY bucket, dim ORDER BY bucket"
    )
    return _run(sql, [_adapt(start), _adapt(end)])


def _query_upstream(
    *,
    start: datetime,
    end: datetime,
    step: int,
    vendor: str,
) -> list[dict[str, Any]]:
    """上游错误码分布（SLA-03 查询侧）：``ModelUsageRecord`` 按 ``upstream_status_code``
    分桶计数，dim 收口为 ``429`` / ``529`` / ``other`` 三类常量。

    - 仅统计 ``upstream_status_code IS NOT NULL`` 的行（上游确实返回了 HTTP 码，
      含 429 限流 / 529 过载 / 其它上游错误码；正常调用该列为 null，不计入）。
    - dim 用受控 ``CASE`` 表达式收口为三类常量，无用户原文进 SQL（与 ``_dim_sql`` 同款
      注入面控制）。429/529 单列，其余上游码统一归 ``other``。
    - 时间列 ``created_at``（与 TPS 同源 ``ModelUsageRecord``）；无 synthetic 概念，不排除。
    - best-effort，双后端 ``CASE`` 通用，无 percentile / 自研聚合。
    """
    bucket = _bucket_expr("created_at", step, vendor)
    # 受控 CASE：常量收口为 429/529/other，禁用户原文。
    dim_expr = (
        "CASE WHEN upstream_status_code = 429 THEN '429' "
        "WHEN upstream_status_code = 529 THEN '529' ELSE 'other' END"
    )
    sql = (
        f"SELECT {bucket} AS bucket, {dim_expr} AS dim, COUNT(*) AS value "
        f"FROM model_usage_records "
        f"WHERE created_at >= %s AND created_at < %s AND upstream_status_code IS NOT NULL "
        f"GROUP BY bucket, dim ORDER BY bucket"
    )
    return _run(sql, [_adapt(start), _adapt(end)])


def _query_gauge(
    *,
    name: str,
    agg: str,
    start: datetime,
    end: datetime,
    step: int,
    vendor: str,
) -> list[dict[str, Any]]:
    """gauge 趋势：``GaugeSample`` 按受控 name + 时间桶 AVG/MAX(value)。

    RATE-03 并发/队列深/积压趋势消费此路；分位对 gauge 意义弱，p* 退化 AVG 近似。
    """
    _validate_gauge_name(name)
    bucket = _bucket_expr("ts", step, vendor)
    value_expr = "MAX(value)" if agg == "max" else "AVG(value)"
    sql = (
        f"SELECT {bucket} AS bucket, '__all__' AS dim, {value_expr} AS value "
        f"FROM gauge_samples WHERE ts >= %s AND ts < %s AND name = %s "
        f"GROUP BY bucket, dim ORDER BY bucket"
    )
    return _run(sql, [_adapt(start), _adapt(end), name])


def _query_sla(
    *,
    start: datetime,
    end: datetime,
    step: int,
    vendor: str,
    dimension: str,
) -> list[dict[str, Any]]:
    """SLA-01 可用率/业务故障率：``RequestMetric`` 成功/失败比派生（口径排除业务限制）。

    - 分母 ``eligible``：``error_class != 'business'``（业务限制 LLMBusyError/权限/校验
      **不计入** SLA 分母与故障，per 72 SLA-02 口径 + 73-CONTEXT）。
    - 故障 ``failures``：``error_class IN ('system','upstream')``。
    - ``availability = (eligible - failures) / eligible``（eligible=0 记 None）。
    - ``business_rejected`` 单列（业务故障率单独可见）。
    - synthetic 行（health/poll）排除分母；健康探针来源 = snapshot/health_views，
      不在 SLA 分母重复计（正向可用性信号由前端/74 告警按需叠加）。
    """
    bucket = _bucket_expr("ts", step, vendor)
    dim = _dim_sql(dimension, _REQUEST_DIMS)
    syn = _synthetic_where(vendor)
    sql = (
        f"SELECT {bucket} AS bucket, {dim} AS dim, "
        f"SUM(CASE WHEN error_class != 'business' THEN 1 ELSE 0 END) AS eligible, "
        f"SUM(CASE WHEN error_class IN ('system','upstream') THEN 1 ELSE 0 END) AS failures, "
        f"SUM(CASE WHEN error_class = 'business' THEN 1 ELSE 0 END) AS business_rejected "
        f"FROM request_metrics WHERE ts >= %s AND ts < %s{syn} "
        f"GROUP BY bucket, dim ORDER BY bucket"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [_adapt(start), _adapt(end)])
        rows = cursor.fetchall()
    series: list[dict[str, Any]] = []
    for r in rows:
        eligible = int(r[2] or 0)
        failures = int(r[3] or 0)
        business = int(r[4] or 0)
        availability = round((eligible - failures) / eligible, 6) if eligible > 0 else None
        series.append(
            {
                "bucket": _norm_bucket(r[0]),
                "dim": r[1],
                "availability": availability,
                "eligible": eligible,
                "failures": failures,
                "business_rejected": business,
            }
        )
    return series


# ---------------------------------------------------------------------------
# 统一出口
# ---------------------------------------------------------------------------


def query_timeseries(
    *,
    metric: str,
    start: str | None = None,
    end: str | None = None,
    step: str | None = None,
    dimension: str = "",
    agg: str = "p95",
) -> dict[str, Any]:
    """时序查询统一出口：校验 + 解析 + 按 metric 分派，返回时间桶序列。

    返回 ``{metric, agg, step_seconds, start, end, vendor, degraded, note, series}``。
    校验失败抛 ``ValueError``（中文），由视图转 400。整体经 ``sync_to_async`` 在视图调用。
    """
    metric = (metric or "").strip()
    dimension = (dimension or "").strip()
    agg = _validate(metric, (agg or "p95").strip(), dimension)
    step_seconds = _parse_step(step)
    start_dt, end_dt = _parse_range(start, end)
    step_seconds = _cap_step(start_dt, end_dt, step_seconds)
    vendor = connection.vendor
    syn = _synthetic_where(vendor)

    degraded = False
    note = ""

    if metric.startswith(_GAUGE_PREFIX):
        name = metric[len(_GAUGE_PREFIX) :]
        series = _query_gauge(
            name=name, agg=agg, start=start_dt, end=end_dt, step=step_seconds, vendor=vendor
        )
    elif metric == "qps":
        series = _query_count(
            table="request_metrics",
            time_col="ts",
            start=start_dt,
            end=end_dt,
            step=step_seconds,
            vendor=vendor,
            dimension=dimension,
            where_extra=syn,
            allowed_dims=_REQUEST_DIMS,
        )
    elif metric == "error":
        series = _query_count(
            table="request_metrics",
            time_col="ts",
            start=start_dt,
            end=end_dt,
            step=step_seconds,
            vendor=vendor,
            dimension=dimension or "error_class",
            where_extra=syn,
            allowed_dims=_REQUEST_DIMS,
        )
    elif metric in ("duration", "ttft"):
        value_col = "duration_ms" if metric == "duration" else "ttft_ms"
        series, degraded, note = _query_percentile(
            value_col=value_col,
            agg=agg,
            start=start_dt,
            end=end_dt,
            step=step_seconds,
            vendor=vendor,
            dimension=dimension,
            where_extra=syn,
            allowed_dims=_REQUEST_DIMS,
        )
    elif metric == "tps":
        series = _query_sum(
            start=start_dt, end=end_dt, step=step_seconds, vendor=vendor, dimension=dimension
        )
    elif metric == "upstream":
        series = _query_upstream(
            start=start_dt, end=end_dt, step=step_seconds, vendor=vendor
        )
    elif metric == "sla":
        series = _query_sla(
            start=start_dt, end=end_dt, step=step_seconds, vendor=vendor, dimension=dimension
        )
    else:  # 防御：_validate 已挡，理论不可达
        raise ValueError(f"不支持的 metric：{metric!r}")

    return {
        "metric": metric,
        "agg": agg,
        "step_seconds": step_seconds,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "vendor": vendor,
        "degraded": degraded,
        "note": note,
        "series": series,
    }

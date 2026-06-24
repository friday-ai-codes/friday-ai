"""时序聚合查询服务 + 查询 API 测试（QUERY-01 / SLA-01 / RATE-03 查询侧）。

覆盖：
- 参数解析/校验（``_parse_step`` / ``_parse_range`` / ``_validate`` / ``_cap_step``）；
- 任意 step epoch-floor 分桶（双后端 SQL 片段）；
- QPS/错误计数（synthetic 排除、error_class 三口径）；
- 时长/TTFT 分位（SQLite 降级 degraded 兜底不阻塞）+ null 排除；
- TPS（``ModelUsageRecord.created_at`` 桶 SUM token）+ gauge 趋势（受控名校验）；
- SLA-01 可用率（口径排除业务限制，business 不计故障）；
- 查询 API：超管 200 / 非法 metric 400 中文 / 非超管 403。

约定：DB 读测试用 ``@pytest.mark.django_db``（``query_timeseries`` 为同步 raw cursor，
无需 async 写读跨连接，故不强制 transaction=True；API 测试同 snapshot 范式）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from system import metrics_query
from system.models import GaugeSample, RequestMetric

QUERY_URL = "/api/system/metrics/query/"


# ---------------------------------------------------------------------------
# 参数解析 / 校验（无 DB）
# ---------------------------------------------------------------------------


def test_parse_step_units_and_bounds():
    """step 解析 30s/1m/5m/1h/1d → 秒；非法回默认 60；越界收口到 [10, 86400]。"""
    assert metrics_query._parse_step("30s") == 30
    assert metrics_query._parse_step("1m") == 60
    assert metrics_query._parse_step("5m") == 300
    assert metrics_query._parse_step("1h") == 3600
    assert metrics_query._parse_step("1d") == 86400
    assert metrics_query._parse_step(None) == 60
    assert metrics_query._parse_step("abc") == 60
    assert metrics_query._parse_step("1s") == 10  # 最小 10s
    assert metrics_query._parse_step("2d") == 86400  # 最大 1d


def test_parse_range_defaults_and_fallback():
    """缺省 end=now / start=end-1h；start>=end 回退 end-1h。"""
    start, end = metrics_query._parse_range(None, None)
    assert (end - start) == timedelta(hours=1)

    now = timezone.now()
    s_iso = (now - timedelta(hours=2)).isoformat()
    e_iso = now.isoformat()
    start, end = metrics_query._parse_range(s_iso, e_iso)
    assert (end - start) == timedelta(hours=2)

    # start >= end → 回退 end-1h
    start, end = metrics_query._parse_range(e_iso, s_iso)
    assert start < end


def test_validate_whitelist_and_agg_default():
    """metric/dimension 非法 → ValueError；非法 agg 回 p95；gauge: 前缀放行。"""
    assert metrics_query._validate("qps", "p95", "source") == "p95"
    assert metrics_query._validate("qps", "weird", "") == "p95"  # 非法 agg 兜底
    assert metrics_query._validate("gauge:concurrency.x", "avg", "") == "avg"
    with pytest.raises(ValueError):
        metrics_query._validate("evil", "p95", "")
    with pytest.raises(ValueError):
        metrics_query._validate("qps", "p95", "drop_table")  # 维度非白名单


def test_validate_gauge_name_controlled_prefix():
    """gauge 名仅允许受控前缀；未知名 → ValueError。"""
    assert metrics_query._validate_gauge_name("concurrency.provider_slots")
    assert metrics_query._validate_gauge_name("queue.durable_doing")
    with pytest.raises(ValueError):
        metrics_query._validate_gauge_name("evil.injection")


def test_cap_step_raises_step_over_max_buckets():
    """桶数超 _MAX_BUCKETS → 按比例抬高 step；未超不变。"""
    now = timezone.now()
    start = now - timedelta(days=1)
    # 1d / 10s = 8640 桶 > 2000 → 抬高
    capped = metrics_query._cap_step(start, now, 10)
    assert capped > 10
    # 1h / 60s = 60 桶 < 2000 → 不变
    assert metrics_query._cap_step(now - timedelta(hours=1), now, 60) == 60


def test_bucket_expr_dual_backend():
    """epoch-floor 分桶 SQL 片段：Postgres to_timestamp / SQLite strftime，step 经 int。"""
    pg = metrics_query._bucket_expr("ts", 300, "postgresql")
    assert "to_timestamp" in pg and "300" in pg
    lite = metrics_query._bucket_expr("ts", 300, "sqlite")
    assert "strftime" in lite and "300" in lite


# ---------------------------------------------------------------------------
# DB 造数 helper
# ---------------------------------------------------------------------------


def _mk_request_metric(*, ts, source="rest", error_class="none", duration_ms=None,
                       ttft_ms=None, synthetic=False, route="/x"):
    return RequestMetric.objects.create(
        ts=ts,
        source=source,
        route=route,
        status_code=200,
        error_class=error_class,
        duration_ms=duration_ms,
        ttft_ms=ttft_ms,
        labels={"synthetic": True} if synthetic else {},
    )


# ---------------------------------------------------------------------------
# QPS / 错误计数（synthetic 排除、error_class 三口径）
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_qps_counts_buckets_and_excludes_synthetic():
    """qps 跨两桶计数正确，且 synthetic 行被排除。"""
    now = timezone.now()
    base = now - timedelta(minutes=5)
    # 桶 A：2 业务 + 1 synthetic（应排除）
    _mk_request_metric(ts=base, source="rest")
    _mk_request_metric(ts=base + timedelta(seconds=5), source="rest")
    _mk_request_metric(ts=base + timedelta(seconds=8), source="rest", synthetic=True)
    # 桶 B（+120s）：1 业务
    _mk_request_metric(ts=base + timedelta(seconds=120), source="rest")

    result = metrics_query.query_timeseries(
        metric="qps",
        start=(now - timedelta(minutes=10)).isoformat(),
        end=now.isoformat(),
        step="1m",
    )
    total = sum(p["value"] for p in result["series"])
    assert total == 3  # synthetic 不计：2 + 1
    assert len(result["series"]) >= 2  # 至少两桶


@pytest.mark.django_db
def test_error_groups_by_error_class():
    """error 按 error_class 分组计数（business 单列）。"""
    now = timezone.now()
    base = now - timedelta(minutes=3)
    _mk_request_metric(ts=base, error_class="none")
    _mk_request_metric(ts=base + timedelta(seconds=2), error_class="business")
    _mk_request_metric(ts=base + timedelta(seconds=3), error_class="business")
    _mk_request_metric(ts=base + timedelta(seconds=4), error_class="system")

    result = metrics_query.query_timeseries(
        metric="error",
        start=(now - timedelta(minutes=10)).isoformat(),
        end=now.isoformat(),
        step="1h",  # 单桶，聚焦 error_class 分组
    )
    by_class = {p["dim"]: p["value"] for p in result["series"]}
    assert by_class.get("business") == 2
    assert by_class.get("none") == 1
    assert by_class.get("system") == 1


# ---------------------------------------------------------------------------
# 分位时长/TTFT（SQLite 降级）+ null 排除
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_duration_percentile_degrades_on_sqlite():
    """duration p95：Postgres 精确 percentile_cont；SQLite degraded=true 用 MAX 兜底。"""
    from django.db import connection

    now = timezone.now()
    base = now - timedelta(minutes=2)
    _mk_request_metric(ts=base, duration_ms=100)
    _mk_request_metric(ts=base + timedelta(seconds=1), duration_ms=300)

    result = metrics_query.query_timeseries(
        metric="duration",
        agg="p95",
        start=(now - timedelta(minutes=10)).isoformat(),
        end=now.isoformat(),
        step="1h",
    )
    if connection.vendor == "postgresql":
        assert result["degraded"] is False
    else:
        assert result["degraded"] is True
        assert result["note"] == "sqlite_percentile_approx"
        # SQLite p95 降级 MAX → 300
        assert result["series"][0]["value"] == 300


@pytest.mark.django_db
def test_duration_excludes_null_value_rows():
    """duration 查询 value_col 为 null 的行被 WHERE 排除。"""
    now = timezone.now()
    base = now - timedelta(minutes=2)
    _mk_request_metric(ts=base, duration_ms=None)  # 应被排除
    _mk_request_metric(ts=base + timedelta(seconds=1), duration_ms=250)

    result = metrics_query.query_timeseries(
        metric="duration",
        agg="max",
        start=(now - timedelta(minutes=10)).isoformat(),
        end=now.isoformat(),
        step="1h",
    )
    assert len(result["series"]) == 1
    assert result["series"][0]["value"] == 250


# ---------------------------------------------------------------------------
# TPS（ModelUsageRecord.created_at 桶 SUM token）+ gauge 趋势
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tps_sum_tokens_by_provider():
    """tps 按 provider 分组 SUM(total_tokens)（时间列 created_at）。"""
    from interactions.models import ModelUsageRecord

    ModelUsageRecord.objects.create(provider="openai", model="gpt", total_tokens=100)
    ModelUsageRecord.objects.create(provider="openai", model="gpt", total_tokens=50)
    ModelUsageRecord.objects.create(provider="anthropic", model="claude", total_tokens=30)

    now = timezone.now()
    result = metrics_query.query_timeseries(
        metric="tps",
        dimension="provider",
        start=(now - timedelta(minutes=10)).isoformat(),
        end=(now + timedelta(minutes=1)).isoformat(),
        step="1h",
    )
    by_provider = {p["dim"]: p["value"] for p in result["series"]}
    assert by_provider.get("openai") == 150
    assert by_provider.get("anthropic") == 30


@pytest.mark.django_db
def test_gauge_trend_avg_and_unknown_name():
    """gauge:<name> avg 趋势正确；未知 gauge name → ValueError。"""
    now = timezone.now()
    base = now - timedelta(minutes=2)
    GaugeSample.objects.create(ts=base, name="concurrency.provider_slots", value=2.0)
    GaugeSample.objects.create(ts=base + timedelta(seconds=1), name="concurrency.provider_slots", value=4.0)

    result = metrics_query.query_timeseries(
        metric="gauge:concurrency.provider_slots",
        agg="avg",
        start=(now - timedelta(minutes=10)).isoformat(),
        end=now.isoformat(),
        step="1h",
    )
    assert result["series"][0]["value"] == 3.0  # (2+4)/2

    with pytest.raises(ValueError):
        metrics_query.query_timeseries(metric="gauge:evil.injection")


# ---------------------------------------------------------------------------
# SLA-01 可用率（排除业务限制）
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sla_availability_excludes_business():
    """sla：business 不进分母/不计故障；availability=(eligible-failures)/eligible。"""
    now = timezone.now()
    base = now - timedelta(minutes=3)
    # eligible = none(2) + system(1) + upstream(1) = 4；failures = system+upstream = 2
    # business(1) 不进分母、单列 business_rejected
    _mk_request_metric(ts=base, error_class="none")
    _mk_request_metric(ts=base + timedelta(seconds=1), error_class="none")
    _mk_request_metric(ts=base + timedelta(seconds=2), error_class="system")
    _mk_request_metric(ts=base + timedelta(seconds=3), error_class="upstream")
    _mk_request_metric(ts=base + timedelta(seconds=4), error_class="business")

    result = metrics_query.query_timeseries(
        metric="sla",
        start=(now - timedelta(minutes=10)).isoformat(),
        end=now.isoformat(),
        step="1h",
    )
    row = result["series"][0]
    assert row["eligible"] == 4
    assert row["failures"] == 2
    assert row["business_rejected"] == 1
    assert row["availability"] == 0.5  # (4-2)/4


# ---------------------------------------------------------------------------
# 查询 API（IsSuperUser fail-closed + 非法 400 中文）
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMetricsQueryView:
    def test_superuser_qps_query_ok(self, api_client, admin_user):
        """超管 GET ?metric=qps&step=1m → 200 + series 序列。"""
        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(QUERY_URL, {"metric": "qps", "step": "1m"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["metric"] == "qps"
        assert data["step_seconds"] == 60
        assert "series" in data
        assert "vendor" in data

    def test_invalid_metric_returns_400(self, api_client, admin_user):
        """非法 metric → 400 + 中文 detail。"""
        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(QUERY_URL, {"metric": "evil"})
        assert resp.status_code == 400
        assert "metric" in resp.json()["detail"]

    def test_non_superuser_forbidden(self, api_client, user):
        """非超管 → 403（IsSuperUser fail-closed）。"""
        api_client.force_authenticate(user=user)
        resp = api_client.get(QUERY_URL, {"metric": "qps"})
        assert resp.status_code == 403

    def test_anonymous_forbidden(self, api_client):
        """未认证 → 401/403。"""
        resp = api_client.get(QUERY_URL, {"metric": "qps"})
        assert resp.status_code in (401, 403)

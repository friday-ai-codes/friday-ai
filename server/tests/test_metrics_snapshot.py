"""快照采集器 + 快照 API 测试（SNAP-01~05 / QUERY-02）。

覆盖：
- 各源 best-effort（host/db/redis/qdrant/concurrency），异常局部降级不冒泡；
- Qdrant 缓存 + ping 不健康不枚举（硬约束）；
- collect_snapshot 聚合器单源失败不拖垮整体；
- 快照 API IsSuperUser fail-closed + synthetic 隔离。

约定：任何 async DB 读测试用 ``@pytest.mark.django_db(transaction=True)``，
避免跨 async 连接行泄漏（per 73-CONTEXT）。
"""

from __future__ import annotations

import pytest

from system import snapshot_service

SNAPSHOT_URL = "/api/system/metrics/snapshot/"


# ---------------------------------------------------------------------------
# SNAP-01：host
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_collect_host_snapshot_available():
    """host 源返回 available=true + CPU/内存/协程/线程/后台任务计数。"""
    data = await snapshot_service.collect_host_snapshot()
    assert data["available"] is True
    assert "cpu_percent" in data
    assert "mem_percent" in data
    assert "mem_total_mb" in data
    # async 测试内事件循环存在 → 协程数非 None
    assert data["asyncio_tasks"] is not None
    assert isinstance(data["threads"], int)
    assert isinstance(data["background_tasks"], dict)


@pytest.mark.asyncio
async def test_collect_host_snapshot_psutil_failure_degrades(monkeypatch):
    """monkeypatch psutil.cpu_percent 抛错 → host 源 available=false，不冒泡。"""
    import psutil

    def _boom(*args, **kwargs):
        raise RuntimeError("psutil boom")

    monkeypatch.setattr(psutil, "cpu_percent", _boom)
    data = await snapshot_service.collect_host_snapshot()
    assert data["available"] is False
    assert "psutil boom" in data["error"]


# ---------------------------------------------------------------------------
# SNAP-02：db（SQLite 优雅降级）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_collect_db_snapshot_sqlite_degrades():
    """测试 DB（SQLite）下 db 源 available=false + error 含 sqlite，不抛。"""
    data = await snapshot_service.collect_db_snapshot()
    assert data["available"] is False
    assert "sqlite" in data["error"].lower()
    assert data["vendor"] != "postgresql"


# ---------------------------------------------------------------------------
# SNAP-03：redis（未配置降级 + 命中率计算）
# ---------------------------------------------------------------------------


class _FakeRedis:
    """伪 redis.asyncio 客户端：只实现 info()/aclose()。"""

    def __init__(self, info: dict):
        self._info = info
        self.closed = False

    async def info(self, *args, **kwargs):
        return self._info

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_collect_redis_snapshot_not_configured(monkeypatch):
    """测试环境未配置 redis（各 URL 空）→ 各路 not_configured，不抛。"""
    from django.conf import settings

    monkeypatch.setattr(settings, "CACHE_REDIS_URL", "", raising=False)
    monkeypatch.setattr(settings, "USE_REDIS_CHANNEL_LAYER", False, raising=False)
    monkeypatch.setattr(settings, "LLM_CONCURRENCY_REDIS_URL", "", raising=False)

    data = await snapshot_service.collect_redis_snapshot()
    assert data["available"] is False
    for name in ("cache", "channels", "llm"):
        assert data["clients"][name]["error"] == "not_configured"


@pytest.mark.asyncio
async def test_collect_redis_snapshot_hit_rate(monkeypatch):
    """mock fake redis INFO → 命中率 = hits/(hits+misses) 计算正确。"""
    import redis.asyncio as aioredis
    from django.conf import settings

    monkeypatch.setattr(settings, "CACHE_REDIS_URL", "redis://fake:6379/0", raising=False)
    monkeypatch.setattr(settings, "USE_REDIS_CHANNEL_LAYER", False, raising=False)
    monkeypatch.setattr(settings, "LLM_CONCURRENCY_REDIS_URL", "", raising=False)

    fake = _FakeRedis(
        {
            "connected_clients": 3,
            "maxclients": 100,
            "used_memory": 1024,
            "used_memory_human": "1.00K",
            "keyspace_hits": 8,
            "keyspace_misses": 2,
        }
    )
    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: fake)

    data = await snapshot_service.collect_redis_snapshot()
    assert data["available"] is True
    cache_client = data["clients"]["cache"]
    assert cache_client["available"] is True
    assert cache_client["connected_clients"] == 3
    assert cache_client["hit_rate"] == 0.8
    assert fake.closed is True  # 用完释放，无连接泄漏


# ---------------------------------------------------------------------------
# SNAP-04：qdrant（ping 不健康不枚举 + 缓存命中）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collect_qdrant_unhealthy_skips_enumeration(monkeypatch):
    """ping 不健康 → available=false 且**不调** _enumerate_qdrant（硬约束）。"""
    from services.qdrant_service import QdrantService

    monkeypatch.setattr(
        QdrantService, "ping_liveness", classmethod(lambda cls: {"status": "unhealthy", "error": "down"})
    )

    called = {"n": 0}

    def _spy():
        called["n"] += 1
        return {"collection_count": 0, "approx_size": None}

    monkeypatch.setattr(snapshot_service, "_enumerate_qdrant", _spy)

    data = await snapshot_service.collect_qdrant_snapshot()
    assert data["available"] is False
    assert data["liveness"] is False
    assert called["n"] == 0  # 枚举未触发


@pytest.mark.asyncio
async def test_collect_qdrant_healthy_enumerates_then_caches(monkeypatch):
    """ping 健康 → 首次枚举得 collection_count；二次命中缓存（枚举只调一次）。"""
    from django.core.cache import cache

    from services.qdrant_service import QdrantService

    await cache.adelete(snapshot_service._QDRANT_CACHE_KEY)
    monkeypatch.setattr(
        QdrantService, "ping_liveness", classmethod(lambda cls: {"status": "healthy"})
    )

    called = {"n": 0}

    def _enum():
        called["n"] += 1
        return {"collection_count": 7, "approx_size": {"sampled_collections": 7}}

    monkeypatch.setattr(snapshot_service, "_enumerate_qdrant", _enum)

    first = await snapshot_service.collect_qdrant_snapshot()
    assert first["available"] is True
    assert first["collection_count"] == 7
    assert first["cached"] is False

    second = await snapshot_service.collect_qdrant_snapshot()
    assert second["collection_count"] == 7
    assert second["cached"] is True
    assert called["n"] == 1  # 第二次命中缓存，枚举只调一次

    await cache.adelete(snapshot_service._QDRANT_CACHE_KEY)


# ---------------------------------------------------------------------------
# SNAP-05：concurrency（provider 槽位 + durable/runner SQLite 降级）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_collect_concurrency_provider_slots(monkeypatch):
    """造 ProviderCredential + mock 进程内信号量 → provider_slots 含 in_use；
    durable/runner 在 SQLite 降级为空不抛。"""
    import asyncio as _asyncio

    from asgiref.sync import sync_to_async
    from django.conf import settings

    from agents import llm_concurrency
    from system.models import ProviderCredential

    monkeypatch.setattr(settings, "LLM_CONCURRENCY_REDIS_URL", "", raising=False)

    cred = await sync_to_async(ProviderCredential.objects.create)(
        provider_type="anthropic",
        name="snap-test",
        encrypted_config="",
        is_active=True,
        max_concurrency=50,
    )
    # 模拟进程内信号量：容量 50，已占 2（_value=48）。
    sem = _asyncio.Semaphore(50)
    await sem.acquire()
    await sem.acquire()
    llm_concurrency._inprocess_semaphores[str(cred.id)] = (sem, 50)

    try:
        data = await snapshot_service.collect_concurrency_snapshot()
    finally:
        llm_concurrency._inprocess_semaphores.pop(str(cred.id), None)

    assert data["available"] is True
    slots = data["provider_slots"]
    assert isinstance(slots, list)
    match = [s for s in slots if s["credential_id"] == str(cred.id)]
    assert match and match[0]["in_use"] == 2
    assert match[0]["max"] == 50
    # durable/runner 在 SQLite 下降级为空结构，不抛
    assert isinstance(data["durable_queues"], dict)
    assert isinstance(data["runner"], dict)
    assert data["rag"]["available"] is False


# ---------------------------------------------------------------------------
# 聚合器：单源失败局部降级
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_collect_snapshot_partial_degradation(monkeypatch):
    """某源抛错 → 该源 available=false，其余源正常返回（局部降级）。"""

    async def _boom():
        raise RuntimeError("host exploded")

    monkeypatch.setattr(snapshot_service, "collect_host_snapshot", _boom)

    data = await snapshot_service.collect_snapshot()
    assert data["host"]["available"] is False
    assert "host exploded" in data["host"]["error"]
    # 其余源仍返回 envelope（db SQLite 降级 available=false 但结构完整）
    for key in ("db", "redis", "qdrant", "concurrency"):
        assert key in data
        assert "available" in data[key]
    assert "generated_at" in data


# ---------------------------------------------------------------------------
# QUERY-02：快照 API（IsSuperUser fail-closed + synthetic 隔离）
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMetricsSnapshotView:
    def test_superuser_aggregated_payload(self, api_client, admin_user):
        """超管 GET → 200 + 含 host/db/redis/qdrant/concurrency/generated_at + counters。"""
        api_client.force_authenticate(user=admin_user)
        resp = api_client.get(SNAPSHOT_URL)
        assert resp.status_code == 200
        data = resp.json()
        for key in (
            "host",
            "db",
            "redis",
            "qdrant",
            "concurrency",
            "generated_at",
            "counters",
        ):
            assert key in data, f"缺少顶层字段 {key}"
        assert "available" in data["host"]

    def test_non_superuser_forbidden(self, api_client, user):
        """非超管 → 403（IsSuperUser fail-closed）。"""
        api_client.force_authenticate(user=user)
        resp = api_client.get(SNAPSHOT_URL)
        assert resp.status_code == 403

    def test_anonymous_forbidden(self, api_client):
        """未认证 → 401/403。"""
        resp = api_client.get(SNAPSHOT_URL)
        assert resp.status_code in (401, 403)


def test_metrics_route_marked_synthetic():
    """中间件 _is_synthetic 命中 /api/system/metrics 前缀（synthetic 隔离断言）。"""
    from common.middleware import _is_synthetic

    assert _is_synthetic(SNAPSHOT_URL) is True
    assert _is_synthetic("/api/system/metrics/query/") is True

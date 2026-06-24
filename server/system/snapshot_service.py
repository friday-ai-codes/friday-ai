"""快照采集器（SNAP-01~05）——"只看当前"的单一聚合器。

把 server 进程主机负载（CPU/内存/协程/线程/后台任务）、DB 连接、Redis 多路、
Qdrant 可用性/collection、并发排队五源的**当前值**一次取齐。设计红线：

- **各源独立 best-effort**：每个 ``collect_*_snapshot`` 整函数 ``try/except`` 兜底，
  异常只让该源返回 ``{"available": False, "error": ...}``，**绝不抛、绝不反噬业务**
  （观测代码永不打断主流程，per observability-logging 规范）。
- **统一 envelope**：每源返回 ``{"available": bool, "error": str, ...data}``。
- **超时纪律**：每源用 ``asyncio.wait_for`` 包裹防永久挂起；Qdrant 枚举段用长超时
  + 缓存（TTL~60s），ping 段用短超时（硬约束，避免高频枚举拖垮 Qdrant）。
- 最大化复用既有探针/聚合范式（``health_views`` ping、``observability_views``
  durable/subagent/runtime 聚合、``llm_concurrency`` 槽位），不另造轮子。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.utils import timezone

logger = structlog.get_logger(__name__)

# 各源采集超时（秒）：快路径（ping/INFO/本地内省）短超时；
# Qdrant collection 枚举走长超时（重操作，硬约束避免拖垮但也不能永久挂起）。
SOURCE_TIMEOUT_FAST = 3.0
SOURCE_TIMEOUT_SLOW = 8.0


# ---------------------------------------------------------------------------
# SNAP-01：server 主机负载（CPU/内存/协程/线程/后台任务）
# ---------------------------------------------------------------------------


def _collect_background_tasks() -> dict[str, Any]:
    """后台（异步）任务计数：复用 observability_views 已有聚合口径（DRY，不重写）。

    在 sync 线程内调用（经 sync_to_async 桥接）：durable todo+doing / subagent
    active / orchestration active。procrastinate 表缺失 / 模型未迁移时各自降级为空。
    """
    from system.observability_views import (
        _background_task_summary,
        _durable_queue_stats,
        _orchestration_stats,
        _subagent_stats,
    )

    durable = _durable_queue_stats()
    try:
        subagent = _subagent_stats()
    except Exception:  # noqa: BLE001 — 子聚合失败降级空，不拖垮主机源
        subagent = {"active": []}
    try:
        orchestration = _orchestration_stats()
    except Exception:  # noqa: BLE001
        orchestration = {}
    return _background_task_summary(durable, subagent, orchestration)


async def collect_host_snapshot() -> dict[str, Any]:
    """SNAP-01：主机/进程运行时快照——CPU/内存(psutil) + 协程数 + 线程数 + 后台任务数。

    ``asyncio.all_tasks()`` **必须在事件循环线程内调用**（不进 sync_to_async 的线程池），
    才能拿到当前 loop 的协程数（参考 observability_views._runtime_stats）；
    非循环上下文降级 None。psutil 不可用/异常 → ``available=False``。
    """
    try:
        import psutil

        # interval=None 取自上次调用以来的瞬时占用（非阻塞）。
        cpu_percent = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        mem_total_mb = round(vm.total / (1024 * 1024), 1)
        mem_used_mb = round(vm.used / (1024 * 1024), 1)
        mem_percent = vm.percent

        try:
            asyncio_tasks: int | None = len(asyncio.all_tasks())
        except RuntimeError:
            asyncio_tasks = None

        threads = threading.active_count()

        try:
            background_tasks = await asyncio.wait_for(
                sync_to_async(_collect_background_tasks, thread_sensitive=True)(),
                timeout=SOURCE_TIMEOUT_FAST,
            )
        except Exception:  # noqa: BLE001 — 后台计数失败不拖垮主机源
            background_tasks = {}

        return {
            "available": True,
            "error": "",
            "cpu_percent": cpu_percent,
            "mem_total_mb": mem_total_mb,
            "mem_used_mb": mem_used_mb,
            "mem_percent": mem_percent,
            "asyncio_tasks": asyncio_tasks,
            "threads": threads,
            "background_tasks": background_tasks,
        }
    except Exception as exc:  # noqa: BLE001 — best-effort：整源失败局部降级
        logger.warning(
            "snapshot_host_failed",
            error=str(exc),
            category="sampling",
            component="metrics",
        )
        return {"available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# SNAP-02：DB 连接（PG pg_stat_activity + max_connections + 池 + PgBouncer）
# ---------------------------------------------------------------------------


def _query_pg_connections(cursor) -> dict[str, Any]:
    """pg_stat_activity 按 state 聚合 + 等待连接数（独立 try/except 包裹由调用方控制）。"""
    cursor.execute("SELECT state, count(*) FROM pg_stat_activity GROUP BY state")
    by_state: dict[str, int] = {}
    for state, count in cursor.fetchall():
        by_state[str(state) if state is not None else "unknown"] = int(count)
    total = sum(by_state.values())
    return {
        "total": total,
        "active": by_state.get("active", 0),
        "idle": by_state.get("idle", 0),
        "idle_in_transaction": by_state.get("idle in transaction", 0),
    }


def _collect_db_sync() -> dict[str, Any]:
    """Postgres DB 快照（在 sync 线程内执行）：连接分布 + max_connections + 池 + PgBouncer。

    每个子查询独立 try/except，单查询失败不拖垮整源。
    """
    from django.conf import settings
    from django.db import connections

    conn = connections["default"]

    connections_stat: dict[str, Any] = {}
    waiting: int | None = None
    max_connections: int | None = None
    try:
        conn.ensure_connection()
        with conn.cursor() as cursor:
            try:
                connections_stat = _query_pg_connections(cursor)
            except Exception:  # noqa: BLE001
                connections_stat = {}
            try:
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE wait_event IS NOT NULL"
                )
                row = cursor.fetchone()
                waiting = int(row[0]) if row else None
            except Exception:  # noqa: BLE001
                waiting = None
            try:
                cursor.execute("SHOW max_connections")
                row = cursor.fetchone()
                max_connections = int(row[0]) if row else None
            except Exception:  # noqa: BLE001
                max_connections = None
    except Exception:  # noqa: BLE001 — 连接级失败：connections/waiting 留空，仍尝试池/pgbouncer
        pass

    if waiting is not None:
        connections_stat["waiting"] = waiting

    # psycopg 应用层池 get_stats()（Django 5.1 原生 OPTIONS["pool"] 注入）——独立兜底。
    pool: dict[str, Any] | None = None
    try:
        raw_pool = getattr(conn, "pool", None) or getattr(conn, "connection_pool", None)
        if raw_pool is not None and hasattr(raw_pool, "get_stats"):
            pool = dict(raw_pool.get_stats())
    except Exception:  # noqa: BLE001 — 池不可用不影响 pg_stat_activity 结果
        pool = None

    # PgBouncer SHOW POOLS（opt-in：仅 DB_PGBOUNCER 为真时尝试）。
    pgbouncer: dict[str, Any] | None = None
    if getattr(settings, "DB_PGBOUNCER", False):
        try:
            with conn.cursor() as cursor:
                cursor.execute("SHOW POOLS")
                cols = [c[0] for c in cursor.description] if cursor.description else []
                rows = [dict(zip(cols, r, strict=False)) for r in cursor.fetchall()]
                pgbouncer = {"pools": rows}
        except Exception:  # noqa: BLE001 — PgBouncer 不可用降级
            pgbouncer = None

    return {
        "available": True,
        "error": "",
        "vendor": "postgresql",
        "connections": connections_stat,
        "max_connections": max_connections,
        "pool": pool,
        "pgbouncer": pgbouncer,
    }


async def collect_db_snapshot() -> dict[str, Any]:
    """SNAP-02：DB 连接快照。

    **SQLite dev 优雅降级**：``vendor != "postgresql"`` → ``available=False`` +
    ``error="n/a (sqlite dev)"``（不报错，per 73-CONTEXT §A.4）。
    Postgres → pg_stat_activity 连接分布 + max_connections + psycopg 池 + PgBouncer(opt-in)。
    """
    try:
        from django.db import connections

        vendor = connections["default"].vendor
        if vendor != "postgresql":
            return {
                "available": False,
                "error": "n/a (sqlite dev)",
                "vendor": vendor,
            }
        return await asyncio.wait_for(
            sync_to_async(_collect_db_sync, thread_sensitive=True)(),
            timeout=SOURCE_TIMEOUT_FAST,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort 局部降级
        logger.warning(
            "snapshot_db_failed",
            error=str(exc),
            category="sampling",
            component="metrics",
        )
        return {"available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# SNAP-03：Redis 多路（cache / channels / llm，去重相同 URL）
# ---------------------------------------------------------------------------


async def _probe_redis(url: str) -> dict[str, Any]:
    """对单个 Redis URL 取 INFO + 命中率。按需创建 client，用完 ``aclose()`` 释放。

    **绝不**把 client 缓存进模块全局长持（避免连接泄漏，T-73-01-05）。
    """
    import redis.asyncio as aioredis

    client = aioredis.from_url(url, decode_responses=True)
    try:
        info = await asyncio.wait_for(client.info(), timeout=SOURCE_TIMEOUT_FAST)
        maxclients = info.get("maxclients")
        if maxclients is None:
            try:
                cfg = await asyncio.wait_for(
                    client.config_get("maxclients"), timeout=SOURCE_TIMEOUT_FAST
                )
                maxclients = cfg.get("maxclients") if isinstance(cfg, dict) else None
            except Exception:  # noqa: BLE001 — maxclients 取不到记 None
                maxclients = None
        hits = info.get("keyspace_hits")
        misses = info.get("keyspace_misses")
        hit_rate: float | None = None
        if hits is not None and misses is not None:
            total = int(hits) + int(misses)
            hit_rate = round(int(hits) / total, 4) if total > 0 else None
        return {
            "available": True,
            "error": "",
            "connected_clients": info.get("connected_clients"),
            "maxclients": int(maxclients) if maxclients is not None else None,
            "used_memory": info.get("used_memory"),
            "used_memory_human": info.get("used_memory_human"),
            "keyspace_hits": hits,
            "keyspace_misses": misses,
            "hit_rate": hit_rate,
        }
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 — 释放失败不影响结果
            pass


async def collect_redis_snapshot() -> dict[str, Any]:
    """SNAP-03：覆盖 cache / channels / llm 三路 Redis（去重相同 URL）。

    未配置某路（url 空）→ 该路 ``{"available": False, "error": "not_configured"}``，
    不算整源失败。逐路独立 try/except，单路失败不拖垮其它路。
    """
    try:
        from django.conf import settings

        use_channel_redis = getattr(settings, "USE_REDIS_CHANNEL_LAYER", False)
        routes = {
            "cache": getattr(settings, "CACHE_REDIS_URL", "") or "",
            "channels": (
                getattr(settings, "REDIS_CHANNEL_LAYER_URL", "") or ""
                if use_channel_redis
                else ""
            ),
            "llm": getattr(settings, "LLM_CONCURRENCY_REDIS_URL", "") or "",
        }

        clients: dict[str, Any] = {}
        # 去重：多路常指同一 Redis，按 url 只 INFO 一次。
        url_results: dict[str, dict[str, Any]] = {}
        for name, url in routes.items():
            if not url:
                clients[name] = {"available": False, "error": "not_configured"}
                continue
            if url not in url_results:
                try:
                    url_results[url] = await _probe_redis(url)
                except Exception as exc:  # noqa: BLE001 — 单路失败降级
                    url_results[url] = {"available": False, "error": str(exc)}
            clients[name] = url_results[url]

        available = any(c.get("available") for c in clients.values())
        return {"available": available, "error": "", "clients": clients}
    except Exception as exc:  # noqa: BLE001 — best-effort 局部降级
        logger.warning(
            "snapshot_redis_failed",
            error=str(exc),
            category="sampling",
            component="metrics",
        )
        return {"available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# SNAP-04：Qdrant（可用性 ping + collection 枚举，缓存 TTL~60s + 长超时，硬约束）
# ---------------------------------------------------------------------------

# 枚举段缓存：避免高频 get_collections 拖垮 Qdrant（一仓一 collection 时遍历数百个）。
_QDRANT_CACHE_KEY = "system:qdrant:snapshot:v1"
_QDRANT_CACHE_TTL = 60
# 占用空间采样：最多读前 N 个 collection 的 points_count，避免遍历全部拖垮。
_QDRANT_SIZE_SAMPLE_LIMIT = 20


def _enumerate_qdrant() -> dict[str, Any]:
    """枚举 collection 数 + 占用（重操作，在 sync 线程内执行）。

    复用 ``QdrantService`` 缓存 client（**绝不** reset，per health_check 不变量注释）。
    占用空间 best-effort：仅采样前 N 个 collection 的 points_count，取不到记 None。
    """
    from services.qdrant_service import QdrantService

    client = QdrantService.get_client()
    info = client.get_collections()
    names = [c.name for c in info.collections]
    collection_count = len(names)

    approx_size: dict[str, Any] | None = None
    try:
        sampled = 0
        points_total = 0
        for name in names[:_QDRANT_SIZE_SAMPLE_LIMIT]:
            try:
                detail = client.get_collection(name)
                pc = getattr(detail, "points_count", None)
                if pc is not None:
                    points_total += int(pc)
                    sampled += 1
            except Exception:  # noqa: BLE001 — 单 collection 取不到跳过
                continue
        approx_size = {
            "sampled_collections": sampled,
            "points_count_sampled": points_total,
            "truncated": collection_count > _QDRANT_SIZE_SAMPLE_LIMIT,
        }
    except Exception:  # noqa: BLE001 — 占用取不到记 None，不强求精确
        approx_size = None

    return {"collection_count": collection_count, "approx_size": approx_size}


async def collect_qdrant_snapshot() -> dict[str, Any]:
    """SNAP-04：Qdrant 可用性 + collection 数/占用（缓存 + 长超时，ping 不健康不枚举）。

    分两段：
    - **可用性（快）**：``ping_liveness``（GET /healthz）在 fast 超时内；不健康直接返回，
      **不再枚举 collection**（硬约束）。
    - **collection 枚举（重）**：先读缓存（TTL~60s），未命中再 ``_enumerate_qdrant``
      在 slow 超时内枚举并写缓存。liveness 与 enumerated 两段解耦，任一段失败另一段仍返回。
    """
    try:
        from django.core.cache import cache

        from services.qdrant_service import QdrantService

        # 段一：liveness（快）。
        try:
            liveness = await asyncio.wait_for(
                sync_to_async(QdrantService.ping_liveness, thread_sensitive=False)(),
                timeout=SOURCE_TIMEOUT_FAST,
            )
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": str(exc), "liveness": False}

        if liveness.get("status") != "healthy":
            return {
                "available": False,
                "error": str(liveness.get("error") or "unhealthy"),
                "liveness": False,
            }

        # 段二：collection 枚举（重，带缓存）。
        cached = await cache.aget(_QDRANT_CACHE_KEY)
        if cached is not None:
            return {
                "available": True,
                "error": "",
                "liveness": True,
                "cached": True,
                **cached,
            }

        try:
            enum = await asyncio.wait_for(
                sync_to_async(_enumerate_qdrant, thread_sensitive=False)(),
                timeout=SOURCE_TIMEOUT_SLOW,
            )
        except Exception as exc:  # noqa: BLE001 — liveness 仍健康，仅枚举失败
            return {
                "available": True,
                "error": str(exc),
                "liveness": True,
                "cached": False,
                "collection_count": None,
                "approx_size": None,
            }

        await cache.aset(_QDRANT_CACHE_KEY, enum, _QDRANT_CACHE_TTL)
        return {
            "available": True,
            "error": "",
            "liveness": True,
            "cached": False,
            **enum,
        }
    except Exception as exc:  # noqa: BLE001 — best-effort 局部降级
        logger.warning(
            "snapshot_qdrant_failed",
            error=str(exc),
            category="sampling",
            component="metrics",
        )
        return {"available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# SNAP-05：并发 / 排队（provider 槽位 / durable / runner / RAG）
# ---------------------------------------------------------------------------


async def _collect_provider_slots() -> list[dict[str, Any]]:
    """各活跃 ProviderCredential 的当前并发槽位占用。

    配置了 ``LLM_CONCURRENCY_REDIS_URL`` → 对每凭证 ``_slot_key`` 先清过期租约再
    ``ZCARD`` 得占用（per llm_concurrency Lua 语义）；否则读进程内信号量内省
    （``capacity - sem._value``）。Redis 故障逐凭证降级 ``in_use=None``。
    """
    import time

    from django.conf import settings

    from agents import llm_concurrency
    from system.models import ProviderCredential

    url = getattr(settings, "LLM_CONCURRENCY_REDIS_URL", "") or ""
    lease_ttl = float(getattr(settings, "LLM_CONCURRENCY_LEASE_TTL_SECONDS", 900))

    creds: list[dict[str, Any]] = []
    async for c in ProviderCredential.objects.filter(
        is_active=True, max_concurrency__gt=0
    ).values("id", "provider_type", "max_concurrency"):
        creds.append(c)

    redis_client = None
    if url:
        try:
            redis_client = llm_concurrency._get_redis_client(url)
        except Exception:  # noqa: BLE001 — Redis 不可用则逐凭证降级
            redis_client = None

    slots: list[dict[str, Any]] = []
    for c in creds:
        cid = str(c["id"])
        maxc = int(c["max_concurrency"])
        in_use: int | None = None
        if redis_client is not None:
            try:
                key = llm_concurrency._slot_key(cid)
                now_ms = int(time.time() * 1000)
                await redis_client.zremrangebyscore(key, "-inf", now_ms - int(lease_ttl * 1000))
                in_use = int(await redis_client.zcard(key))
            except Exception:  # noqa: BLE001 — 单凭证读取失败降级
                in_use = None
        else:
            existing = llm_concurrency._inprocess_semaphores.get(cid)
            if existing is not None:
                sem, capacity = existing
                in_use = max(capacity - sem._value, 0)
            else:
                in_use = 0
        slots.append(
            {
                "credential_id": cid,
                "provider": c["provider_type"],
                "max": maxc,
                "in_use": in_use,
            }
        )
    return slots


def _collect_runner_stats() -> dict[str, Any]:
    """runner 待派发 / 本地队列：RunnerTaskAssignment 按 status 计数 + 活跃 Runner 汇总。

    注：实际 ``RunnerTaskAssignment.Status`` 为 assigned/running/completed/failed
    （无 pending/dispatched）；Runner 容量字段为 ``concurrent``（非 max_concurrent）。
    """
    from django.db.models import Count, Sum

    from runners.models import Runner, RunnerTaskAssignment

    assignments = {
        str(row["status"]): int(row["n"])
        for row in RunnerTaskAssignment.objects.values("status")
        .annotate(n=Count("id"))
        .order_by()
    }
    agg = Runner.objects.filter(is_active=True).aggregate(
        current=Sum("current_tasks"),
        capacity=Sum("concurrent"),
        runners=Count("id"),
    )
    return {
        "assignments_by_status": assignments,
        "current_tasks": int(agg["current"] or 0),
        "capacity": int(agg["capacity"] or 0),
        "active_runners": int(agg["runners"] or 0),
    }


async def collect_concurrency_snapshot() -> dict[str, Any]:
    """SNAP-05：并发/排队当前值——provider 槽位 / durable / runner / RAG。四块独立 try/except。"""
    try:
        from system.observability_views import _durable_queue_stats

        # 块一：provider 槽位占用。
        try:
            provider_slots: Any = await _collect_provider_slots()
        except Exception as exc:  # noqa: BLE001
            provider_slots = {"available": False, "error": str(exc)}

        # 块二：durable todo/doing（复用 observability 聚合范式）。
        try:
            durable_queues: Any = await sync_to_async(
                _durable_queue_stats, thread_sensitive=True
            )()
        except Exception as exc:  # noqa: BLE001
            durable_queues = {"available": False, "error": str(exc)}

        # 块三：runner 待派发 / 本地队列。
        try:
            runner: Any = await sync_to_async(_collect_runner_stats, thread_sensitive=True)()
        except Exception as exc:  # noqa: BLE001
            runner = {"available": False, "error": str(exc)}

        # 块四：RAG 并发——无显式信号量/槽位，记 n/a（不臆造）。
        rag = {"available": False, "error": "n/a"}

        return {
            "available": True,
            "error": "",
            "provider_slots": provider_slots,
            "durable_queues": durable_queues,
            "runner": runner,
            "rag": rag,
        }
    except Exception as exc:  # noqa: BLE001 — best-effort 局部降级
        logger.warning(
            "snapshot_concurrency_failed",
            error=str(exc),
            category="sampling",
            component="metrics",
        )
        return {"available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# 聚合器：五源并发采集，单源失败局部降级不拖垮整体
# ---------------------------------------------------------------------------


async def collect_snapshot() -> dict[str, Any]:
    """聚合 SNAP-01~05 五源当前值（``gather(return_exceptions=True)`` 双保险局部降级）。

    各源函数已逐源 try/except 兜底；此处对 gather 返回的异常项再兜底成
    ``{"available": False, "error": ...}``，确保单源即便抛也不拖垮整聚合。
    """
    results = await asyncio.gather(
        collect_host_snapshot(),
        collect_db_snapshot(),
        collect_redis_snapshot(),
        collect_qdrant_snapshot(),
        collect_concurrency_snapshot(),
        return_exceptions=True,
    )
    keys = ("host", "db", "redis", "qdrant", "concurrency")
    out: dict[str, Any] = {}
    for key, result in zip(keys, results, strict=False):
        if isinstance(result, BaseException):
            out[key] = {"available": False, "error": str(result)}
        else:
            out[key] = result
    out["generated_at"] = timezone.now().isoformat()
    return out

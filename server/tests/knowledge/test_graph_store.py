"""GraphStore 行为、防线与 raw SQL 收口审计测试（Plan 12-02，KMOD-04 / KMOD-02）。

用例清单：
- 遍历行为：线性链 1–3 跳 / A→B→C→A 环终止 / max_hops clamp /
  relations 白名单过滤 / direction="in" 反向 / chunk 边不参与实体遍历
- 有效性与 as-of：失效边默认不可见 / as_of 历史可见 / 多跳中段失效下游不可达 /
  expired_at 作废不可见 / naive datetime 拒绝（P2）
- 级联失效原语：invalidate_entity_version 单事务失效版本 + 出入边
- UUID prep（Pitfall 1）：uuid.UUID 入参命中数据；绕过 prep 的 str(uuid) 对照组为空
- grep 审计（P9 防线固化）：WITH RECURSIVE 与 knowledge_knowledgeedge 表名
  raw SQL 全仓只允许出现在 knowledge/graph_store.py
- perf 基准（@pytest.mark.perf，CI 默认 skip）：2000 实体 / 10000 边 3 跳 < 2s
"""

from __future__ import annotations

import os
import random
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from asgiref.sync import sync_to_async
from django.db import connection
from django.utils import timezone

from knowledge.graph_store import graph_store, invalidate_entity_version
from knowledge.models import (
    EdgeRelation,
    EntityKind,
    EntityOrigin,
    KnowledgeEdge,
    KnowledgeEntity,
    KnowledgeEntityVersion,
    generate_entity_id,
)

# SQLite 内存数据库 + async（sync_to_async 跨线程）需要 transaction=True 避免锁冲突
pytestmark = pytest.mark.django_db(transaction=True)


# ============================================================================
# 遍历行为（KMOD-04）
# ============================================================================


async def test_linear_chain_hops(entity_factory, edge_factory):
    """线性链 A→B→C→D：max_hops=2 返回 {B:1, C:2}，D 不可达；max_hops=3 含 D。"""

    def _setup():
        a, b, c, d = (entity_factory() for _ in range(4))
        for s, t in [(a, b), (b, c), (c, d)]:
            edge_factory(s, t)
        return a, b, c, d

    a, b, c, d = await sync_to_async(_setup)()

    result = await graph_store.traverse(a.id, max_hops=2)
    assert {r.entity_id: r.depth for r in result} == {b.id: 1, c.id: 2}

    result3 = await graph_store.traverse(a.id, max_hops=3)
    assert {r.entity_id: r.depth for r in result3} == {b.id: 1, c.id: 2, d.id: 3}


async def test_cycle_terminates_each_entity_once(entity_factory, edge_factory):
    """A→B→C→A 环：max_hops=3 正常终止，结果实体集合 = {B, C, A} 且每实体一条。"""

    def _setup():
        a, b, c = (entity_factory() for _ in range(3))
        for s, t in [(a, b), (b, c), (c, a)]:
            edge_factory(s, t)
        return a, b, c

    a, b, c = await sync_to_async(_setup)()

    result = await graph_store.traverse(a.id, max_hops=3)
    assert {r.entity_id for r in result} == {b.id, c.id, a.id}
    # 每实体只出现一条（GROUP BY + MIN depth）
    assert len(result) == 3


async def test_max_hops_clamp_to_three(entity_factory, edge_factory):
    """深度 clamp：5 节点链 A→B→C→D→E，max_hops=10 仍只达 D（第 3 跳），E 不出现。"""

    def _setup():
        nodes = [entity_factory() for _ in range(5)]
        for s, t in zip(nodes, nodes[1:]):
            edge_factory(s, t)
        return nodes

    a, b, c, d, e = await sync_to_async(_setup)()

    result = await graph_store.traverse(a.id, max_hops=10)
    ids = {r.entity_id for r in result}
    assert ids == {b.id, c.id, d.id}
    assert e.id not in ids


async def test_relations_filter_only_walks_whitelisted(entity_factory, edge_factory):
    """relations=["HAS_PLAN"] 只走 HAS_PLAN 边，RELATES_TO 分支不可达。"""

    def _setup():
        a, b, c = (entity_factory() for _ in range(3))
        edge_factory(a, b, relation=EdgeRelation.HAS_PLAN)
        edge_factory(a, c, relation=EdgeRelation.RELATES_TO)
        return a, b, c

    a, b, c = await sync_to_async(_setup)()

    result = await graph_store.traverse(a.id, max_hops=3, relations=["HAS_PLAN"])
    assert {r.entity_id for r in result} == {b.id}


async def test_relations_invalid_value_raises(entity_factory):
    """relations 传非法值（不在 EdgeRelation 白名单）→ ValueError（T-12-01）。"""
    a = await sync_to_async(entity_factory)()
    with pytest.raises(ValueError, match="非法 relation"):
        await graph_store.traverse(a.id, max_hops=2, relations=["DROP TABLE"])
    with pytest.raises(ValueError, match="非法 relation"):
        await graph_store.neighbors(a.id, relations=["nope"])


async def test_direction_in_traversal(entity_factory, edge_factory):
    """direction="in" 反向遍历命中上游实体。"""

    def _setup():
        a, b, c = (entity_factory() for _ in range(3))
        edge_factory(a, b)
        edge_factory(b, c)
        return a, b, c

    a, b, c = await sync_to_async(_setup)()

    result = await graph_store.traverse(c.id, max_hops=2, direction="in")
    assert {r.entity_id: r.depth for r in result} == {b.id: 1, a.id: 2}


async def test_chunk_edge_excluded_from_entity_traversal(entity_factory, edge_factory):
    """chunk 边（target_chunk_id 填、target_entity 空）不出现在实体遍历结果。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        edge_factory(a, b)
        edge_factory(
            a,
            target_entity=None,
            target_chunk_id=uuid.uuid4(),
            relation=EdgeRelation.MODIFIES_CHUNK,
        )
        return a, b

    a, b = await sync_to_async(_setup)()

    result = await graph_store.traverse(a.id, max_hops=3)
    assert {r.entity_id for r in result} == {b.id}


# ============================================================================
# 有效性与 as-of（KMOD-02）
# ============================================================================


async def test_invalidated_edge_invisible_by_default(entity_factory, edge_factory):
    """失效边默认不可见：A→B 边置 invalid_at 后 traverse(A) 为空、neighbors(A) 为空。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        edge = edge_factory(a, b, valid_at=timezone.now() - timedelta(hours=1))
        return a, b, edge

    a, b, edge = await sync_to_async(_setup)()
    await graph_store.invalidate_edge(edge.id, invalid_at=timezone.now())

    assert await graph_store.traverse(a.id, max_hops=3) == []
    assert await graph_store.neighbors(a.id) == []


async def test_as_of_history_visible(entity_factory, edge_factory):
    """as_of=失效前时点 traverse/neighbors 命中 B（bi-temporal 历史可查）。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        edge = edge_factory(a, b, valid_at=timezone.now() - timedelta(hours=1))
        return a, b, edge

    a, b, edge = await sync_to_async(_setup)()
    # 失效点设在未来 1h；as_of 取"创建之后、失效之前"的时点（满足 created_at <= as_of）
    await graph_store.invalidate_edge(edge.id, invalid_at=timezone.now() + timedelta(hours=1))
    as_of = timezone.now() + timedelta(minutes=10)

    traversed = await graph_store.traverse(a.id, max_hops=3, as_of=as_of)
    assert {r.entity_id for r in traversed} == {b.id}
    neighbor_records = await graph_store.neighbors(a.id, as_of=as_of)
    assert [n.target_id for n in neighbor_records] == [b.id]


async def test_midchain_invalidation_blocks_downstream(entity_factory, edge_factory):
    """多跳中段失效：A→B→C，B→C 失效后 traverse(A, max_hops=3) 只含 B。"""

    def _setup():
        a, b, c = (entity_factory() for _ in range(3))
        edge_factory(a, b, valid_at=timezone.now() - timedelta(hours=1))
        edge_bc = edge_factory(b, c, valid_at=timezone.now() - timedelta(hours=1))
        return a, b, c, edge_bc

    a, b, c, edge_bc = await sync_to_async(_setup)()
    await graph_store.invalidate_edge(edge_bc.id, invalid_at=timezone.now())

    result = await graph_store.traverse(a.id, max_hops=3)
    assert {r.entity_id for r in result} == {b.id}


async def test_expired_edge_invisible_by_default(entity_factory, edge_factory):
    """expired_at 置位（系统时间线作废）同样默认不可见。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        edge = edge_factory(a, b, valid_at=timezone.now() - timedelta(hours=1))
        return a, b, edge

    a, b, edge = await sync_to_async(_setup)()
    await graph_store.expire_edge(edge.id, expired_at=timezone.now())

    assert await graph_store.traverse(a.id, max_hops=3) == []
    assert await graph_store.neighbors(a.id) == []


async def test_invalidate_edge_does_not_overwrite_existing_timestamp(
    entity_factory, edge_factory
):
    """重复 invalidate_edge 是幂等 no-op：首次置位的 invalid_at 不被覆盖（防改写历史）。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        return edge_factory(a, b, valid_at=timezone.now() - timedelta(hours=2))

    edge = await sync_to_async(_setup)()
    first_invalid_at = timezone.now() - timedelta(hours=1)
    await graph_store.invalidate_edge(edge.id, invalid_at=first_invalid_at)

    # 再次调用（更晚的时间戳）不报错、不覆盖
    await graph_store.invalidate_edge(edge.id, invalid_at=timezone.now())

    refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
    assert refreshed.invalid_at == first_invalid_at


async def test_expire_edge_does_not_overwrite_existing_timestamp(entity_factory, edge_factory):
    """重复 expire_edge 是幂等 no-op：首次置位的 expired_at 不被覆盖（防改写历史）。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        return edge_factory(a, b, valid_at=timezone.now() - timedelta(hours=2))

    edge = await sync_to_async(_setup)()
    first_expired_at = timezone.now() - timedelta(hours=1)
    await graph_store.expire_edge(edge.id, expired_at=first_expired_at)

    await graph_store.expire_edge(edge.id, expired_at=timezone.now())

    refreshed = await KnowledgeEdge.objects.aget(id=edge.id)
    assert refreshed.expired_at == first_expired_at


async def test_invalidate_and_expire_missing_edge_raises():
    """目标边不存在 → DoesNotExist（与"已置位幂等返回"严格区分）。"""
    missing_id = uuid.uuid4()
    with pytest.raises(KnowledgeEdge.DoesNotExist):
        await graph_store.invalidate_edge(missing_id, invalid_at=timezone.now())
    with pytest.raises(KnowledgeEdge.DoesNotExist):
        await graph_store.expire_edge(missing_id, expired_at=timezone.now())


async def test_naive_datetime_rejected_on_add_edge(entity_factory):
    """naive datetime 传入 add_edge → ValueError（P2 时区漂移防线）。"""

    def _setup():
        return entity_factory(), entity_factory()

    a, b = await sync_to_async(_setup)()
    with pytest.raises(ValueError, match="aware"):
        await graph_store.add_edge(
            source_id=a.id,
            target_id=b.id,
            relation=EdgeRelation.RELATES_TO,
            valid_at=datetime(2026, 1, 1, 12, 0, 0),  # naive
        )


async def test_naive_as_of_rejected(entity_factory):
    """naive datetime 传入 as_of → ValueError（traverse 与 neighbors 双入口）。"""
    a = await sync_to_async(entity_factory)()
    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="aware"):
        await graph_store.traverse(a.id, max_hops=2, as_of=naive)
    with pytest.raises(ValueError, match="aware"):
        await graph_store.neighbors(a.id, as_of=naive)


# ============================================================================
# 级联失效原语（invalidate_entity_version，单事务）
# ============================================================================


async def test_invalidate_entity_version_cascade(entity_factory, edge_factory, version_factory):
    """invalidate_entity_version(B) 后：B 的 latest 版本失效、出入边均失效，
    traverse(A, max_hops=3) 不再含 C（2–3 跳级联）。"""

    def _setup():
        a, b, c = (entity_factory() for _ in range(3))
        past = timezone.now() - timedelta(hours=1)
        edge_factory(a, b, valid_at=past)
        edge_factory(b, c, valid_at=past)
        version = version_factory(b, valid_at=past)
        return a, b, c, version

    a, b, c, version = await sync_to_async(_setup)()

    await invalidate_entity_version(b.id, invalid_at=timezone.now())

    refreshed = await KnowledgeEntityVersion.objects.aget(id=version.id)
    assert refreshed.invalid_at is not None
    # B 的出入边均失效
    active_edges = await sync_to_async(
        lambda: list(KnowledgeEdge.objects.filter(invalid_at__isnull=True))
    )()
    assert active_edges == []
    # 失效后下游实体 C 在多跳遍历中不可达
    result = await graph_store.traverse(a.id, max_hops=3)
    assert c.id not in {r.entity_id for r in result}


async def test_invalidate_entity_version_does_not_overwrite_existing_timestamp(
    entity_factory, version_factory
):
    """重复 invalidate_entity_version 不覆盖已置位的版本 invalid_at（防改写历史）。"""

    def _setup():
        b = entity_factory()
        version = version_factory(b, valid_at=timezone.now() - timedelta(hours=2))
        return b, version

    b, version = await sync_to_async(_setup)()
    first_invalid_at = timezone.now() - timedelta(hours=1)
    await invalidate_entity_version(b.id, invalid_at=first_invalid_at)

    await invalidate_entity_version(b.id, invalid_at=timezone.now())

    refreshed = await KnowledgeEntityVersion.objects.aget(id=version.id)
    assert refreshed.invalid_at == first_invalid_at


async def test_invalidate_entity_version_skips_expired_edges(entity_factory, edge_factory):
    """已被系统时间线作废（expired_at 置位）的边不参与级联失效——
    不再补业务失效时间戳，避免污染已作废记录。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        past = timezone.now() - timedelta(hours=2)
        expired_edge = edge_factory(a, b, valid_at=past, expired_at=timezone.now())
        active_edge = edge_factory(b, a, valid_at=past)
        return b, expired_edge, active_edge

    b, expired_edge, active_edge = await sync_to_async(_setup)()

    await invalidate_entity_version(b.id, invalid_at=timezone.now())

    refreshed_expired = await KnowledgeEdge.objects.aget(id=expired_edge.id)
    assert refreshed_expired.invalid_at is None  # 已作废边未被触碰
    refreshed_active = await KnowledgeEdge.objects.aget(id=active_edge.id)
    assert refreshed_active.invalid_at is not None  # 活跃边正常级联失效


async def test_invalidate_entity_version_rejects_naive(entity_factory):
    """naive datetime 传入 invalidate_entity_version → ValueError（P2）。"""
    b = await sync_to_async(entity_factory)()
    with pytest.raises(ValueError, match="aware"):
        await invalidate_entity_version(b.id, invalid_at=datetime(2026, 1, 1))


# ============================================================================
# UUID prep（Pitfall 1 专测）
# ============================================================================


async def test_uuid_prep_hits_data_raw_str_misses(entity_factory, edge_factory):
    """uuid.UUID 直接入参可命中数据（get_db_prep_value 路径）；
    对照组：绕过 prep 用带连字符 str(uuid) 手工 cursor 查询返回空——证明 prep 必要性。"""

    def _setup():
        a, b = entity_factory(), entity_factory()
        edge_factory(a, b)
        return a, b

    a, b = await sync_to_async(_setup)()

    result = await graph_store.traverse(a.id, max_hops=1)
    assert {r.entity_id for r in result} == {b.id}

    if connection.vendor == "sqlite":
        # SQLite 存 32 位无连字符 hex；带连字符 str(uuid) 一行都查不到
        def _raw_count() -> int:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM knowledge_knowledgeedge WHERE source_entity_id = %s",
                    [str(a.id)],
                )
                return cur.fetchone()[0]

        assert await sync_to_async(_raw_count)() == 0


# ============================================================================
# grep 审计（P9 防线固化）：raw SQL 收口
# ============================================================================

_RAW_SQL_WHITELIST = {"knowledge/graph_store.py"}


def _scan_server_sources(needle: str) -> set[str]:
    """遍历 server/ 下全部非测试、非 migrations 的 .py 源码，返回含 needle 的文件集合。"""
    server_root = Path(__file__).resolve().parents[2]
    offenders: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(server_root):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".")
            and d not in ("migrations", "tests", "__pycache__", "node_modules", "staticfiles")
        ]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if needle in text:
                offenders.add(path.relative_to(server_root).as_posix())
    return offenders


def test_raw_sql_audit_with_recursive_confined():
    """全仓 WITH RECURSIVE 仅允许出现在 knowledge/graph_store.py（grep 审计）。"""
    offenders = _scan_server_sources("WITH RECURSIVE")
    assert offenders <= _RAW_SQL_WHITELIST, f"WITH RECURSIVE 泄漏到: {offenders}"
    assert offenders == _RAW_SQL_WHITELIST, "graph_store.py 应包含 WITH RECURSIVE（实现丢失？）"


def test_raw_sql_audit_edge_table_name_confined():
    """knowledge_knowledgeedge 表名字面量仅允许出现在 knowledge/graph_store.py。

    models.py 用 Django 默认表名（无显式 db_table），不含该字面量。
    """
    offenders = _scan_server_sources("knowledge_knowledgeedge")
    assert offenders <= _RAW_SQL_WHITELIST, f"边表 raw SQL 泄漏到: {offenders}"


# ============================================================================
# perf 基准（CI 默认 skip；本地 `pytest -m perf` 主动运行）
# ============================================================================


@pytest.mark.perf
async def test_perf_traverse_three_hops():
    """2000 实体 / 10000 随机边，3 跳遍历耗时 < 2s（T-12-03 性能基线）。"""

    def _setup() -> KnowledgeEntity:
        now = timezone.now()
        entities = [
            KnowledgeEntity(
                id=generate_entity_id(EntityKind.WORK_ITEM, "perf_bench", f"e{i}"),
                kind=EntityKind.WORK_ITEM,
                origin=EntityOrigin.FEISHU,
                source_kind="perf_bench",
                source_id=f"e{i}",
                title=f"perf-{i}",
                event_time=now,
            )
            for i in range(2000)
        ]
        KnowledgeEntity.objects.bulk_create(entities)

        rng = random.Random(42)
        pairs: set[tuple[int, int]] = set()
        while len(pairs) < 10000:
            s, t = rng.randrange(2000), rng.randrange(2000)
            if s != t:
                pairs.add((s, t))
        edges = [
            KnowledgeEdge(
                source_entity=entities[s],
                target_entity=entities[t],
                relation=EdgeRelation.RELATES_TO,
                valid_at=now,
            )
            for s, t in pairs
        ]
        KnowledgeEdge.objects.bulk_create(edges)
        return entities[0]

    start_entity = await sync_to_async(_setup)()

    started = time.perf_counter()
    result = await graph_store.traverse(start_entity.id, max_hops=3)
    elapsed = time.perf_counter() - started

    assert result, "随机稠密图 3 跳遍历应有命中"
    assert elapsed < 2.0, f"3 跳遍历耗时 {elapsed:.2f}s ≥ 2s"

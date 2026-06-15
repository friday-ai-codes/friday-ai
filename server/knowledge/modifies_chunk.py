"""HDIFF-02：MODIFIES_CHUNK 边的 as-of 查询 + 重索引失效对账（唯一收口）。

本模块是 knowledge 内部针对 ``MODIFIES_CHUNK``（diff→chunk 关联）边的时效治理面：

- ``amodifies_chunk_edges``：as-of 查询 helper——历史 ``as_of`` 见"当年成立且当年
  有效"的边；当前视图（``as_of=None``）默认只见未失效边（``invalid_at IS NULL``）。
  target_chunk_id-scoped 查询经 ``graph_store.chunk_in_edges`` chunk 反查唯一收口；
  repository_id-scoped 查询在 relation/repo 之上叠加**同一** bi-temporal 谓词
  （``bitemporal_as_of_q``，与 neighbors/traverse 语义一致）。
- ``areconcile_modifies_chunk_edges``：重索引完成后对账——把指向**已过期 chunk
  版本**的活跃 MODIFIES_CHUNK 边 ``invalid_at`` 置位（置位不删除，保留历史可追溯）。
  过期双信号：① target_chunk_id 在当前 base ``ChunkRegistry`` 已不存在（文件删除/
  chunk 收缩）；② 存在但 content_hash 漂移（边 metadata 冻结的 ``chunk_content_hash``
  ≠ 当前 ChunkRegistry.content_hash）。边失效唯一经 ``graph_store.invalidate_edge``
  收口（不裸写 ORM update，防改写历史 T-33-04）；逐边 try/except 降级（T-33-05）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from django.db import IntegrityError

from knowledge.graph_store import (
    EdgeRecord,
    bitemporal_as_of_q,
    graph_store,
    require_aware,
)
from knowledge.models import EdgeRelation, KnowledgeEdge

__all__ = ["amodifies_chunk_edges", "areconcile_modifies_chunk_edges"]

logger = structlog.get_logger(__name__)


async def amodifies_chunk_edges(
    *,
    repository_id: str | None = None,
    target_chunk_id: uuid.UUID | None = None,
    as_of: datetime | None = None,
) -> list[EdgeRecord]:
    """查询 MODIFIES_CHUNK 边（as-of bi-temporal，knowledge 内部查询面）。

    - ``as_of=None``（当前视图）：只返回 ``invalid_at IS NULL AND expired_at IS NULL``
      的边；``as_of`` 给定：返回该时点"当年成立且当年有效"的边（naive 经
      ``require_aware`` 拒绝）。
    - ``target_chunk_id`` 给定：经 ``graph_store.chunk_in_edges`` chunk 反查唯一收口
      取入边，再过滤 ``relation == MODIFIES_CHUNK``（chunk-lookup chokepoint 纪律）。
    - 否则（repository_id-scoped）：在 ``relation=MODIFIES_CHUNK`` +
      可选 ``source_entity__repository_id`` 之上叠加**同一** bi-temporal 谓词。
    """
    if target_chunk_id is not None:
        records = await graph_store.chunk_in_edges(target_chunk_id, as_of=as_of)
        return [r for r in records if r.relation == EdgeRelation.MODIFIES_CHUNK]

    qs = KnowledgeEdge.objects.filter(relation=EdgeRelation.MODIFIES_CHUNK)
    if repository_id is not None:
        qs = qs.filter(source_entity__repository_id=repository_id)
    if as_of is None:
        qs = qs.filter(invalid_at__isnull=True, expired_at__isnull=True)
    else:
        require_aware(as_of, "as_of")
        qs = qs.filter(bitemporal_as_of_q(as_of))
    qs = qs.select_related("source_entity")
    return [
        EdgeRecord(
            edge_id=e.id,
            source_id=e.source_entity_id,
            target_id=e.target_entity_id,
            target_chunk_id=e.target_chunk_id,
            relation=e.relation,
            metadata=e.metadata,
            valid_at=e.valid_at,
            invalid_at=e.invalid_at,
            created_at=e.created_at,
            expired_at=e.expired_at,
        )
        async for e in qs
    ]


async def areconcile_modifies_chunk_edges(repository_id: str, *, invalid_at: datetime) -> int:
    """重索引对账：把指向已过期 chunk 版本的活跃 MODIFIES_CHUNK 边置 invalid_at。

    过期双信号（取既有重索引可可靠提供者）：
    ① 边 ``target_chunk_id`` 在当前 base ``ChunkRegistry``（branch_name=""）已不存在
       （文件删除 / chunk 收缩）→ 过期；
    ② 存在但 ``content_hash`` 漂移（边 metadata 冻结的 ``chunk_content_hash`` 非空且
       ≠ 当前 ChunkRegistry.content_hash，同位置内容已被新版本取代）→ 过期。
    边 metadata 缺 ``chunk_content_hash``（历史边 / 空串）→ 仅用①存在性判定，不因缺
    指纹误失效（保守，T-33-06）。

    边失效唯一经 ``graph_store.invalidate_edge`` 收口（置位不删除、仅 invalid_at IS
    NULL 时写一次、不覆盖原失效时间，T-33-04）；逐边 try/except 降级——单边触发
    ``kedge_valid_range``（invalid_at<=valid_at）等约束仅记 warning 跳过，不掀翻批次
    （T-33-05，沿用 v0.5 best-effort 范式）。返回成功失效计数（结构化日志可观测）。
    """
    require_aware(invalid_at, "invalid_at")

    from asgiref.sync import sync_to_async

    from code_relations.models import ChunkRegistry

    # ① 当前 repo base 命名空间 chunk 指纹快照：{chunk_id: content_hash}
    current: dict[uuid.UUID, str] = await sync_to_async(
        lambda: dict(
            ChunkRegistry.objects.filter(
                repository_id=repository_id, branch_name=""
            ).values_list("chunk_id", "content_hash")
        )
    )()

    # ② 该 repo 的活跃 MODIFIES_CHUNK 边（source_entity.repository 归属本 repo）；
    # 先 materialize 再逐条置位——避免开着读游标的同时写库（SQLite 锁竞争）。
    active = await sync_to_async(
        lambda: list(
            KnowledgeEdge.objects.filter(
                relation=EdgeRelation.MODIFIES_CHUNK,
                invalid_at__isnull=True,
                expired_at__isnull=True,
                source_entity__repository_id=repository_id,
            ).values_list("id", "target_chunk_id", "metadata")
        )
    )()

    checked = 0
    invalidated = 0
    for edge_id, cid, metadata in active:
        checked += 1
        if cid is None:
            continue
        # ③ 过期判定：不存在（信号①） 或 content_hash 漂移（信号②，需边有冻结指纹）
        if cid in current:
            frozen = (metadata or {}).get("chunk_content_hash")
            stale = bool(frozen) and frozen != current[cid]
        else:
            stale = True
        if not stale:
            continue
        # ④ 过期边逐条置位（唯一经 invalidate_edge），逐边隔离 best-effort
        try:
            await graph_store.invalidate_edge(edge_id, invalid_at=invalid_at)
            invalidated += 1
        except (IntegrityError, KnowledgeEdge.DoesNotExist) as exc:
            logger.warning(
                "knowledge_modifies_chunk_reconcile_edge_skipped",
                repository_id=repository_id,
                edge_id=str(edge_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )

    logger.info(
        "knowledge_modifies_chunk_reconciled",
        repository_id=repository_id,
        checked=checked,
        invalidated=invalidated,
    )
    return invalidated

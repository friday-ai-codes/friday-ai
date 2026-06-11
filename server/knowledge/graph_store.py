"""知识图谱图访问服务（Phase 12，KMOD-04 / KMOD-02）。

实现契约（三条，全部为 locked decision 的落点）：

1. **图访问唯一收口**：``WITH RECURSIVE`` 与 ``knowledge_knowledgeedge`` 表名的
   raw SQL 全仓只允许出现在本文件（grep 审计测试 ``test_graph_store.py`` 守护）。
   调用方（Phase 13+ 服务/节点）一律 import 模块尾部的 ``graph_store`` 单例，
   不存在绕过接口的裸 SQL 路径。本接口同时是换图引擎的逃生门——
   若未来引入图数据库，仅替换 ``RelationalGraphStore`` 实现，接口不变。
2. **默认语义 = 当前有效**：所有读路径默认过滤
   ``invalid_at IS NULL AND expired_at IS NULL``；历史查询必须走显式 ``as_of``
   参数（bi-temporal as-of 语义），调用方无法"忘加"有效性过滤（P2 防线）。
3. **接口方法全部 keyword-only 参数**：为 Phase 15 权限 scope 参数
   （project_id 等）预留非破坏性扩展位（ASVS V4 预埋）——新增 keyword 参数
   不破坏既有调用方。

写路径只提供 invalidate / expire 置位方法，不提供 delete（失效置位不删除，
历史可审计，locked decision；T-12-04 防线）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Q

from knowledge.models import (
    EdgeRelation,
    KnowledgeEdge,
    KnowledgeEntityVersion,
)

__all__ = [
    "EdgeRecord",
    "GraphStore",
    "RelationalGraphStore",
    "TraversalResult",
    "graph_store",
    "invalidate_entity_version",
]

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TraversalResult:
    """遍历命中：实体 id + 最短跳数（MIN depth）。

    首版只返回 (entity_id, depth)（Open Question 2 定案）；
    路径重建需求出现时再扩展字段，不破坏收口。
    """

    entity_id: uuid.UUID
    depth: int


@dataclass(frozen=True)
class EdgeRecord:
    """单跳邻居查询返回的边详情快照（neighbors 用）。"""

    edge_id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID | None
    target_chunk_id: uuid.UUID | None
    relation: str
    metadata: dict
    valid_at: datetime
    invalid_at: datetime | None
    created_at: datetime
    expired_at: datetime | None


def _require_aware(dt: datetime, field: str) -> datetime:
    """P2 防线：拒绝 naive datetime（USE_TZ=True，禁止 naive，否则 ±8h 漂移）。"""
    if dt.tzinfo is None:
        raise ValueError(f"{field} 必须是 aware datetime（USE_TZ=True，禁止 naive datetime）")
    return dt


def _validate_relations(relations: list[str] | None) -> list[str] | None:
    """relations 白名单校验：逐值断言 ∈ EdgeRelation.values（T-12-01 防线）。"""
    if relations is None:
        return None
    for rel in relations:
        if rel not in EdgeRelation.values:
            raise ValueError(f"非法 relation 值: {rel!r}（必须 ∈ {EdgeRelation.values}）")
    return list(relations)


class GraphStore(Protocol):
    """图访问唯一收口接口（KMOD-04）。

    有效性过滤 / 深度上限 / 防环全部内置于实现，调用方无法绕过。
    全部方法 async；self 后参数 keyword-only（edge_id / entity_id / start_id
    作为主语保留 positional），为 Phase 15 权限 scope 参数留扩展位。
    """

    async def add_edge(
        self,
        *,
        source_id: uuid.UUID,
        target_id: uuid.UUID | None = None,
        target_chunk_id: uuid.UUID | None = None,
        relation: str,
        valid_at: datetime,
        metadata: dict | None = None,
    ) -> uuid.UUID: ...

    async def invalidate_edge(self, edge_id: uuid.UUID, *, invalid_at: datetime) -> None: ...

    async def expire_edge(self, edge_id: uuid.UUID, *, expired_at: datetime) -> None: ...

    async def neighbors(
        self,
        entity_id: uuid.UUID,
        *,
        relations: list[str] | None = None,
        direction: str = "out",
        as_of: datetime | None = None,
    ) -> list[EdgeRecord]: ...

    async def traverse(
        self,
        start_id: uuid.UUID,
        *,
        max_hops: int = 2,
        relations: list[str] | None = None,
        direction: str = "out",
        as_of: datetime | None = None,
    ) -> list[TraversalResult]: ...


class RelationalGraphStore:
    """GraphStore 的关系型实现（SQLite dev/test 与 PostgreSQL prod 双后端）。

    写路径与单跳 neighbors 全走 ORM；仅多跳 traverse 用递归 CTE raw SQL
    （`_traverse_sync` / `_build_sql`，raw SQL 不出本文件）。
    """

    MAX_HOPS = 3
    _RESULT_LIMIT = 1000  # 外层 LIMIT fail-safe（T-12-03 防线）

    async def add_edge(
        self,
        *,
        source_id: uuid.UUID,
        target_id: uuid.UUID | None = None,
        target_chunk_id: uuid.UUID | None = None,
        relation: str,
        valid_at: datetime,
        metadata: dict | None = None,
    ) -> uuid.UUID:
        """新增一条边，返回 edge id。

        target_id（实体边）与 target_chunk_id（chunk 边，Phase 14）XOR 二选一：
        DB 层 ``kedge_target_xor`` 约束兜底，接口层先行校验给出友好错误。
        """
        _require_aware(valid_at, "valid_at")
        if relation not in EdgeRelation.values:
            raise ValueError(f"非法 relation 值: {relation!r}（必须 ∈ {EdgeRelation.values}）")
        if (target_id is None) == (target_chunk_id is None):
            raise ValueError("target_id 与 target_chunk_id 必须二选一（XOR）")
        edge = await KnowledgeEdge.objects.acreate(
            source_entity_id=source_id,
            target_entity_id=target_id,
            target_chunk_id=target_chunk_id,
            relation=relation,
            valid_at=valid_at,
            metadata=metadata or {},
        )
        logger.info(
            "knowledge_edge_added",
            edge_id=str(edge.id),
            source_id=str(source_id),
            target_id=str(target_id) if target_id else None,
            target_chunk_id=str(target_chunk_id) if target_chunk_id else None,
            relation=relation,
        )
        return edge.id

    async def invalidate_edge(self, edge_id: uuid.UUID, *, invalid_at: datetime) -> None:
        """业务时间线失效置位（不删除）。目标不存在时 raise DoesNotExist。"""
        _require_aware(invalid_at, "invalid_at")
        updated = await KnowledgeEdge.objects.filter(id=edge_id).aupdate(invalid_at=invalid_at)
        if updated == 0:
            raise KnowledgeEdge.DoesNotExist(f"KnowledgeEdge {edge_id} 不存在")
        logger.info(
            "knowledge_edge_invalidated", edge_id=str(edge_id), invalid_at=invalid_at.isoformat()
        )

    async def expire_edge(self, edge_id: uuid.UUID, *, expired_at: datetime) -> None:
        """系统时间线作废置位（纠错用，不删除）。目标不存在时 raise DoesNotExist。"""
        _require_aware(expired_at, "expired_at")
        updated = await KnowledgeEdge.objects.filter(id=edge_id).aupdate(expired_at=expired_at)
        if updated == 0:
            raise KnowledgeEdge.DoesNotExist(f"KnowledgeEdge {edge_id} 不存在")
        logger.info(
            "knowledge_edge_expired", edge_id=str(edge_id), expired_at=expired_at.isoformat()
        )

    async def neighbors(
        self,
        entity_id: uuid.UUID,
        *,
        relations: list[str] | None = None,
        direction: str = "out",
        as_of: datetime | None = None,
    ) -> list[EdgeRecord]:
        """单跳邻居边查询（带边详情；纯 ORM，无 raw SQL）。

        默认只返回当前有效边；``as_of`` 给定时按 bi-temporal as-of 语义
        返回该时点有效的边（历史可查）。
        """
        relations = _validate_relations(relations)
        if direction not in ("out", "in", "both"):
            raise ValueError(f"非法 direction: {direction!r}（必须 ∈ ('out', 'in', 'both')）")

        if direction == "out":
            direction_q = Q(source_entity_id=entity_id)
        elif direction == "in":
            direction_q = Q(target_entity_id=entity_id)
        else:
            direction_q = Q(source_entity_id=entity_id) | Q(target_entity_id=entity_id)

        qs = KnowledgeEdge.objects.filter(direction_q)
        if relations is not None:
            qs = qs.filter(relation__in=relations)
        if as_of is None:
            qs = qs.filter(invalid_at__isnull=True, expired_at__isnull=True)
        else:
            _require_aware(as_of, "as_of")
            qs = qs.filter(
                Q(valid_at__lte=as_of)
                & (Q(invalid_at__isnull=True) | Q(invalid_at__gt=as_of))
                & Q(created_at__lte=as_of)
                & (Q(expired_at__isnull=True) | Q(expired_at__gt=as_of))
            )

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

    async def traverse(
        self,
        start_id: uuid.UUID,
        *,
        max_hops: int = 2,
        relations: list[str] | None = None,
        direction: str = "out",
        as_of: datetime | None = None,
    ) -> list[TraversalResult]:
        """1–3 跳递归遍历（深度上限 / 防环 / 有效性过滤全部内置）。

        ``max_hops`` 接口层 clamp 到 1..MAX_HOPS（调用方传 10 也只走 3，
        T-12-03 防线）；``as_of`` 给定时按 bi-temporal as-of 语义遍历历史图。
        """
        relations = _validate_relations(relations)
        if as_of is not None:
            _require_aware(as_of, "as_of")
        hops = max(1, min(int(max_hops), self.MAX_HOPS))
        return await sync_to_async(self._traverse_sync)(start_id, hops, relations, direction, as_of)

    def _traverse_sync(
        self,
        start_id: uuid.UUID,
        hops: int,
        relations: list[str] | None,
        direction: str,
        as_of: datetime | None,
    ) -> list[TraversalResult]:
        """同步遍历实现（Task 2 交付递归 CTE）。"""
        raise NotImplementedError("递归 CTE 遍历在 Plan 12-02 Task 2 交付")


async def invalidate_entity_version(entity_id: uuid.UUID, *, invalid_at: datetime) -> None:
    """单事务级联失效原语（P2 防线）：失效实体最新版本 + 该实体全部活跃出入边。

    在一个 ``transaction.atomic()`` 内同时完成：
    ① 该实体 ``is_latest=True`` 的版本行置 ``invalid_at``；
    ② 该实体全部活跃出入边（source 或 target 命中且 ``invalid_at IS NULL``）
       置 ``invalid_at``——失效后下游实体在多跳遍历中不可达。

    注意：``is_latest`` 翻转与重摄取触发在 Phase 13；本函数只交付
    级联失效的操作原语与事务语义。
    """
    _require_aware(invalid_at, "invalid_at")

    def _invalidate_sync() -> tuple[int, int]:
        with transaction.atomic():
            version_count = KnowledgeEntityVersion.objects.filter(
                entity_id=entity_id, is_latest=True
            ).update(invalid_at=invalid_at)
            edge_count = KnowledgeEdge.objects.filter(
                Q(source_entity_id=entity_id) | Q(target_entity_id=entity_id),
                invalid_at__isnull=True,
            ).update(invalid_at=invalid_at)
        return version_count, edge_count

    version_count, edge_count = await sync_to_async(_invalidate_sync)()
    logger.info(
        "knowledge_entity_version_invalidated",
        entity_id=str(entity_id),
        invalid_at=invalid_at.isoformat(),
        version_count=version_count,
        edge_count=edge_count,
    )


# 模块级默认单例（NodeRegistry 同款模式）：Phase 13+ 调用方直接 import 本实例。
graph_store = RelationalGraphStore()

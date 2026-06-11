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

import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import structlog
from asgiref.sync import sync_to_async
from django.db import connection, transaction
from django.db.models import Q

from knowledge.models import (
    EdgeRelation,
    KnowledgeEdge,
    KnowledgeEntity,
    KnowledgeEntityVersion,
)

__all__ = [
    "EdgeRecord",
    "GraphStore",
    "RelationalGraphStore",
    "TraversalResult",
    "graph_store",
    "invalidate_entity_version",
    "require_aware",
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


def require_aware(dt: datetime, field: str) -> datetime:
    """P2 防线：拒绝 naive datetime（USE_TZ=True，禁止 naive，否则 ±8h 漂移）。

    公开 util（IN-03）：ingestion 等下游模块同样需要该防线，
    跨模块依赖私有符号易在重构时悄然破坏，故提升为公开 API。
    """
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
        require_aware(valid_at, "valid_at")
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
        """业务时间线失效置位（不删除，幂等）。目标不存在时 raise DoesNotExist。

        仅在 ``invalid_at`` 仍为 NULL 时置位：已失效的边重复调用是幂等 no-op
        （warning 日志），绝不覆盖原失效时间——bi-temporal 模型里覆盖等于改写
        历史，``as_of`` 查询结果会随之漂移（T-12-04 防线）。
        """
        require_aware(invalid_at, "invalid_at")
        updated = await KnowledgeEdge.objects.filter(id=edge_id, invalid_at__isnull=True).aupdate(
            invalid_at=invalid_at
        )
        if updated == 0:
            # 区分两种 0 行情况：边不存在（响亮报错） vs 已失效（幂等返回）
            if not await KnowledgeEdge.objects.filter(id=edge_id).aexists():
                raise KnowledgeEdge.DoesNotExist(f"KnowledgeEdge {edge_id} 不存在")
            logger.warning(
                "knowledge_edge_already_invalidated",
                edge_id=str(edge_id),
                requested_invalid_at=invalid_at.isoformat(),
            )
            return
        logger.info(
            "knowledge_edge_invalidated", edge_id=str(edge_id), invalid_at=invalid_at.isoformat()
        )

    async def expire_edge(self, edge_id: uuid.UUID, *, expired_at: datetime) -> None:
        """系统时间线作废置位（纠错用，不删除，幂等）。目标不存在时 raise DoesNotExist。

        仅在 ``expired_at`` 仍为 NULL 时置位：已作废的边重复调用是幂等 no-op
        （warning 日志），绝不覆盖原作废时间（同 ``invalidate_edge``，防改写历史）。
        """
        require_aware(expired_at, "expired_at")
        updated = await KnowledgeEdge.objects.filter(id=edge_id, expired_at__isnull=True).aupdate(
            expired_at=expired_at
        )
        if updated == 0:
            if not await KnowledgeEdge.objects.filter(id=edge_id).aexists():
                raise KnowledgeEdge.DoesNotExist(f"KnowledgeEdge {edge_id} 不存在")
            logger.warning(
                "knowledge_edge_already_expired",
                edge_id=str(edge_id),
                requested_expired_at=expired_at.isoformat(),
            )
            return
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
            require_aware(as_of, "as_of")
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
            require_aware(as_of, "as_of")
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
        """同步遍历实现：递归 CTE（raw SQL 不出本文件）。

        仅支持 SQLite 与 PostgreSQL（A1 定案）：MySQL 的 ``||`` 默认非字符串
        拼接（需 PIPES_AS_CONCAT），响亮失败优于静默错误结果。
        """
        if connection.vendor not in ("sqlite", "postgresql"):
            raise NotImplementedError(f"GraphStore 不支持 {connection.vendor}")
        started = time.perf_counter()
        prep_id = self._prep_uuid(start_id)
        sql, params = self._build_sql(prep_id, hops, relations, as_of, direction)
        with connection.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        results = [TraversalResult(entity_id=self._to_uuid(r[0]), depth=r[1]) for r in rows]
        logger.info(
            "knowledge_graph_traversed",
            start_id=str(start_id),
            hops=hops,
            result_count=len(results),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return results

    @staticmethod
    def _prep_uuid(value: uuid.UUID) -> Any:
        """UUID 进 SQL 前的跨后端预处理（Pitfall 1 防线）。

        SQLite 存 32 位无连字符 hex、PG 存原生 uuid——raw cursor 不会自动做
        ``get_db_prep_value``，所有进 SQL 的 UUID 参数必经本函数，否则
        SQLite 下一行都查不到而 PG 正常（dev/prod 行为分叉）。
        """
        return KnowledgeEntity._meta.pk.get_db_prep_value(value, connection)

    @staticmethod
    def _to_uuid(raw: str | uuid.UUID) -> uuid.UUID:
        """结果列 UUID 还原：SQLite 回 str（hex），PG psycopg 回 UUID 对象。"""
        return uuid.UUID(hex=raw) if isinstance(raw, str) else raw

    def _build_sql(
        self,
        prep_id: Any,
        hops: int,
        relations: list[str] | None,
        as_of: datetime | None,
        direction: str,
    ) -> tuple[str, list]:
        """拼装递归 CTE SQL（SQLite/PG 双后端可移植规格）。

        可移植要点（RESEARCH §递归 CTE 双方言）：
        - 防环：字符串 path + ``NOT LIKE``（PG 数组 / CYCLE 子句 SQLite 不支持）；
          path 初始只含首跳目标（不含起点）——环回到起点时起点计 1 次后终止
          （A→B→C→A 环结果含 A，每实体仅一条）。
        - 深度上限：递归项 ``w.depth < %s``；LIMIT 仅放最外层（PG 禁止递归项 LIMIT）。
        - 占位符统一 ``%s``（Django cursor 双后端适配）；零用户输入拼接（T-12-01）：
          validity 谓词仅两个固定模板，relations 经白名单校验后只生成占位符。
        - direction="both" 本阶段不实现（接口预留，Phase 15 需要时扩展）。
        """
        if direction == "out":
            from_col, to_col = "source_entity_id", "target_entity_id"
        elif direction == "in":
            from_col, to_col = "target_entity_id", "source_entity_id"
        elif direction == "both":
            raise NotImplementedError(
                'direction="both" 多跳遍历本阶段未实现（接口预留，Phase 15 需要时扩展）'
            )
        else:
            raise ValueError(f"非法 direction: {direction!r}（必须 ∈ ('out', 'in', 'both')）")

        # validity 谓词：仅两个固定模板字符串，as_of 值全部参数绑定（各出现 4 次）
        if as_of is None:
            validity = "e.invalid_at IS NULL AND e.expired_at IS NULL"
            validity_params: list = []
        else:
            validity = (
                "e.valid_at <= %s AND (e.invalid_at IS NULL OR e.invalid_at > %s) "
                "AND e.created_at <= %s AND (e.expired_at IS NULL OR e.expired_at > %s)"
            )
            validity_params = [as_of, as_of, as_of, as_of]

        # relation 过滤：白名单校验后才生成占位符，值全部参数绑定（T-12-01）
        if relations:
            for rel in relations:
                if rel not in EdgeRelation.values:
                    raise ValueError(f"非法 relation 值: {rel!r}（必须 ∈ {EdgeRelation.values}）")
            placeholders = ", ".join(["%s"] * len(relations))
            relation_filter = f"AND e.relation IN ({placeholders})"
            relation_params: list = list(relations)
        else:
            relation_filter = ""
            relation_params = []

        # 表名硬编码 knowledge_knowledgeedge：全仓仅本文件允许出现（grep 审计守护）
        sql = f"""
WITH RECURSIVE walk(entity_id, depth, path) AS (
    SELECT e.{to_col}, 1,
           ',' || CAST(e.{to_col} AS TEXT) || ','
    FROM knowledge_knowledgeedge e
    WHERE e.{from_col} = %s
      AND e.target_entity_id IS NOT NULL
      AND {validity}
      {relation_filter}
  UNION ALL
    SELECT e.{to_col}, w.depth + 1,
           w.path || CAST(e.{to_col} AS TEXT) || ','
    FROM knowledge_knowledgeedge e
    JOIN walk w ON e.{from_col} = w.entity_id
    WHERE w.depth < %s
      AND e.target_entity_id IS NOT NULL
      AND {validity}
      {relation_filter}
      AND w.path NOT LIKE '%%,' || CAST(e.{to_col} AS TEXT) || ',%%'
)
SELECT entity_id, MIN(depth) AS depth
FROM walk
GROUP BY entity_id
ORDER BY depth
LIMIT %s
"""
        params: list = (
            [prep_id]
            + validity_params
            + relation_params
            + [hops]
            + validity_params
            + relation_params
            + [self._RESULT_LIMIT]
        )
        return sql, params


async def invalidate_entity_version(entity_id: uuid.UUID, *, invalid_at: datetime) -> None:
    """单事务级联失效原语（P2 防线）：失效实体最新版本 + 该实体全部活跃出入边。

    在一个 ``transaction.atomic()`` 内同时完成：
    ① 该实体 ``is_latest=True`` 且 ``invalid_at IS NULL`` 的版本行置 ``invalid_at``
       ——已失效版本不再触碰，重复调用幂等，绝不覆盖原失效时间（防改写历史，
       同 ``invalidate_edge``）；
    ② 该实体全部活跃出入边（source 或 target 命中且 ``invalid_at IS NULL``
       且 ``expired_at IS NULL``）置 ``invalid_at``——已被系统时间线作废
       （expired）的边不再补业务失效时间戳，避免污染已作废记录；
       失效后下游实体在多跳遍历中不可达。

    注意：``is_latest`` 翻转与重摄取触发在 Phase 13；本函数只交付
    级联失效的操作原语与事务语义。
    """
    require_aware(invalid_at, "invalid_at")

    def _invalidate_sync() -> tuple[int, int]:
        with transaction.atomic():
            version_count = KnowledgeEntityVersion.objects.filter(
                entity_id=entity_id, is_latest=True, invalid_at__isnull=True
            ).update(invalid_at=invalid_at)
            edge_count = KnowledgeEdge.objects.filter(
                Q(source_entity_id=entity_id) | Q(target_entity_id=entity_id),
                invalid_at__isnull=True,
                expired_at__isnull=True,
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

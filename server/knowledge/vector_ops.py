"""delivery_knowledge Qdrant 写操作薄层（Phase 13 / INGEST-06、INGEST-08）。

本模块是知识路径 Qdrant **写语义的唯一收口**——与 indexer 的静默容错
**刻意相反**（P1 防线：漏删旧方案 / 漏写新向量是正确性事故而非噪音）：

- upsert / tombstone 一律 ``wait=True``，失败 raise（含
  ``upsert_vectors_by_name`` 返回 False 的静默语义，本层负责转译为异常）；
- 物理删点是纯优化层（``is_latest`` 翻转才是正确性防线）：失败吞掉
  但 structlog error 响亮记录；
- 删点只按 point id 列表（``PointIdsList``），绝不按业务 filter 删
  （weak ordering 竞态会误删新点，qdrant#6556）。

payload schema 单一事实源为 ``knowledge.collection`` 常量，
本模块写入的键集合 ⊇ 索引字段 ∪ 必带字段（回归测试锁定，T-13-02）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from qdrant_client import models
from qdrant_client.http.models import SparseVector

from knowledge.collection import (
    DELIVERY_KNOWLEDGE_COLLECTION,
    KNOWLEDGE_PAYLOAD_INDEXED_FIELDS,
    KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS,
)
from knowledge.exceptions import KnowledgeError
from services.qdrant_service import QdrantService

if TYPE_CHECKING:
    from knowledge.chunking import KnowledgeChunk
    from knowledge.models import KnowledgeEntity, KnowledgeEntityVersion

logger = structlog.get_logger(__name__)

__all__ = [
    "build_knowledge_points",
    "delete_points",
    "tombstone_points",
    "upsert_knowledge_points",
]

# 分批 upsert 上限（indexer 同款编排）
_UPSERT_BATCH_SIZE = 100

# 写入处 schema 契约（T-13-02）：payload 键集合必须 ⊇ 索引字段 ∪ 必带字段
_SCHEMA_KEYS = set(KNOWLEDGE_PAYLOAD_INDEXED_FIELDS) | set(KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS)


def build_knowledge_points(
    *,
    entity: KnowledgeEntity,
    version: KnowledgeEntityVersion,
    chunks: list[KnowledgeChunk],
    dense_vectors: list[list[float]],
    sparse_vectors: list[dict[str, Any]],
    point_ids: list[str],
    embedding_model: str,
) -> list[dict[str, Any]]:
    """构造 hybrid point 列表（纯函数，无 I/O）。

    payload 全字段构造（RESEARCH Pattern 6）：8 索引字段 + 6 必带字段，
    键集合 ⊇ ``KNOWLEDGE_PAYLOAD_INDEXED_FIELDS`` ∪
    ``KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS``（schema 单一事实源）。

    约定：
    - ``project_id`` / ``repository_id`` 为 None 时写空串
      （与 ``file_path`` 空串契约一致，保证 KEYWORD 索引字段类型稳定）；
    - sparse 项 ``indices`` 为空时该 point 降级为纯 dense vector
      （sparse 是召回增强不是正确性，规划定案的降级语义）。
    """
    points: list[dict[str, Any]] = []
    for chunk, dense, sparse, point_id in zip(
        chunks, dense_vectors, sparse_vectors, point_ids, strict=True
    ):
        vector: Any
        if sparse.get("indices"):
            vector = {
                "dense": dense,
                "sparse": SparseVector(indices=sparse["indices"], values=sparse["values"]),
            }
        else:
            vector = dense

        payload: dict[str, Any] = {
            # 8 索引字段（KNOWLEDGE_PAYLOAD_INDEXED_FIELDS）
            "entity_kind": entity.kind,
            "entity_id": str(entity.id),
            "version": version.version,
            "is_latest": True,
            "project_id": str(entity.space_id) if entity.space_id else "",
            "repository_id": str(entity.repository_id) if entity.repository_id else "",
            "source_kind": entity.source_kind,
            "event_time": version.event_time.isoformat(),
            # 6 必带非索引字段（KNOWLEDGE_PAYLOAD_REQUIRED_FIELDS）
            "source_id": entity.source_id,
            "chunk_kind": chunk.chunk_kind,
            "file_path": "",  # 知识文本无文件路径（契约注明可空串）
            "text": chunk.text,
            "embedding_model": embedding_model,
            "version_id": str(version.id),
            # PageIndex 章节路径回溯用：命中 chunk → toc_tree.chunk_indexes 反查
            "chunk_index": chunk.index,
        }
        missing = _SCHEMA_KEYS - payload.keys()
        if missing:  # 写入处契约自检：缺权限/定位字段即检索期 IDOR 温床（P6）
            raise KnowledgeError(
                "knowledge point payload 缺少 schema 必带字段",
                details={"missing": sorted(missing), "point_id": point_id},
            )
        points.append({"id": point_id, "vector": vector, "payload": payload})
    return points


async def upsert_knowledge_points(points: list[dict[str, Any]]) -> None:
    """分批 upsert 知识 points；任一批失败（含返回 False）即 raise。

    ``QdrantService.upsert_vectors_by_name`` catch 全部网络异常后
    ``return False``（indexer 容错哲学）——知识路径禁止沿用该静默语义，
    本函数负责把 False 转译为 :class:`KnowledgeError`。
    """
    for start in range(0, len(points), _UPSERT_BATCH_SIZE):
        batch = points[start : start + _UPSERT_BATCH_SIZE]
        ok = await sync_to_async(QdrantService.upsert_vectors_by_name)(
            DELIVERY_KNOWLEDGE_COLLECTION, batch
        )
        if ok is not True:
            logger.error(
                "knowledge_vector_upsert_failed",
                collection=DELIVERY_KNOWLEDGE_COLLECTION,
                batch_start=start,
                batch_size=len(batch),
                total_points=len(points),
            )
            raise KnowledgeError(
                "delivery_knowledge 向量 upsert 失败（upsert_vectors_by_name 返回 False）",
                details={
                    "collection": DELIVERY_KNOWLEDGE_COLLECTION,
                    "batch_start": start,
                    "batch_size": len(batch),
                    "total_points": len(points),
                },
            )


async def tombstone_points(point_ids: list[str]) -> None:
    """将旧版本 points 的 payload ``is_latest`` 置 False（版本下线第一道防线）。

    ``wait=True`` + 异常重抛：tombstone 失败是唯一影响检索正确性的
    commit 后失败（旧版本仍可被召回），必须响亮。
    """
    if not point_ids:
        return
    # 首次调用经 sync ORM 读配置，async 上下文必须桥接
    client = await sync_to_async(QdrantService.get_client)()
    try:
        await sync_to_async(client.set_payload)(
            collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
            payload={"is_latest": False},
            points=point_ids,
            wait=True,
        )
    except Exception as exc:
        logger.error(
            "knowledge_vector_tombstone_failed",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
            point_count=len(point_ids),
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise


async def delete_points(point_ids: list[str]) -> None:
    """按 point id 列表物理删除旧 points（纯优化层）。

    P1：绝不按业务 filter 删（weak ordering 竞态误删新点）。
    失败吞掉但 structlog error——正确性已由 tombstone / ``is_latest``
    过滤兜底，残留旧点由 reconcile 清理。
    """
    if not point_ids:
        return
    # 首次调用经 sync ORM 读配置，async 上下文必须桥接
    client = await sync_to_async(QdrantService.get_client)()
    try:
        await sync_to_async(client.delete)(
            collection_name=DELIVERY_KNOWLEDGE_COLLECTION,
            points_selector=models.PointIdsList(points=point_ids),
            wait=True,
        )
    except Exception as exc:
        logger.error(
            "knowledge_vector_delete_failed",
            collection=DELIVERY_KNOWLEDGE_COLLECTION,
            point_count=len(point_ids),
            error=str(exc),
            error_type=type(exc).__name__,
        )

"""分支感知检索服务——在应用层合并 overlay + base collection 结果。"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from services.branch_utils import (
    get_branch_file_changes,
    is_branch_index_enabled_async,
    resolve_branch_for_query,
)
from services.qdrant_service import QdrantService

logger = structlog.get_logger(__name__)


class BranchAwareSearchService:
    """分支感知检索——封装 overlay + base 并行查询、过滤、去重、合并排序。

    所有检索入口（API / MCP 工具 / Workflow 节点）应通过此 service 获取
    分支感知结果，避免在每个入口重复实现合并逻辑。
    """

    @classmethod
    async def search(
        cls,
        repository_id: str,
        query_dense: list[float],
        *,
        query_sparse: dict[str, Any] | None = None,
        branch_name: str | None = None,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """分支感知向量检索。

        路由策略:
        1. 分支索引未启用 → 降级到旧的单 collection 路径
        2. base 分支 / resolve 失败 → 直接查 base collection
        3. inherited 分支 → 直接查 base collection
        4. 功能分支 → 并行查 overlay + base，过滤合并
        """
        if not await is_branch_index_enabled_async(repository_id):
            return await cls._search_single(
                repository_id, query_dense,
                query_sparse=query_sparse, top_k=top_k, filters=filters,
            )

        _, branch_index = await resolve_branch_for_query(repository_id, branch_name)

        if branch_index is None or branch_index.is_base_branch:
            return await cls._search_single(
                repository_id, query_dense,
                query_sparse=query_sparse, top_k=top_k, filters=filters,
            )

        if branch_index.status == "inherited":
            return await cls._search_single(
                repository_id, query_dense,
                query_sparse=query_sparse, top_k=top_k, filters=filters,
            )

        return await cls._search_branch(
            repository_id, branch_index, query_dense,
            query_sparse=query_sparse, top_k=top_k, filters=filters,
        )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @classmethod
    async def _search_single(
        cls,
        repository_id: str,
        query_dense: list[float],
        *,
        query_sparse: dict[str, Any] | None = None,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """单 collection 搜索（base 分支 / 旧路径）。"""
        if query_sparse is not None:
            return await sync_to_async(QdrantService.hybrid_search)(
                repository_id, query_dense, query_sparse,
                top_k=top_k, filters=filters,
            )
        return await sync_to_async(QdrantService.search)(
            repository_id, query_dense, top_k=top_k, filters=filters,
        )

    @classmethod
    async def _search_branch(
        cls,
        repository_id: str,
        branch_index: Any,
        query_dense: list[float],
        *,
        query_sparse: dict[str, Any] | None = None,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """功能分支搜索：并行查 overlay + base → 过滤合并。"""
        overlay_collection = branch_index.collection_name
        base_collection = QdrantService.get_collection_name(repository_id)

        if query_sparse is not None:
            overlay_coro = sync_to_async(QdrantService.hybrid_search_by_name)(
                overlay_collection, query_dense, query_sparse,
                top_k=top_k, filters=filters,
            )
            base_coro = sync_to_async(QdrantService.hybrid_search)(
                repository_id, query_dense, query_sparse,
                top_k=top_k, filters=filters,
            )
        else:
            overlay_coro = sync_to_async(QdrantService.search_by_name)(
                overlay_collection, query_dense, top_k=top_k, filters=filters,
            )
            base_coro = sync_to_async(QdrantService.search)(
                repository_id, query_dense, top_k=top_k, filters=filters,
            )

        try:
            overlay_results, base_results = await asyncio.gather(
                overlay_coro, base_coro,
            )
        except Exception:
            logger.warning(
                "overlay_search_failed_fallback_to_base",
                repository_id=repository_id,
                overlay_collection=overlay_collection,
            )
            if query_sparse is not None:
                base_results = await sync_to_async(QdrantService.hybrid_search)(
                    repository_id, query_dense, query_sparse,
                    top_k=top_k, filters=filters,
                )
            else:
                base_results = await sync_to_async(QdrantService.search)(
                    repository_id, query_dense, top_k=top_k, filters=filters,
                )
            return base_results

        return await cls._merge_results(
            overlay_results, base_results, branch_index, top_k,
        )

    @classmethod
    async def _merge_results(
        cls,
        overlay_results: list[dict[str, Any]],
        base_results: list[dict[str, Any]],
        branch_index: Any,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """合并 overlay + base 结果，overlay 覆盖同文件 chunk。"""
        added_files, modified_files, deleted_files = await get_branch_file_changes(
            branch_index,
        )

        merged: dict[tuple[str, int], dict[str, Any]] = {}
        for r in overlay_results:
            merged[cls._chunk_key(r)] = r

        for r in base_results:
            file_path = r.get("payload", {}).get("file_path", "")
            key = cls._chunk_key(r)

            if file_path in deleted_files:
                continue
            if file_path in modified_files:
                continue
            if key in merged:
                continue

            merged[key] = r

        results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    @staticmethod
    def _chunk_key(result: dict[str, Any]) -> tuple[str, int]:
        """生成 chunk 唯一标识用于去重。"""
        payload = result.get("payload", {})
        return (payload.get("file_path", ""), payload.get("chunk_index", 0))

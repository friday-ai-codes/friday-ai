"""功能点详情结构化服务（缓存优先 + 批量取 + 预热）。

Step 2 结构化（把功能点原文 → 柔性 sections）从「每次点开现算」改为「按内容哈希持久化」：

- ``aget_or_generate``：命中缓存直接返回；未命中才调 LLM 生成并写入缓存（此后不再重算）。
- ``aget_cached_map``：批量按原文取已缓存 sections（构树时附到功能点节点，点开即时零请求）。
- ``awarm``：解析阶段 best-effort 预热（并发有界），实现「第一次解析就生成好、点开秒开」。

缓存 key = ``sha256(source.strip())``，与 feature list 载体解耦。观测：
``component=initiatives.feature_detail``。
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from initiatives.models import FeatureDetailCache

logger = structlog.get_logger(__name__)

_COMPONENT = "initiatives.feature_detail"
# 预热并发上限（best-effort，避免解析时对同一 Provider 洪峰）。
_WARM_CONCURRENCY = 4


def _hash_source(source: str) -> str:
    return hashlib.sha256((source or "").strip().encode("utf-8")).hexdigest()


class FeatureDetailService:
    """功能点详情结构化 sections 的缓存编排。"""

    @sync_to_async
    def _aget_cached(self, project_id: Any, source_hash: str) -> list[Any] | None:
        row = (
            FeatureDetailCache.objects.filter(
                project_id=project_id, source_hash=source_hash
            )
            .values_list("sections", flat=True)
            .first()
        )
        return list(row) if row is not None else None

    @sync_to_async
    def _astore(self, project_id: Any, source_hash: str, sections: list[Any]) -> None:
        FeatureDetailCache.objects.update_or_create(
            project_id=project_id,
            source_hash=source_hash,
            defaults={"sections": sections},
        )

    @sync_to_async
    def _aget_many(self, project_id: Any, hashes: list[str]) -> dict[str, list[Any]]:
        rows = FeatureDetailCache.objects.filter(
            project_id=project_id, source_hash__in=hashes
        ).values_list("source_hash", "sections")
        return {h: list(s or []) for h, s in rows}

    async def aget_or_generate(self, project_id: Any, source: str) -> list[dict[str, Any]]:
        """取该原文的结构化 sections：命中缓存直接返回；未命中生成并写缓存。"""
        src = str(source or "").strip()
        if not src:
            return []
        h = _hash_source(src)
        cached = await self._aget_cached(project_id, h)
        if cached is not None:
            return cached

        from initiatives.services.feature_list_import import (
            agenerate_feature_detail_sections,
        )

        sections = await agenerate_feature_detail_sections(project_id, src)
        # 即使为空也写缓存：杜绝「每次点开都重算」（用户明确要求只算一次）。
        await self._astore(project_id, h, sections)
        return sections

    async def aget_cached_map(
        self, project_id: Any, sources: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """批量按原文取已缓存 sections（仅返回命中项），供构树时附到功能点节点。"""
        norm = {str(s or "").strip() for s in sources if str(s or "").strip()}
        if not norm:
            return {}
        hash_to_src = {_hash_source(s): s for s in norm}
        rows = await self._aget_many(project_id, list(hash_to_src.keys()))
        return {hash_to_src[h]: sec for h, sec in rows.items() if h in hash_to_src}

    async def awarm(self, project_id: Any, sources: list[str]) -> int:
        """解析阶段 best-effort 预热缓存（去重 + 并发有界）；返回成功预热的条数。"""
        targets = list(
            dict.fromkeys(
                str(s or "").strip() for s in sources if str(s or "").strip()
            )
        )
        if not targets:
            return 0
        sem = asyncio.Semaphore(_WARM_CONCURRENCY)
        warmed = 0

        async def _one(src: str) -> None:
            nonlocal warmed
            async with sem:
                try:
                    await self.aget_or_generate(project_id, src)
                    warmed += 1
                except Exception as exc:  # noqa: BLE001 — 预热 best-effort，绝不反噬解析
                    logger.warning(
                        "feature_detail_warm_failed",
                        project_id=str(project_id),
                        error_type=type(exc).__name__,
                        component=_COMPONENT,
                        category="sampling",
                    )

        await asyncio.gather(*(_one(s) for s in targets), return_exceptions=True)
        logger.info(
            "feature_detail_warmed",
            project_id=str(project_id),
            requested=len(targets),
            warmed=warmed,
            component=_COMPONENT,
            category="sampling",
        )
        return warmed


feature_detail_service = FeatureDetailService()

__all__ = ["FeatureDetailService", "feature_detail_service"]

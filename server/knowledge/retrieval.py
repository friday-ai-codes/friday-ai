"""Phase 15 检索唯一 service 收口（DeliveryKnowledgeSearchService）。

Phase 16 MCP/chat/workflow 四入口只调此模块。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from django.conf import settings
from django.utils import timezone

from knowledge.access_scope import resolve_allowed_project_ids, resolve_allowed_repository_ids
from knowledge.graph_enrichment import enrich_vector_hits
from knowledge.metadata_hydrate import hydrate_many
from knowledge.recency import compute_recency_score, fuse_vector_recency, normalize_vector_scores
from knowledge.related import fetch_related_entities
from knowledge.retrieval_types import SearchResultDTO
from knowledge.timeline import build_entity_timeline
from knowledge.toc_path import resolve_toc_paths
from knowledge.vector_recall import recall_similar_chunks

logger = structlog.get_logger(__name__)

__all__ = ["DeliveryKnowledgeSearchService"]


class DeliveryKnowledgeSearchService:
    """交付知识混合检索服务。"""

    async def search_similar(
        self,
        query: str,
        *,
        user,
        top_k: int = 10,
        entity_kinds: list[str] | None = None,
        project_ids: list[str] | None = None,
        repository_ids: list[str] | None = None,
        as_of: datetime | None = None,
        include_superseded: bool = False,
        include_document_kind: bool = False,
    ) -> list[SearchResultDTO]:
        logger.info("knowledge_search_started", query_len=len(query), top_k=top_k)
        allowed_projects = await resolve_allowed_project_ids(user, project_ids)
        allowed_repos = await resolve_allowed_repository_ids(
            user, repository_ids, project_ids=allowed_projects
        )
        if not allowed_projects:
            logger.info("knowledge_search_completed", result_count=0)
            return []

        hits = await recall_similar_chunks(
            query,
            allowed_project_ids=allowed_projects,
            allowed_repository_ids=allowed_repos,
            top_k=top_k,
            entity_kinds=entity_kinds,
            include_superseded=include_superseded,
            include_document_kind=include_document_kind,
        )
        if not hits:
            logger.info("knowledge_search_completed", result_count=0)
            return []

        enriched = await enrich_vector_hits(
            hits,
            allowed_project_ids=allowed_projects,
            allowed_repository_ids=allowed_repos,
            as_of=as_of,
        )
        reference_time = as_of or timezone.now()
        keys = [(h.entity_id, h.version) for h in hits]
        metadata_map = await hydrate_many(keys, include_superseded=include_superseded)

        # PageIndex 章节路径回溯（增强信息，失败返回空 map 不阻塞检索）
        toc_paths = await resolve_toc_paths(hits)

        vector_scores = [h.rrf_score for h in hits]
        norm_scores = normalize_vector_scores(vector_scores)

        results: list[SearchResultDTO] = []
        for hit, norm_v in zip(hits, norm_scores, strict=True):
            meta = metadata_map.get((hit.entity_id, hit.version))
            if meta is None:
                continue
            if not include_superseded and meta.superseded_hint:
                continue
            event_time = meta.event_time
            recency = compute_recency_score(event_time, reference_time=reference_time)
            final = fuse_vector_recency(norm_v, recency)
            results.append(
                SearchResultDTO(
                    score=final,
                    vector_score=norm_v,
                    recency_score=recency,
                    entity=meta,
                    related_entities=enriched.get(hit.entity_id, []),
                    toc_path=toc_paths.get(hit.point_id, []),
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        results = results[:top_k]
        results = await self._apply_llm_grades(query, results)
        logger.info("knowledge_search_completed", result_count=len(results))
        return results

    async def _apply_llm_grades(
        self, query: str, results: list[SearchResultDTO]
    ) -> list[SearchResultDTO]:
        if not settings.KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED:
            return results
        from knowledge.llm_grader import grade_search_results

        return await grade_search_results(query, results)

    async def get_timeline(
        self,
        entity_id: uuid.UUID,
        *,
        user,
        include_superseded: bool = False,
        as_of: datetime | None = None,
    ):
        return await build_entity_timeline(
            entity_id,
            user=user,
            include_superseded=include_superseded,
            as_of=as_of,
        )

    async def get_related(
        self,
        entity_id: uuid.UUID,
        *,
        user,
        direction: str = "both",
        max_hops: int = 2,
        relations: list[str] | None = None,
        as_of: datetime | None = None,
    ):
        """图关联遍历。

        ``relations``（Phase 116 VIEW-04）默认 ``None`` ⇒ 透传给
        ``fetch_related_entities`` 后落回 ``_DEFAULT_RELATIONS``，既有调用点零回归。
        """
        return await fetch_related_entities(
            entity_id,
            user=user,
            direction=direction,
            max_hops=max_hops,
            relations=relations,
            as_of=as_of,
        )

"""仓库路由服务 —— 两阶段路由（per contract/contract）。

Stage 1: BM25 关键词快速筛选 Top-10
Stage 2: Embedding 语义相似度精排 Top-3
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService

logger = structlog.get_logger(__name__)


@dataclass
class RepoRouteResult:
    """仓库路由结果（per contract）。"""

    repo_id: str
    repo_name: str
    bm25_score: float
    embedding_score: float
    final_score: float
    match_reason: str


class RepoRouter:
    """两阶段仓库路由器 —— per contract/contract。

    Stage 1: BM25 关键词快速筛选 Top-10
             (SparseEncoderService.encode + Qdrant hybrid search with RRF)
    Stage 2: 结构化关键词精排 Top-3
             (在 Stage 1 Top-10 上用 payload 结构化字段做可解释微调)
    """

    STAGE1_K: int = 10  # BM25 初筛 Top-10
    BM25_WEIGHT: float = 0.4
    EMBEDDING_WEIGHT: float = 0.6

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    @classmethod
    async def route(cls, query: str, *, top_k: int = 3) -> list[RepoRouteResult]:
        """对用户提问执行两阶段仓库路由，返回 Top-K 最相关仓库。

        Args:
            query: 用户提问/查询文本
            top_k: 最终返回的仓库数量（默认 3）

        Returns:
            list[RepoRouteResult]: 按 final_score 降序的结果列表
        """
        # Stage 1 — BM25 快速筛选
        # 1. 生成 query sparse vector
        query_sparse = await sync_to_async(SparseEncoderService.encode)(query)
        if not query_sparse.get("indices"):
            logger.warning("sparse_encode_empty", query=query[:100])
            return []

        # 2. 生成 query dense vector (供 RRF 融合用)
        # 走查询收口：长需求文本切块多探针，绝不因超长返回空（改造前 None → 静默 []）。
        from services.query_embedding import embed_query

        embedded = await embed_query(query)
        if not embedded.ok:
            logger.warning("embedding_failed", query_len=len(query or ""))
            return []
        query_dense = embedded.vectors

        # 3. 调用 hybrid_search (RRF 融合 dense + sparse, 与 L3 层一致)
        stage1_results = await sync_to_async(QdrantService.hybrid_search_multi_by_name)(
            "repo_summaries",
            query_dense,
            query_sparse,
            top_k=cls.STAGE1_K,
        )

        # 4. 无结果直接返回空
        if not stage1_results:
            logger.info("repo_router_no_matches", query=query[:100])
            return []

        # Stage 2 — 结构化关键词精排
        scored: list[dict[str, Any]] = []
        for r in stage1_results:
            payload = r.get("payload", {})
            repo_id = payload.get("repository_id", "")
            repo_name = payload.get("repo_name", "unknown")
            bm25_score = r.get("score", 0.0)

            # 使用 payload 结构化字段与 query 做关键词匹配计算 keyword_score
            keyword_score = cls._compute_keyword_score(query, payload)

            final_score = bm25_score * cls.BM25_WEIGHT + keyword_score * cls.EMBEDDING_WEIGHT

            match_reason = cls._generate_match_reason(query, payload, bm25_score)

            scored.append({
                "repo_id": repo_id,
                "repo_name": repo_name,
                "bm25_score": round(bm25_score, 4),
                "embedding_score": round(keyword_score, 4),
                "final_score": round(final_score, 4),
                "match_reason": match_reason,
            })

        # 6. 按 final_score 降序排序取 top_k
        scored.sort(key=lambda x: x["final_score"], reverse=True)
        top = scored[:top_k]

        result = [
            RepoRouteResult(
                repo_id=r["repo_id"],
                repo_name=r["repo_name"],
                bm25_score=r["bm25_score"],
                embedding_score=r["embedding_score"],
                final_score=r["final_score"],
                match_reason=r["match_reason"],
            )
            for r in top
        ]

        logger.info(
            "repo_router_completed",
            query=query[:100],
            result_count=len(result),
        )
        return result

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @classmethod
    def _compute_keyword_score(cls, query: str, payload: dict[str, Any]) -> float:
        """计算 query 与仓库摘要的语义相关分数 (0-1)。

        策略: 关键词匹配加权。检查 query 词在 tech_stack / api_domains /
        primary_symbols / description 中的出现情况。不使用额外的 Embedding API 调用
        (Stage 1 已使用了 dense，Stage 2 在已筛选的 Top-10 上用关键词微调)。
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        score = 0.0
        max_score = 10.0

        # tech_stack 匹配: 每个匹配 +2
        tech_stack_str = payload.get("tech_stack", "{}")
        try:
            tech_stack = (
                _json.loads(tech_stack_str)
                if isinstance(tech_stack_str, str)
                else tech_stack_str
            )
            if isinstance(tech_stack, dict):
                for lang in tech_stack:
                    if lang.lower() in query_lower:
                        score += 2.0
            elif isinstance(tech_stack, list):
                for lang in tech_stack:
                    if str(lang).lower() in query_lower:
                        score += 2.0
        except (_json.JSONDecodeError, TypeError):
            pass

        # api_domains 匹配: 每个匹配 +1.5
        api_domains_str = payload.get("api_domains", "[]")
        try:
            api_domains = (
                _json.loads(api_domains_str)
                if isinstance(api_domains_str, str)
                else api_domains_str
            )
            if isinstance(api_domains, list):
                for domain in api_domains:
                    if str(domain).lower() in query_lower:
                        score += 1.5
        except (_json.JSONDecodeError, TypeError):
            pass

        # primary_symbols 匹配: 每个匹配 +0.5
        primary_symbols_str = payload.get("primary_symbols", "[]")
        try:
            primary_symbols = (
                _json.loads(primary_symbols_str)
                if isinstance(primary_symbols_str, str)
                else primary_symbols_str
            )
            if isinstance(primary_symbols, list):
                for sym in primary_symbols:
                    if str(sym).lower() in query_lower:
                        score += 0.5
        except (_json.JSONDecodeError, TypeError):
            pass

        # description 关键词覆盖: query 词在 description 中出现比例 * 3
        desc = payload.get("description", "").lower()
        if desc and query_words:
            matched = sum(1 for w in query_words if w in desc)
            score += (matched / len(query_words)) * 3.0

        return min(score / max_score, 1.0)

    @classmethod
    def _generate_match_reason(
        cls, query: str, payload: dict[str, Any], bm25_score: float,
    ) -> str:
        """生成人类可读的匹配原因（per contract）。"""
        reasons: list[str] = []
        query_lower = query.lower()

        tech_stack_str = payload.get("tech_stack", "{}")
        try:
            tech_stack = (
                _json.loads(tech_stack_str)
                if isinstance(tech_stack_str, str)
                else tech_stack_str
            )
            if isinstance(tech_stack, dict):
                matched_tech = [k for k in tech_stack if k.lower() in query_lower]
            elif isinstance(tech_stack, list):
                matched_tech = [str(k) for k in tech_stack if str(k).lower() in query_lower]
            else:
                matched_tech = []
            if matched_tech:
                reasons.append(f"matched tech_stack: {', '.join(matched_tech)}")
        except (_json.JSONDecodeError, TypeError):
            pass

        api_domains_str = payload.get("api_domains", "[]")
        try:
            api_domains = (
                _json.loads(api_domains_str)
                if isinstance(api_domains_str, str)
                else api_domains_str
            )
            if isinstance(api_domains, list):
                matched_domains = [d for d in api_domains if str(d).lower() in query_lower]
                if matched_domains:
                    reasons.append(f"matched api_domains: {', '.join(matched_domains)}")
        except (_json.JSONDecodeError, TypeError):
            pass

        if reasons:
            return "; ".join(reasons)
        return f"semantic match (score: {bm25_score:.3f})"


__all__ = ["RepoRouter", "RepoRouteResult"]

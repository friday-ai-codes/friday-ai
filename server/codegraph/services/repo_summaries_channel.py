"""统一仓库路由服务的摘要级回退通道。

本模块承接原 ``RepoRouter`` 的 ``repo_summaries`` 检索算法：

1. sparse BM25 + dense embedding 经 Qdrant RRF 粗筛；
2. 在 Top-N 摘要上按技术栈、API 域、核心符号和描述做关键词微调；
3. 输出给 :class:`RepoRouterV2` 的节点索引无命中回退路径。

它不是独立业务 service；生产调用方必须使用 ``RepoRouterV2.route``。保留摘要通道的
唯一目的，是在新仓尚未生成 ``repo_index_nodes`` 或能力树暂不可用时避免直接返回空候选。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from services.qdrant_service import QdrantService
from services.sparse_encoder import SparseEncoderService

logger = structlog.get_logger(__name__)

_STAGE1_K = 10
_HYBRID_SCORE_WEIGHT = 0.4
_KEYWORD_SCORE_WEIGHT = 0.6


@dataclass(frozen=True)
class RepoSummaryRouteResult:
    """摘要级回退候选。"""

    repo_id: str
    repo_name: str
    bm25_score: float
    embedding_score: float
    final_score: float
    match_reason: str


def _safe_log(level: str, event: str, **fields: Any) -> None:
    """记录 best-effort 结构化事件，观测失败不反噬路由。"""

    try:
        getattr(logger, level)(
            event,
            category="sampling",
            component="repo_router_v2",
            **fields,
        )
    except Exception:  # noqa: BLE001
        pass


async def route_repo_summaries(
    query: str,
    *,
    top_k: int = 3,
) -> list[RepoSummaryRouteResult]:
    """通过仓库摘要执行 BM25+dense 召回与关键词微调。

    该函数只允许由 ``RepoRouterV2`` 的内部回退路径调用。
    """

    started = time.perf_counter()
    _safe_log(
        "debug",
        "repo_router_summaries_channel_started",
        query_len=len(query or ""),
        top_k=top_k,
    )
    try:
        query_sparse = await sync_to_async(SparseEncoderService.encode)(query)
        if not query_sparse.get("indices"):
            _safe_log(
                "warning",
                "repo_router_summaries_channel_completed",
                result_count=0,
                outcome="sparse_empty",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return []

        from services.query_embedding import embed_query

        embedded = await embed_query(query)
        if not embedded.ok:
            _safe_log(
                "warning",
                "repo_router_summaries_channel_completed",
                result_count=0,
                outcome="embedding_unavailable",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return []

        recalled = await sync_to_async(QdrantService.hybrid_search_multi_by_name)(
            "repo_summaries",
            embedded.vectors,
            query_sparse,
            top_k=_STAGE1_K,
        )
        scored: list[RepoSummaryRouteResult] = []
        for item in recalled:
            payload = item.get("payload", {})
            hybrid_score = float(item.get("score", 0.0))
            keyword_score = compute_keyword_score(query, payload)
            final_score = (
                hybrid_score * _HYBRID_SCORE_WEIGHT + keyword_score * _KEYWORD_SCORE_WEIGHT
            )
            scored.append(
                RepoSummaryRouteResult(
                    repo_id=str(payload.get("repository_id", "")),
                    repo_name=str(payload.get("repo_name", "unknown")),
                    bm25_score=round(hybrid_score, 4),
                    embedding_score=round(keyword_score, 4),
                    final_score=round(final_score, 4),
                    match_reason=generate_match_reason(query, payload, hybrid_score),
                )
            )

        scored.sort(key=lambda candidate: (-candidate.final_score, candidate.repo_id))
        result = scored[:top_k]
        _safe_log(
            "debug",
            "repo_router_summaries_channel_completed",
            result_count=len(result),
            outcome="ok",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return result
    except Exception as exc:
        _safe_log(
            "warning",
            "repo_router_summaries_channel_failed",
            error=redact_secrets_in_text(str(exc)),
            error_type=type(exc).__name__,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        raise


def compute_keyword_score(query: str, payload: dict[str, Any]) -> float:
    """按摘要结构化字段计算关键词微调分数（0-1）。"""

    query_lower = query.lower()
    query_words = set(query_lower.split())
    score = 0.0

    tech_stack = _decode_json(payload.get("tech_stack", "{}"), {})
    if isinstance(tech_stack, dict):
        score += sum(2.0 for lang in tech_stack if str(lang).lower() in query_lower)
    elif isinstance(tech_stack, list):
        score += sum(2.0 for lang in tech_stack if str(lang).lower() in query_lower)

    api_domains = _decode_json(payload.get("api_domains", "[]"), [])
    if isinstance(api_domains, list):
        score += sum(1.5 for domain in api_domains if str(domain).lower() in query_lower)

    primary_symbols = _decode_json(payload.get("primary_symbols", "[]"), [])
    if isinstance(primary_symbols, list):
        score += sum(0.5 for symbol in primary_symbols if str(symbol).lower() in query_lower)

    description = str(payload.get("description", "")).lower()
    if description and query_words:
        matched = sum(1 for word in query_words if word in description)
        score += (matched / len(query_words)) * 3.0

    return min(score / 10.0, 1.0)


def generate_match_reason(
    query: str,
    payload: dict[str, Any],
    hybrid_score: float,
) -> str:
    """生成摘要级候选的可解释匹配原因。"""

    query_lower = query.lower()
    reasons: list[str] = []

    tech_stack = _decode_json(payload.get("tech_stack", "{}"), {})
    values = tech_stack if isinstance(tech_stack, (dict, list)) else []
    matched_tech = [str(value) for value in values if str(value).lower() in query_lower]
    if matched_tech:
        reasons.append(f"matched tech_stack: {', '.join(matched_tech)}")

    api_domains = _decode_json(payload.get("api_domains", "[]"), [])
    if isinstance(api_domains, list):
        matched_domains = [
            str(domain) for domain in api_domains if str(domain).lower() in query_lower
        ]
        if matched_domains:
            reasons.append(f"matched api_domains: {', '.join(matched_domains)}")

    if reasons:
        return "; ".join(reasons)
    return f"semantic match (score: {hybrid_score:.3f})"


def _decode_json(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


__all__ = [
    "RepoSummaryRouteResult",
    "compute_keyword_score",
    "generate_match_reason",
    "route_repo_summaries",
]

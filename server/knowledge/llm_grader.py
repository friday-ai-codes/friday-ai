"""LLM 二阶段检索分级（Phase 15-05 ENH-02）。"""

from __future__ import annotations

import json
import re

import structlog
from django.conf import settings
from langchain_core.messages import HumanMessage, SystemMessage

from knowledge.retrieval_types import LlmGrade, SearchResultDTO

logger = structlog.get_logger(__name__)

__all__ = ["grade_search_results"]

_SNIPPET_MAX = 500
_GRADE_ORDER = {"related": 0, "duplicate": 1, "unrelated": 2}


def _truncate(text: str, limit: int = _SNIPPET_MAX) -> str:
    return text if len(text) <= limit else text[:limit]


def _parse_grades(raw: str, n: int) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", raw)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("LLM 输出必须是 JSON array")
    return data[:n]


async def grade_search_results(query: str, results: list[SearchResultDTO]) -> list[SearchResultDTO]:
    """对候选做 duplicate/related/unrelated 分级；失败降级原序。"""
    if not results or not settings.KNOWLEDGE_RETRIEVAL_LLM_RERANK_ENABLED:
        return results

    candidates = [
        {
            "entity_id": str(r.entity.entity_id),
            "kind": r.entity.entity_kind,
            "title": r.entity.title,
            "snippet": _truncate(r.entity.title),
        }
        for r in results
    ]
    system = SystemMessage(
        content="你是交付知识检索助手。根据用户 query 对候选分级：duplicate/related/unrelated，"
        "并给中文一句话理由。严格输出 JSON 数组，每项含 entity_id、grade、reason。"
    )
    human = HumanMessage(
        content=f"用户 query：{query}\n\n候选：\n{json.dumps(candidates, ensure_ascii=False)}"
    )

    try:
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve_or_error(scope="system")
        if hasattr(resolved, "code"):
            raise RuntimeError("provider missing")
        model = build_chat_model(resolved, resolved.default_model, streaming=False)
        response = await model.ainvoke([system, human])
        content = response.content if isinstance(response.content, str) else str(response.content)
        grades = _parse_grades(content, len(results))
        grade_by_id = {g.get("entity_id"): g for g in grades if isinstance(g, dict)}

        graded: list[SearchResultDTO] = []
        for r in results:
            g = grade_by_id.get(str(r.entity.entity_id), {})
            grade_raw = str(g.get("grade", "")).lower()
            grade: LlmGrade | None = grade_raw if grade_raw in _GRADE_ORDER else None
            reason = str(g.get("reason", "")) if g.get("reason") else None
            graded.append(
                SearchResultDTO(
                    score=r.score,
                    vector_score=r.vector_score,
                    recency_score=r.recency_score,
                    entity=r.entity,
                    related_entities=r.related_entities,
                    llm_grade=grade,
                    llm_reason=reason,
                )
            )
        graded.sort(
            key=lambda x: (
                _GRADE_ORDER.get(x.llm_grade or "related", 1),
                -x.score,
            )
        )
        return graded
    except Exception as exc:
        logger.warning("knowledge_llm_grade_failed", error=str(exc))
        return results

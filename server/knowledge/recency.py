"""时间衰减纯函数（Phase 15 RETR-05）。

公式：recency = exp(-ln(2) * age_days / half_life)
final_score = alpha * norm_vector + beta * recency
"""

from __future__ import annotations

import math
from datetime import datetime

from django.conf import settings

from knowledge.graph_store import require_aware

__all__ = ["compute_recency_score", "fuse_vector_recency", "normalize_vector_scores"]


def compute_recency_score(
    event_time: datetime | None,
    *,
    reference_time: datetime,
    half_life_days: float | None = None,
) -> float:
    """计算时间衰减分数；无 event_time 返回 0.5（中性）。"""
    require_aware(reference_time, "reference_time")
    if event_time is None:
        return 0.5
    require_aware(event_time, "event_time")

    half_life = half_life_days or float(settings.KNOWLEDGE_RETRIEVAL_HALF_LIFE_DAYS)
    if half_life <= 0:
        return 1.0

    age_days = max(0.0, (reference_time - event_time).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * age_days / half_life)


def normalize_vector_scores(scores: list[float]) -> list[float]:
    """Min-max 归一化向量分；单元素或全零 → [1.0, ...]。"""
    if not scores:
        return []
    if len(scores) == 1:
        return [1.0]
    lo, hi = min(scores), max(scores)
    if hi <= lo:
        return [1.0 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def fuse_vector_recency(
    vector_score: float,
    recency_score: float,
    *,
    alpha: float | None = None,
    beta: float | None = None,
) -> float:
    """融合向量分与时间衰减分。"""
    a = alpha if alpha is not None else float(settings.KNOWLEDGE_RETRIEVAL_ALPHA)
    b = beta if beta is not None else float(settings.KNOWLEDGE_RETRIEVAL_BETA)
    return a * vector_score + b * recency_score

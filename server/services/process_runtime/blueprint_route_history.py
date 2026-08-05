"""历史分量（`history_match`）—— 「同类需求近期实际合进哪个仓」（CHARTER-02，112-03 Task 2）。

**分量语义**：章程说「应该落哪」、能力树说「现在有什么」，历史说「同类需求上次真的
合进了哪个仓」——经既有 delivery knowledge 检索（`entity_kinds=[code_change,
tech_plan]`，**单次调用即覆盖 demand/code 两条分路**，不拆两次查）取落点证据。

**best-effort**：检索异常、无 acting user、空 query 一律降级返回**形状恒定**的结果并
带显式 `unavailable_reason`，绝不阻断路由。无 actor 时不伪造/提权（T-112-10 权限
fail-closed），也**不静默当 0 分**——`unavailable_reason="no_acting_user"` 会被上层写进
breakdown 证据，否则「历史证据不可得」会伪装成「历史无命中」。

**LOGGING-SPEC 强制**：新增召回必写 `RetrievalTrace` 并上报召回条数/耗时/score。
trace payload 与日志**只记指标与关联键**，需求原文与召回正文一律不进（T-112-13）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog
from asgiref.sync import sync_to_async

logger = structlog.get_logger(__name__)

__all__ = ["ascore_history_match", "HistoryMatchResult", "HISTORY_ENTITY_KINDS"]

# 历史落点召回的实体 kinds（逐字对齐 `knowledge.models.EntityKind` 实际值）。
# `["code_change", "tech_plan"]` 一次 search_similar 即覆盖 code 与 demand 两条
# 分路白名单（vector_recall 按「传入 ∩ 白名单」交集分派），无需拆两次调用；
# 未知 kind 绝不回退全量（检索侧保证返回空而非放大范围）。
HISTORY_ENTITY_KINDS = ["code_change", "tech_plan"]


@dataclass(frozen=True)
class HistoryMatchResult:
    """历史分量结果（逐仓分数 + 命中证据 + 显式降级原因）。

    `unavailable_reason` 取值：`""` 可得 / `"empty_query"` 无查询或无候选 /
    `"no_acting_user"` 无发起用户（权限 fail-closed，不伪造 actor）/
    `"retrieval_error"` 检索异常。
    """

    scores: dict[str, float] = field(default_factory=dict)
    hit_counts: dict[str, int] = field(default_factory=dict)
    top_scores: dict[str, float] = field(default_factory=dict)
    citation_ids: list[str] = field(default_factory=list)
    unavailable_reason: str = ""


@sync_to_async
def _resolve_actor(session):
    """同步解析发起人（`created_by_id` 为空时 Django 短路返回 None，不查库、不伪造）。"""
    return session.created_by


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


async def ascore_history_match(
    *,
    query: str,
    candidate_repository_ids: list[str],
    session,
    top_k_multiplier: int = 2,
) -> HistoryMatchResult:
    """算逐候选仓的 `history_match` 分量（单次检索 + 埋点 + 显式降级）。

    分数取该仓命中中的**最高 score**（而非命中数）：历史噪声多的大仓会靠命中数虚高，
    而「上次同类需求真的合进这里」这件事的强度由最相似那一条决定——用 top_score
    才是「落点相似度」而不是「仓活跃度」。命中数另存 `hit_counts` 供证据展示。
    """
    candidate_ids = [str(r) for r in (candidate_repository_ids or []) if str(r or "").strip()]
    if not str(query or "").strip() or not candidate_ids:
        return HistoryMatchResult(unavailable_reason="empty_query")

    started = time.perf_counter()
    logger.info(
        "blueprint_route_history_started",
        session_id=str(getattr(session, "id", "")),
        candidate_count=len(candidate_ids),
        kinds=HISTORY_ENTITY_KINDS,
        category="sampling",
        component="process_runtime",
    )

    try:
        from knowledge.retrieval import DeliveryKnowledgeSearchService

        actor = await _resolve_actor(session)
        if actor is None:
            # T-112-10：权限 fail-closed。绝不伪造 actor 提权，也不静默当 0 分——
            # 上层据此在 breakdown 里写 history_match_unavailable=no_acting_user。
            logger.info(
                "blueprint_route_history_completed",
                session_id=str(getattr(session, "id", "")),
                candidate_count=len(candidate_ids),
                result_count=0,
                unavailable_reason="no_acting_user",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                category="sampling",
                component="process_runtime",
            )
            return HistoryMatchResult(unavailable_reason="no_acting_user")

        results = await DeliveryKnowledgeSearchService().search_similar(
            query,
            user=actor,
            # 超采样留截断余量（候选数 * multiplier + 常数底），对齐 recall_adapter 取舍
            top_k=len(candidate_ids) * max(1, int(top_k_multiplier)) + 10,
            entity_kinds=HISTORY_ENTITY_KINDS,
            # 用候选仓收窄召回：跨全库召回的历史落点对本次路由没有区分度
            repository_ids=candidate_ids,
            include_document_kind=False,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort：检索失败不阻断路由
        from common.logging import redact_secrets_in_text

        logger.warning(
            "blueprint_route_history_failed",
            session_id=str(getattr(session, "id", "")),
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            category="sampling",
            component="process_runtime",
        )
        return HistoryMatchResult(unavailable_reason="retrieval_error")

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    allowed = set(candidate_ids)
    hit_counts: dict[str, int] = {}
    top_scores: dict[str, float] = {}
    citation_ids: list[str] = []
    for result in results or []:
        entity = getattr(result, "entity", None)
        repository_id = str(getattr(entity, "repository_id", "") or "")
        if not repository_id or repository_id not in allowed:
            continue
        try:
            score = float(getattr(result, "score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        hit_counts[repository_id] = hit_counts.get(repository_id, 0) + 1
        if score > top_scores.get(repository_id, 0.0):
            top_scores[repository_id] = score
        entity_id = str(getattr(entity, "entity_id", "") or "")
        if entity_id:
            citation_ids.append(entity_id)

    scores = {rid: _clamp(score) for rid, score in top_scores.items()}
    result_obj = HistoryMatchResult(
        scores=scores,
        hit_counts=hit_counts,
        top_scores=top_scores,
        citation_ids=list(dict.fromkeys(citation_ids)),
        unavailable_reason="",
    )
    await _record_trace(
        session=session,
        actor=actor,
        result=result_obj,
        result_count=len(results or []),
        duration_ms=duration_ms,
    )
    logger.info(
        "blueprint_route_history_completed",
        session_id=str(getattr(session, "id", "")),
        candidate_count=len(candidate_ids),
        result_count=len(results or []),
        matched_repo_count=len(scores),
        unavailable_reason="",
        duration_ms=duration_ms,
        category="sampling",
        component="process_runtime",
    )
    return result_obj


async def _record_trace(
    *,
    session,
    actor,
    result: HistoryMatchResult,
    result_count: int,
    duration_ms: float,
) -> None:
    """召回埋点（LOGGING-SPEC 强制项）：整段吞异常，观测绝不反噬路由。

    payload 只放 kinds / 计数 / score / duration_ms 与关联键（`session_id` 可回查
    需求内容）——需求原文与召回正文一律不进 payload 与日志（T-112-13）。
    """
    try:
        from interactions.ledger import arecord_retrieval_trace
        from interactions.models import RetrievalTrace

        scores = list(result.scores.values())
        await arecord_retrieval_trace(
            None,  # 编排链无 InteractionRun
            kind=RetrievalTrace.Kind.CHUNK,
            payload={
                "source": "blueprint_route_history",
                "session_id": str(getattr(session, "id", "")),
                "kinds": HISTORY_ENTITY_KINDS,
                "result_count": result_count,
                "per_repo_counts": dict(result.hit_counts),
                "scores": scores,
                "top_score": max(scores) if scores else 0,
                "duration_ms": duration_ms,
            },
            user_id=str(actor.id) if actor is not None else None,
            source="process_runtime",
        )
        # 118（LIVE-02）：把同一批标量镜像到会话事件流，让「历史落点召回了什么」在蓝图页
        # 可见。RetrievalTrace 本身**没有前端消费方**（它是留痕面），而活动流要的就是这几个
        # 数：命中条数、最高分、耗时。⛔ 召回正文仍只在 RetrievalTrace 里。
        await _aemit_retrieval_event(
            session,
            hit_count=result_count,
            top_score=max(scores) if scores else 0,
            duration_ms=duration_ms,
            matched_repository_count=len(result.hit_counts or {}),
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬路由主流程
        pass


async def _aemit_retrieval_event(session, **fields) -> None:
    """写 `blueprint.retrieval.completed`（118）。独立函数 + 独立 try：埋点失败不能让
    上面那条 RetrievalTrace 也一起丢（两者是两个不同的观测面）。"""
    try:
        from delivery.services.convergence_session_service import ConvergenceSessionService
        from delivery.services.event_taxonomy import EVENT_BLUEPRINT_RETRIEVAL_COMPLETED

        await ConvergenceSessionService().aemit_event(
            EVENT_BLUEPRINT_RETRIEVAL_COMPLETED,
            session,
            {"scope": "route_history", **dict(fields)},
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass

"""SessionCapture 评估精华 → knowledge document 投影 normalizer（EVAL-03）。

仅 medium/high 且已进入摄取阶段的 Capture 产生事件。RAG 正文只使用再次脱敏后的
``distilled_essence``；原始 question/answer 不进入正文或 payload。无项目锚的中高价值
Capture 仍保留为无边事件，等待读侧补齐可见性。
"""

from __future__ import annotations

import time

import structlog

from common.logging import redact_secrets_in_text
from knowledge.ingestion import EdgeSpec, IngestionEvent, IngestionRequest
from knowledge.models import EdgeRelation, EntityKind, EntityOrigin

logger = structlog.get_logger(__name__)

__all__ = ["normalize"]

_READY_STATUSES = frozenset({"ingest_pending", "ingesting", "ingested"})
_INDEXED_TIERS = frozenset({"medium", "high"})


def _title_from_essence(essence: str) -> str:
    """取精华首个非空行作为标题，不回退到原始问答。"""
    for line in essence.splitlines():
        title = line.strip()
        if title:
            return title[:500]
    return ""


def _log_started(*, capture_id: str, tier: str, status: str, user_id: str) -> None:
    try:
        logger.info(
            "session_capture_normalize_started",
            capture_id=capture_id,
            tier=tier,
            status=status,
            initiated_by_user_id=user_id,
            category="sampling",
            component="knowledge",
        )
    except Exception:
        pass


def _log_completed(
    *,
    capture_id: str,
    tier: str,
    status: str,
    user_id: str,
    event_count: int,
    started: float,
) -> None:
    try:
        logger.info(
            "session_capture_normalize_completed",
            capture_id=capture_id,
            tier=tier,
            status=status,
            initiated_by_user_id=user_id,
            event_count=event_count,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            category="sampling",
            component="knowledge",
        )
    except Exception:
        pass


def _log_failed(
    *,
    capture_id: str,
    tier: str,
    status: str,
    user_id: str,
    error: Exception,
    started: float,
) -> None:
    try:
        logger.error(
            "session_capture_normalize_failed",
            capture_id=capture_id,
            tier=tier,
            status=status,
            initiated_by_user_id=user_id,
            error=redact_secrets_in_text(str(error)),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            category="sampling",
            component="knowledge",
        )
    except Exception:
        pass


async def normalize(request: IngestionRequest) -> list[IngestionEvent]:
    """SessionCapture UUID → 单个精华 document 事件；不满足摄取门槛时返回空。"""
    from initiatives.models import SessionCapture
    from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService

    started = time.perf_counter()
    capture_id = request.source_id
    tier = ""
    status = "missing"
    user_id = "system"

    try:
        capture = (
            await SessionCapture.objects.select_related(
                "project",
                "project__space",
                "repository",
            )
            .filter(id=request.source_id)
            .afirst()
        )
        if capture is None:
            return []

        capture_id = str(capture.id)
        tier = capture.value_tier
        status = capture.status
        user_id = capture.initiated_by_user_id or "system"
        _log_started(
            capture_id=capture_id,
            tier=tier,
            status=status,
            user_id=user_id,
        )

        essence = capture.distilled_essence or ""
        if (
            tier not in _INDEXED_TIERS
            or status not in _READY_STATUSES
            or not essence.strip()
        ):
            _log_completed(
                capture_id=capture_id,
                tier=tier,
                status=status,
                user_id=user_id,
                event_count=0,
                started=started,
            )
            return []

        body = redact_secrets_in_text(essence)
        project = capture.project
        edges: tuple[EdgeSpec, ...] = ()
        space_id = None
        if project is not None:
            project_node_id = await ProjectKnowledgeGraphService().ensure_project_node(project)
            edges = (
                EdgeSpec(
                    relation=EdgeRelation.REFERENCES,
                    target_entity_id=project_node_id,
                ),
            )
            space_id = str(project.space_id) if project.space_id else None

        repository_id = str(capture.repository_id) if capture.repository_id else None
        project_id = str(capture.project_id) if capture.project_id else None
        event = IngestionEvent(
            kind=EntityKind.DOCUMENT,
            origin=EntityOrigin.MCP,
            source_kind="session_capture",
            source_id=capture_id,
            title=_title_from_essence(body),
            content=body,
            payload={
                "capture_id": capture_id,
                "value_tier": tier,
                "repository_id": repository_id,
                "project_id": project_id,
            },
            space_id=space_id,
            repository_id=repository_id,
            event_time=capture.evaluated_at or capture.updated_at,
            edges=edges,
        )
        _log_completed(
            capture_id=capture_id,
            tier=tier,
            status=status,
            user_id=user_id,
            event_count=1,
            started=started,
        )
        return [event]
    except Exception as exc:
        _log_failed(
            capture_id=capture_id,
            tier=tier,
            status=status,
            user_id=user_id,
            error=exc,
            started=started,
        )
        raise

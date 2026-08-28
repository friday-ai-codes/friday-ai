"""Session Capture durable 投递与数据库行恢复。

Capture 行是工作真相；队列只携带主键和 attempt。首次投递与恢复使用稳定
idempotency key，worker 内退避则创建不带该 key 的新 job。
"""

from __future__ import annotations

import datetime
import time

import structlog
from asgiref.sync import sync_to_async
from django.db.models import Q
from django.utils import timezone

from common.logging import redact_secrets_in_text
from durable.queues import QUEUE_KNOWLEDGE
from initiatives.models import SessionCapture, SessionCaptureStatus
from initiatives.services.capture_service import CaptureService

logger = structlog.get_logger(__name__)

_EVAL_TASK = "durable_session_capture_eval"
_INGEST_TASK = "durable_session_capture_ingest"
_MAX_AUTOMATIC_ATTEMPTS = 6
_PROCESSING_STALE_AFTER = datetime.timedelta(minutes=10)

_EVAL_READY = {
    SessionCaptureStatus.PENDING_EVAL,
    SessionCaptureStatus.EVAL_FAILED,
}
_INGEST_READY = {
    SessionCaptureStatus.INGEST_PENDING,
    SessionCaptureStatus.INGEST_FAILED,
}
_EVAL_RECOVERABLE = _EVAL_READY | {SessionCaptureStatus.EVALUATING}
_INGEST_RECOVERABLE = _INGEST_READY | {SessionCaptureStatus.INGESTING}


async def _defer_capture_task(
    *,
    task: str,
    capture_id: str,
    attempt: int,
    initiated_by_user_id: str | None,
    key: str,
) -> str:
    from durable.service import DurableTaskService

    return await DurableTaskService.defer(
        task,
        {"capture_id": str(capture_id), "attempt": max(0, int(attempt))},
        queue=QUEUE_KNOWLEDGE,
        idempotency_key=key,
        lock=key,
        initiated_by_user_id=initiated_by_user_id,
    )


async def enqueue_session_capture_eval(
    capture_id: str,
    *,
    initiated_by_user_id: str | None = None,
) -> str | None:
    """首次或显式手工投递 eval；终态和 processing 状态不重复投递。"""

    capture = await CaptureService.get_capture(capture_id)
    if capture is None or capture.status not in _EVAL_READY:
        return None
    actor = initiated_by_user_id or getattr(capture, "initiated_by_user_id", None)
    attempt = int(getattr(capture, "eval_attempts", 0) or 0)
    try:
        key = f"capture-eval:{capture_id}"
        return await _defer_capture_task(
            task=_EVAL_TASK,
            capture_id=str(capture_id),
            attempt=attempt,
            initiated_by_user_id=actor,
            key=key,
        )
    except Exception as exc:  # noqa: BLE001 - Capture 已落库，恢复扫描会补投
        _log_enqueue_failed("eval", capture_id, actor, exc)
        return None


async def enqueue_session_capture_ingest(
    capture_id: str,
    *,
    initiated_by_user_id: str | None = None,
) -> str | None:
    """首次或显式手工投递 ingest；终态和 processing 状态不重复投递。"""

    capture = await CaptureService.get_capture(capture_id)
    if capture is None or capture.status not in _INGEST_READY:
        return None
    actor = initiated_by_user_id or getattr(capture, "initiated_by_user_id", None)
    attempt = int(getattr(capture, "ingest_attempts", 0) or 0)
    try:
        key = f"capture-ingest:{capture_id}"
        return await _defer_capture_task(
            task=_INGEST_TASK,
            capture_id=str(capture_id),
            attempt=attempt,
            initiated_by_user_id=actor,
            key=key,
        )
    except Exception as exc:  # noqa: BLE001 - Capture 已落库，恢复扫描会补投
        _log_enqueue_failed("ingest", capture_id, actor, exc)
        return None


@sync_to_async
def _list_recoverable_captures() -> list[SessionCapture]:
    """读取 due pending/failed 与无心跳可判定的 stale processing 行。"""

    now = timezone.now()
    stale_before = now - _PROCESSING_STALE_AFTER
    due = Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)
    query = (
        Q(status=SessionCaptureStatus.PENDING_EVAL)
        | Q(
            status=SessionCaptureStatus.EVAL_FAILED,
            eval_attempts__lt=_MAX_AUTOMATIC_ATTEMPTS,
        )
        | Q(status=SessionCaptureStatus.INGEST_PENDING)
        | Q(
            status=SessionCaptureStatus.INGEST_FAILED,
            ingest_attempts__lt=_MAX_AUTOMATIC_ATTEMPTS,
        )
    ) & due
    query |= Q(
        status__in=[
            SessionCaptureStatus.EVALUATING,
            SessionCaptureStatus.INGESTING,
        ],
        updated_at__lte=stale_before,
    )
    return list(SessionCapture.objects.filter(query).order_by("updated_at")[:500])


async def recover_session_capture_tasks() -> int:
    """逐行隔离重派 stranded Capture；不重置 processing 数据库状态。"""

    from durable.service import DurableTaskService

    started = time.perf_counter()
    recovered = 0
    for capture in await _list_recoverable_captures():
        try:
            capture_id = str(capture.id)
            status = str(capture.status)
            if status in _EVAL_RECOVERABLE:
                task = _EVAL_TASK
                key = f"capture-eval:{capture_id}"
                attempt = int(getattr(capture, "eval_attempts", 0) or 0)
            elif status in _INGEST_RECOVERABLE:
                task = _INGEST_TASK
                key = f"capture-ingest:{capture_id}"
                attempt = int(getattr(capture, "ingest_attempts", 0) or 0)
            else:
                continue

            if await DurableTaskService.has_active_by_key(key):
                continue
            job_id = await _defer_capture_task(
                task=task,
                capture_id=capture_id,
                attempt=attempt,
                initiated_by_user_id=capture.initiated_by_user_id or "system",
                key=key,
            )
            if job_id:
                recovered += 1
                try:
                    logger.debug(
                        "session_capture_recovery_item_deferred",
                        category="sampling",
                        component="knowledge",
                        capture_id=capture_id,
                        status=status,
                    )
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001 - 单行故障不阻断恢复 sweep
            try:
                logger.debug(
                    "session_capture_recovery_item_failed",
                    category="sampling",
                    component="knowledge",
                    capture_id=str(getattr(capture, "id", "")),
                    status=str(getattr(capture, "status", "")),
                    error=redact_secrets_in_text(str(exc)),
                )
            except Exception:
                pass
    try:
        logger.info(
            "session_capture_recovery_completed",
            category="sampling",
            component="knowledge",
            initiated_by_user_id="system",
            status="completed",
            recovered=recovered,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
    except Exception:
        pass
    return recovered


async def recover_stranded_session_captures() -> int:
    """周期任务使用的语义化别名。"""

    return await recover_session_capture_tasks()


def _log_enqueue_failed(
    stage: str,
    capture_id: str,
    actor: str | None,
    exc: BaseException,
) -> None:
    try:
        logger.debug(
            "session_capture_enqueue_failed",
            category="sampling",
            component="knowledge",
            capture_id=str(capture_id),
            status=f"{stage}_enqueue_failed",
            initiated_by_user_id=actor or "system",
            error=redact_secrets_in_text(str(exc)),
        )
    except Exception:
        pass


__all__ = [
    "enqueue_session_capture_eval",
    "enqueue_session_capture_ingest",
    "recover_session_capture_tasks",
    "recover_stranded_session_captures",
]

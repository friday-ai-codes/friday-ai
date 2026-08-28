"""SessionCapture 唯一写入入口（STORE-01~05，INV-6）。"""

from __future__ import annotations

import hashlib
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from common.logging import redact_secrets_in_text
from initiatives.models import (
    Project,
    ProjectMember,
    SessionCapture,
    SessionCaptureStatus,
)

logger = structlog.get_logger(__name__)

__all__ = ["CapturePersistResult", "CaptureService"]

_COMPONENT = "knowledge"
_UNKNOWN = "unknown"
_UNSPECIFIED_SESSION = "unspecified"


@dataclass(frozen=True)
class CapturePersistResult:
    """一次 Capture 持久化的结果。"""

    capture: SessionCapture
    link_reason: str
    idempotent_hit: bool
    created: bool


def _scalar_or_unknown(value: Any) -> str:
    normalized = str(value).strip() if value is not None else ""
    return normalized or _UNKNOWN


def _question_hash(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class CaptureService:
    """会话问答 Capture 的 INV-6 唯一 writer。"""

    async def persist(
        self,
        *,
        question: str,
        answer: str,
        actor: Any = None,
        initiated_by_user_id: Any = None,
        session_id: Any = None,
        project_id: Any = None,
        repository_id: Any = None,
        git_url: str | None = None,
        branch_name: str | None = None,
        response_model: Any = None,
        provider: Any = None,
        input_tokens: Any = None,
        output_tokens: Any = None,
    ) -> CapturePersistResult:
        """脱敏并持久化问答；挂钩失败不影响 Capture 落库。"""

        started = time.monotonic()
        actor_id = initiated_by_user_id or getattr(actor, "id", None) or "system"
        initiated_by = str(actor_id)
        session_key = str(session_id or "").strip() or _UNSPECIFIED_SESSION
        self._log_started(initiated_by)

        try:
            redacted_question = redact_secrets_in_text(question or "")
            redacted_answer = redact_secrets_in_text(answer or "")
            project, link_reason = await self._resolve_minimal_link(
                project_id=project_id,
                repository_requested=bool(repository_id or git_url),
                actor=actor,
            )
            result = await self._create_locked(
                question=redacted_question,
                answer=redacted_answer,
                question_hash=_question_hash(redacted_question),
                session_id=session_key,
                project=project,
                link_reason=link_reason,
                branch_name=str(branch_name or "").strip(),
                initiated_by_user_id=initiated_by,
                response_model=_scalar_or_unknown(response_model),
                provider=_scalar_or_unknown(provider),
                input_tokens=_scalar_or_unknown(input_tokens),
                output_tokens=_scalar_or_unknown(output_tokens),
            )
        except Exception as exc:
            self._log_failed(started, initiated_by, exc)
            raise

        self._log_completed(started, initiated_by, result)
        return result

    @staticmethod
    @sync_to_async
    def _resolve_minimal_link(
        *, project_id: Any, repository_requested: bool, actor: Any
    ) -> tuple[Project | None, str]:
        """Plan 141-02 仅处理无锚与 project-only；仓库状态机在 141-03。"""

        if project_id is not None:
            actor_id = getattr(actor, "id", None)
            try:
                is_member = (
                    actor_id is not None
                    and ProjectMember.objects.filter(
                        project_id=project_id, user_id=actor_id
                    ).exists()
                )
                if is_member:
                    project = Project.objects.filter(pk=project_id).first()
                    if project is not None and not repository_requested:
                        return project, "project_only"
            except (TypeError, ValueError):
                pass
            return None, "project_unauthorized"
        if repository_requested:
            return None, "repo_unresolved"
        return None, "unanchored"

    @staticmethod
    @sync_to_async
    def _create_locked(
        *,
        question: str,
        answer: str,
        question_hash: str,
        session_id: str,
        project: Project | None,
        link_reason: str,
        branch_name: str,
        initiated_by_user_id: str,
        response_model: str,
        provider: str,
        input_tokens: str,
        output_tokens: str,
    ) -> CapturePersistResult:
        lookup = {
            "initiated_by_user_id": initiated_by_user_id,
            "session_id": session_id,
            "question_hash": question_hash,
        }
        try:
            with transaction.atomic():
                capture = SessionCapture.objects.create(
                    **lookup,
                    question=question,
                    answer=answer,
                    response_model=response_model,
                    provider=provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    project=project,
                    repository=None,
                    link_reason=link_reason,
                    branch_name=branch_name,
                    status=SessionCaptureStatus.PENDING_EVAL,
                )
        except IntegrityError:
            capture = SessionCapture.objects.get(**lookup)
            return CapturePersistResult(
                capture=capture,
                link_reason=capture.link_reason,
                idempotent_hit=True,
                created=False,
            )
        return CapturePersistResult(
            capture=capture,
            link_reason=capture.link_reason,
            idempotent_hit=False,
            created=True,
        )

    @staticmethod
    def _log_started(initiated_by_user_id: str) -> None:
        try:
            logger.info(
                "session_capture_persist_started",
                initiated_by_user_id=initiated_by_user_id,
                category="caller",
                component=_COMPONENT,
            )
        except Exception:  # noqa: BLE001 - 观测失败不得反噬业务
            pass

    @staticmethod
    def _log_completed(
        started: float, initiated_by_user_id: str, result: CapturePersistResult
    ) -> None:
        try:
            capture = result.capture
            logger.info(
                "session_capture_persist_completed",
                duration_ms=int((time.monotonic() - started) * 1000),
                initiated_by_user_id=initiated_by_user_id,
                capture_id=str(capture.id),
                link_reason=result.link_reason,
                repository_bound=capture.repository_id is not None,
                project_bound=capture.project_id is not None,
                session_present=capture.session_id != _UNSPECIFIED_SESSION,
                idempotent_hit=result.idempotent_hit,
                category="caller",
                component=_COMPONENT,
            )
        except Exception:  # noqa: BLE001 - 观测失败不得反噬业务
            pass

    @staticmethod
    def _log_failed(started: float, initiated_by_user_id: str, exc: Exception) -> None:
        try:
            logger.warning(
                "session_capture_persist_failed",
                duration_ms=int((time.monotonic() - started) * 1000),
                initiated_by_user_id=initiated_by_user_id,
                error=redact_secrets_in_text(str(exc)),
                category="caller",
                component=_COMPONENT,
            )
        except Exception:  # noqa: BLE001 - 观测失败不得反噬业务
            pass

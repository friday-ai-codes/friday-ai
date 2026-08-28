"""SessionCapture 唯一写入入口（STORE-01~05，INV-6）。"""

from __future__ import annotations

import hashlib
import time
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from common.logging import redact_secrets_in_text
from initiatives.models import (
    Project,
    RepoAssociation,
    SessionCapture,
    SessionCaptureStatus,
)
from knowledge.access_scope import resolve_allowed_project_ids, resolve_allowed_repository_ids
from repositories.models import Repository
from services.git_url import normalize_git_url

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
            repository, project, link_reason = await self._resolve_link(
                project_id=project_id,
                repository_id=repository_id,
                git_url=git_url,
                actor=actor,
            )
            result = await self._create_locked(
                question=redacted_question,
                answer=redacted_answer,
                question_hash=_question_hash(redacted_question),
                session_id=session_key,
                project=project,
                repository=repository,
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

    async def _resolve_link(
        self,
        *,
        project_id: Any,
        repository_id: Any,
        git_url: str | None,
        actor: Any,
    ) -> tuple[Repository | None, Project | None, str]:
        """解析并授权 Capture 关联；失败只影响 FK 与 reason，不阻断落账。"""

        repository_requested = repository_id is not None or bool(str(git_url or "").strip())
        repository: Repository | None = None
        if repository_requested:
            repository, repo_reason = await self._resolve_repository(
                repository_id=repository_id,
                git_url=git_url,
            )
            if repository is None:
                return None, None, repo_reason
            allowed_repositories = await resolve_allowed_repository_ids(
                actor,
                repository_ids=[str(repository.id)],
            )
            can_bind_repository = await self._can_bind_repository(actor, repository)
            if str(repository.id) not in allowed_repositories or not can_bind_repository:
                return None, None, "repo_unauthorized"

        project: Project | None = None
        if project_id is not None:
            project = await self._get_project(project_id)
            if project is None:
                return repository, None, "project_unresolved"
            allowed_projects = await resolve_allowed_project_ids(actor, [str(project.id)])
            is_project_member = await self._is_project_member(actor, project)
            if str(project.id) not in allowed_projects or not is_project_member:
                return repository, None, "project_unauthorized"

        if repository is None:
            if project is not None:
                return None, project, "project_only"
            return None, None, "unanchored"
        if project is None:
            return repository, None, "linked"
        if not await self._project_contains_repository(project, repository):
            return repository, None, "project_repo_mismatch"
        return repository, project, "linked_with_project"

    @staticmethod
    @sync_to_async
    def _resolve_repository(
        *, repository_id: Any, git_url: str | None
    ) -> tuple[Repository | None, str]:
        """显式 id 优先；否则仅用规范化 URL 变体查询未软删仓库。"""

        if repository_id is not None:
            try:
                parsed_id = uuid.UUID(str(repository_id))
            except (TypeError, ValueError, AttributeError):
                return None, "repo_unresolved"
            repository = Repository.objects.filter(pk=parsed_id, is_deleted=False).first()
            return (repository, "linked") if repository is not None else (None, "repo_unresolved")

        normalized = normalize_git_url(git_url)
        if not normalized:
            return None, "repo_unresolved"
        variants = {
            normalized,
            f"{normalized}/",
            f"{normalized}.git",
            f"{normalized}.git/",
        }
        matches = list(
            Repository.objects.filter(is_deleted=False, git_url__in=variants).order_by("id")[:2]
        )
        if len(matches) > 1:
            return None, "repo_ambiguous"
        if not matches:
            return None, "repo_unresolved"
        return matches[0], "linked"

    @staticmethod
    @sync_to_async
    def _get_project(project_id: Any) -> Project | None:
        try:
            parsed_id = uuid.UUID(str(project_id))
        except (TypeError, ValueError, AttributeError):
            return None
        return Project.objects.filter(pk=parsed_id).first()

    @staticmethod
    @sync_to_async
    def _project_contains_repository(project: Project, repository: Repository) -> bool:
        return project.space.repositories.filter(pk=repository.id).exists() or (
            RepoAssociation.objects.filter(project=project, repository=repository).exists()
        )

    @staticmethod
    @sync_to_async
    def _is_project_member(actor: Any, project: Project) -> bool:
        if getattr(actor, "is_superuser", False):
            return True
        actor_id = getattr(actor, "id", None)
        return bool(actor_id and project.members.filter(user_id=actor_id).exists())

    @staticmethod
    @sync_to_async
    def _can_bind_repository(actor: Any, repository: Repository) -> bool:
        if getattr(actor, "is_superuser", False):
            return True
        actor_id = getattr(actor, "id", None)
        return bool(
            actor_id
            and Project.objects.filter(
                members__user_id=actor_id,
                space__repositories=repository,
            ).exists()
        )

    @staticmethod
    @sync_to_async
    def _create_locked(
        *,
        question: str,
        answer: str,
        question_hash: str,
        session_id: str,
        project: Project | None,
        repository: Repository | None,
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
                    repository=repository,
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

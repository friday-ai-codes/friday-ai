"""为指定项目生成仓库关联候选。"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError, CommandParser

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)


def _observe(event: str, **fields: Any) -> None:
    """运维命令观测 best-effort，不记录 feature 正文。"""
    try:
        logger.info(event, category="caller", component="initiatives", **fields)
    except Exception:
        pass


class Command(BaseCommand):
    help = (
        "按 project_id 的 feature list 生成仓库候选。"
        "必须传 --initiated-by-user-id；可用 --dry-run 预览或 --confirm 确认全部候选。"
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("project_id", help="项目 UUID")
        parser.add_argument(
            "--initiated-by-user-id",
            required=True,
            help="触发本次运维操作的用户 UUID/标识",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅打印 feature 与候选仓库范围统计，不调用提案写入",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="提案后经 RepoAssociationService 确认全部候选",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        project_id = self._normalize_project_id(options.get("project_id"))
        initiated_by = str(options.get("initiated_by_user_id") or "").strip()
        if not initiated_by:
            raise CommandError("--initiated-by-user-id 不能为空")
        if options.get("dry_run") and options.get("confirm"):
            raise CommandError("--dry-run 与 --confirm 不能同时使用")

        async_to_sync(self._handle_async)(
            project_id=project_id,
            initiated_by_user_id=initiated_by,
            dry_run=bool(options.get("dry_run")),
            confirm=bool(options.get("confirm")),
        )

    @staticmethod
    def _normalize_project_id(raw: Any) -> str:
        try:
            return str(uuid.UUID(str(raw or "")))
        except (TypeError, ValueError, AttributeError) as exc:
            raise CommandError("project_id 必须是合法 UUID") from exc

    async def _handle_async(
        self,
        *,
        project_id: str,
        initiated_by_user_id: str,
        dry_run: bool,
        confirm: bool,
    ) -> None:
        from initiatives.models import Project
        from initiatives.services.context_link_service import ContextLinkService
        from initiatives.services.repo_association_service import RepoAssociationService

        started = time.perf_counter()
        fields = {
            "project_id": project_id,
            "initiated_by_user_id": initiated_by_user_id,
            "dry_run": dry_run,
            "confirm": confirm,
        }
        _observe("propose_project_repos_started", **fields)

        try:
            project = await Project.objects.select_related("space").filter(id=project_id).afirst()
            if project is None:
                raise CommandError(f"项目不存在: {project_id}")

            flat = await ContextLinkService()._afeature_corpus(project)
            space = project.space
            if dry_run:
                repo_count = await space.repositories.acount()
                self.stdout.write(
                    self.style.WARNING(
                        f"[DRY-RUN] project_id={project_id} "
                        f"feature_count={len(flat)} scoped_repo_count={repo_count}"
                    )
                )
                _observe(
                    "propose_project_repos_completed",
                    **fields,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    candidate_count=0,
                    feature_count=len(flat),
                )
                return

            service = RepoAssociationService()
            result = await service.propose(
                space=space,
                features_flat=flat,
                project=project,
                initiated_by_user_id=initiated_by_user_id,
            )
            candidates = list(result.get("candidates") or [])
            self._print_candidates(candidates)

            if confirm and candidates:
                await service.confirm_repos(
                    project=project,
                    repo_ids=[c.get("repo_id") for c in candidates if c.get("repo_id")],
                    initiated_by_user_id=initiated_by_user_id,
                )
                self.stdout.write(self.style.SUCCESS(f"已确认 {len(candidates)} 个候选仓库"))

            _observe(
                "propose_project_repos_completed",
                **fields,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                candidate_count=len(candidates),
                feature_count=len(flat),
            )
        except CommandError as exc:
            _observe(
                "propose_project_repos_failed",
                **fields,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                error=redact_secrets_in_text(str(exc))[:500],
            )
            raise
        except Exception as exc:
            safe_error = redact_secrets_in_text(str(exc))[:500]
            _observe(
                "propose_project_repos_failed",
                **fields,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                error=safe_error,
            )
            raise CommandError(f"仓库提案失败: {safe_error or '未知错误'}") from exc

    def _print_candidates(self, candidates: list[dict[str, Any]]) -> None:
        if not candidates:
            self.stdout.write("未生成仓库候选")
            return
        self.stdout.write("repo_id | name | score | confidence | reason")
        for candidate in candidates:
            self.stdout.write(
                " | ".join(
                    [
                        str(candidate.get("repo_id") or ""),
                        str(candidate.get("repo_name") or ""),
                        str(candidate.get("score") or 0),
                        str(candidate.get("confidence") or ""),
                        str(candidate.get("reason") or "").replace("\n", " ")[:200],
                    ]
                )
            )

"""把一个蓝图会话的调研派发预算清零（基础设施故障恢复后的运维口）。

背景：调研容器的重试上界按 ``RepoResearchTask.attempt`` 记，**派发即计数**。回调侧现在会
按失败归因把基础设施故障那一格退回去（见 ``services.process_runtime.failure_classification``），
但这只覆盖「归因能认出来」的那部分——归因是保守的（宁可漏判不可错判），仍会有环境问题烧掉
预算的残余情形，更不用说本次修复之前**已经**被烧光的存量会话。

于是留这个运维口：模型额度充上了、key 换好了、runner 拉起来了之后跑一次，会话就能接着走，
不必新建会话从头调研（2026-09-04 因为没有这个口，连废三个会话）。

设计红线（与 ``repair_blueprint_confirm_gate`` 同源）：

- **零新造机制**：写入一律经 ``ResearchService.reset_attempts``（``RepoResearchTask`` 的唯一
  写入面，INV-6）；本命令只负责定位会话、调度与报数。
- **异步在事务外 ``asyncio.run``**（持锁事务内调异步 ORM 会长事务持锁 / ``SynchronousOnlyOperation``）。
- **归因 system**：无触发用户的后台运维动作一律 ``initiated_by_user_id=system``。
- **观测脱敏**：只记 session_id 与计数标量。

⛔ **本命令不派容器**：清零之后由既有续驱链（作答/确认门动作、或 10 分钟一轮的僵尸恢复
扫描）自然重派。运维不必也不该在这里手工触发派发。

Usage:
    python manage.py reset_research_attempts --session-id=<uuid> [--artifact-id=<uuid>]
                                             [--keep-failed] [--dry-run]
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandError

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "清零蓝图会话的调研派发计数（attempt），并把 failed 任务放回 pending 以便重派"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--session-id",
            dest="session_id",
            default="",
            help="目标 ConvergenceSession 的 UUID（与 --artifact-id 二选一）",
        )
        parser.add_argument(
            "--artifact-id",
            dest="artifact_id",
            default="",
            help="目标蓝图 artifact 的 UUID；取指向它的最近一次 technical_blueprint 会话",
        )
        parser.add_argument(
            "--keep-failed",
            action="store_true",
            help="只清零计数，不把 failed 任务放回 pending（默认放回，否则清零了也不会被重派）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只定位与报数，不写库",
        )

    def handle(self, *args: object, **options: object) -> None:
        session_id = str(options.get("session_id") or "").strip()
        artifact_id = str(options.get("artifact_id") or "").strip()
        revive_failed = not bool(options.get("keep_failed"))
        dry_run = bool(options.get("dry_run"))
        if not session_id and not artifact_id:
            raise CommandError("必须提供 --session-id 或 --artifact-id")

        started = time.monotonic()
        try:
            outcome = asyncio.run(
                self._arun(
                    session_id=session_id,
                    artifact_id=artifact_id,
                    revive_failed=revive_failed,
                    dry_run=dry_run,
                )
            )
        except CommandError:
            raise
        except Exception as exc:  # noqa: BLE001 — 顶层兜底：转 CommandError（非 0 退出）
            logger.warning(
                "repo_research_attempts_reset_failed",
                category="caller",
                component="research_service",
                session_id=session_id,
                artifact_id=artifact_id,
                error=redact_secrets_in_text(str(exc)),
                initiated_by_user_id="system",
            )
            raise CommandError(f"重置失败：{redact_secrets_in_text(str(exc))}") from exc

        if outcome["status"] == "no_session":
            raise CommandError(
                f"未找到 technical_blueprint 会话（session_id={session_id or '-'} "
                f"artifact_id={artifact_id or '-'}）"
            )

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(
            f"{prefix}session={outcome['session_id']} "
            f"reset={outcome['reset']} revived={outcome['revived']}"
        )
        if not dry_run:
            logger.info(
                "repo_research_attempts_reset_completed",
                category="caller",
                component="research_service",
                session_id=outcome["session_id"],
                reset=outcome["reset"],
                revived=outcome["revived"],
                duration_ms=duration_ms,
                initiated_by_user_id="system",
            )

    async def _arun(
        self, *, session_id: str, artifact_id: str, revive_failed: bool, dry_run: bool
    ) -> dict[str, Any]:
        from delivery.models import ConvergenceSession, RepoResearchTask, RepoResearchTaskStatus
        from delivery.services import ResearchService

        queryset = ConvergenceSession.objects.filter(process_type="technical_blueprint")
        if session_id:
            queryset = queryset.filter(id=session_id)
        else:
            queryset = queryset.filter(current_artifact_version__artifact_id=artifact_id)
        session = await queryset.order_by("-updated_at").afirst()
        if session is None:
            return {"status": "no_session"}

        if dry_run:
            tasks = RepoResearchTask.objects.filter(session_id=session.id)
            return {
                "status": "ok",
                "session_id": str(session.id),
                "reset": await tasks.filter(attempt__gt=0).acount(),
                "revived": (
                    await tasks.filter(status=RepoResearchTaskStatus.FAILED).acount()
                    if revive_failed
                    else 0
                ),
            }

        counts = await ResearchService().reset_attempts(session.id, revive_failed=revive_failed)
        return {"status": "ok", "session_id": str(session.id), **counts}

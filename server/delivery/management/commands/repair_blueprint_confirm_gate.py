"""按 artifact_id 一键幂等刷新已打开的 repo_confirmation 确认门快照（存量修复，D-09）。

背景（本相位根因）：确认门已开后若发生重调研，旧实现的 ``open_gate`` 直接短路、不重算
快照，而 ``blueprint_resume`` 在「无待调研仓 + 门恒 open」的稳态下 advance 为 0——调研
终态（failed→done）后没有任何路径会再刷 ``BlueprintThread.options``，用户在确认门看到的
``task_status`` 永远停在陈旧值。代码修复见 ``blueprint_confirm_gate.arefresh_open_gate_snapshot``
与 ``blueprint_resume`` 短路前接线；本命令是**存量数据**的一次性修复入口：对已经处于
「快照残留 failed」的 artifact，运维部署后手动跑一次即可把快照刷到与最新
``PartialPlan`` 一致。

设计红线（与 ``expire_pending_clarifications`` 同源）：

- **零新造机制**：刷新只经 ``BlueprintConfirmGateAdapter.arefresh_open_gate_snapshot``
  （其内部行锁读改写、幂等、保留人工裁决面）；本命令只负责定位 session 与调度。
- **异步在事务外 ``asyncio.run``**（Pitfall 9：持锁事务内调异步 ORM 会长事务持锁 /
  ``SynchronousOnlyOperation``）。
- **归因 system**：无触发用户的后台运维动作一律 ``initiated_by_user_id=system``。
- **观测脱敏**：只记 artifact_id / thread_id / 计数标量，绝不打印 options 全文或凭证。

Usage:
    python manage.py repair_blueprint_confirm_gate --artifact-id=<uuid> [--dry-run]
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
    help = "按 artifact_id 幂等刷新已打开的 repo_confirmation 确认门快照（修复残留 failed 旧态）"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--artifact-id",
            dest="artifact_id",
            required=True,
            help="目标蓝图 artifact 的 UUID（如 7409c0d0-7fde-4bcf-8857-29e437610fc7）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只定位不写：报告将刷新的 session / thread，不落库",
        )

    def handle(self, *args: object, **options: object) -> None:
        artifact_id = str(options.get("artifact_id") or "").strip()
        dry_run = bool(options.get("dry_run"))
        if not artifact_id:
            raise CommandError("必须提供 --artifact-id")

        started = time.monotonic()
        try:
            outcome = asyncio.run(self._arun(artifact_id, dry_run=dry_run))
        except CommandError:
            raise
        except Exception as exc:  # noqa: BLE001 — 顶层兜底：转 CommandError（非 0 退出）
            logger.warning(
                "blueprint_confirm_gate_repair_failed",
                category="caller",
                component="process_runtime",
                artifact_id=artifact_id,
                error=redact_secrets_in_text(str(exc)),
                initiated_by_user_id="system",
            )
            raise CommandError(f"修复失败：{redact_secrets_in_text(str(exc))}") from exc

        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if outcome["status"] == "no_session":
            logger.warning(
                "blueprint_confirm_gate_repair_no_session",
                category="caller",
                component="process_runtime",
                artifact_id=artifact_id,
                duration_ms=duration_ms,
                initiated_by_user_id="system",
            )
            raise CommandError(f"未找到关联该 artifact 的 technical_blueprint 会话：{artifact_id}")
        if outcome["status"] == "no_gate":
            logger.warning(
                "blueprint_confirm_gate_repair_no_gate",
                category="caller",
                component="process_runtime",
                artifact_id=artifact_id,
                session_id=outcome["session_id"],
                duration_ms=duration_ms,
                initiated_by_user_id="system",
            )
            raise CommandError(
                f"该 artifact 当前没有打开的 repo_confirmation 确认门（无需修复）：{artifact_id}"
            )

        if dry_run:
            self.stdout.write(
                f"[dry-run] session={outcome['session_id']} thread={outcome['thread_id']} "
                f"将执行确认门快照幂等刷新（未写库）"
            )
            return

        logger.info(
            "blueprint_confirm_gate_repair_completed",
            category="caller",
            component="process_runtime",
            artifact_id=artifact_id,
            session_id=outcome["session_id"],
            thread_id=outcome["thread_id"],
            refreshed=outcome["refreshed"],
            changed_count=outcome["changed_count"],
            duration_ms=duration_ms,
            initiated_by_user_id="system",
        )
        self.stdout.write(
            f"session={outcome['session_id']} thread={outcome['thread_id']} "
            f"refreshed={outcome['refreshed']} changed={outcome['changed_count']}"
        )

    async def _arun(self, artifact_id: str, *, dry_run: bool) -> dict[str, Any]:
        """定位 session + 门线程；非 dry-run 时执行幂等刷新。返回结构化结果。"""
        from delivery.models import (
            Artifact,
            BlueprintThread,
            ConvergenceSession,
            ThreadKind,
            ThreadStatus,
        )
        from services.process_runtime.blueprint_confirm_gate import BlueprintConfirmGateAdapter

        artifact = await Artifact.objects.filter(id=artifact_id).afirst()
        if artifact is None:
            raise CommandError(f"artifact 不存在：{artifact_id}")

        # 取最近一次指向该 artifact 任一版本的 technical_blueprint 会话——refresh 需要它的
        # stage_state / session_id 才能重算 fitness 并定位门线程。
        session = await (
            ConvergenceSession.objects.filter(
                process_type="technical_blueprint",
                current_artifact_version__artifact_id=artifact_id,
            )
            .order_by("-updated_at")
            .afirst()
        )
        if session is None:
            return {"status": "no_session"}

        gate_open = await (
            BlueprintThread.objects.filter(
                artifact_id=artifact_id,
                kind=ThreadKind.REPO_CONFIRMATION,
                status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
            ).aexists()
        )
        if not gate_open:
            return {"status": "no_gate", "session_id": str(session.id)}

        thread_id = await (
            BlueprintThread.objects.filter(
                artifact_id=artifact_id,
                kind=ThreadKind.REPO_CONFIRMATION,
                status__in=[ThreadStatus.OPEN, ThreadStatus.ANSWERED],
            )
            .order_by("-created_at")
            .values_list("id", flat=True)
            .afirst()
        )

        if dry_run:
            return {
                "status": "ok",
                "session_id": str(session.id),
                "thread_id": str(thread_id or ""),
                "refreshed": False,
                "changed_count": 0,
            }

        result = await BlueprintConfirmGateAdapter().arefresh_open_gate_snapshot(session)
        return {
            "status": "ok",
            "session_id": str(session.id),
            "thread_id": str(result.get("thread_id") or thread_id or ""),
            "refreshed": bool(result.get("refreshed")),
            "changed_count": int(result.get("changed_count") or 0),
        }

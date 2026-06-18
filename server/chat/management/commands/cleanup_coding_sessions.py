"""清理 N 天前编码会话的 Claude Code SDK 会话数据（resume 支撑的 TTL 清理）。

背景：为支持「7 天内可改方案/改实现并快速回溯续跑」，``CodingSession`` 会持久化
容器回传的 ``sdk_session_id`` 与 ``sdk_transcript``（SDK 对话 transcript）。transcript
可能达数百 KB，必须设 TTL 防 DB 无限膨胀。

清理规则：
- ``sdk_session_saved_at < now - N days`` 且 ``status`` 不在活跃态
  （running / awaiting_confirmation）—— 避免清掉正在执行/等待确认会话的恢复数据。
- 命中后置空 ``sdk_transcript`` / ``sdk_session_id`` / ``sdk_session_saved_at``，
  其余业务字段（tech_plan、pr_url 等）一律保留，用户历史零损失。

清理后该会话无法再 SDK resume，改方案/回溯将自动回退到语义重建路径。

用法：
    uv run python manage.py cleanup_coding_sessions --days=7
    uv run python manage.py cleanup_coding_sessions --dry-run
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from chat.models import CodingSession

logger = structlog.get_logger(__name__)

# 活跃态：正在执行或等待用户确认，清掉恢复数据会破坏续跑，必须排除。
_ACTIVE_STATUSES = [
    CodingSession.Status.RUNNING,
    CodingSession.Status.AWAITING_CONFIRMATION,
]


class Command(BaseCommand):
    help = "清理 N 天前编码会话的 SDK 会话数据（transcript/session_id；默认 7 天）"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="保留天数阈值（sdk_session_saved_at < now-N 的记录被清理）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅打印预计清理条数，不真改",
        )

    def handle(self, *args: object, **options: Any) -> None:
        days = int(options["days"])
        dry_run = bool(options["dry_run"])

        cutoff = timezone.now() - timedelta(days=days)
        qs = (
            CodingSession.objects.filter(sdk_session_saved_at__lt=cutoff)
            .exclude(status__in=_ACTIVE_STATUSES)
            .exclude(sdk_session_id="", sdk_transcript="")
        )
        count = qs.count()

        if dry_run:
            msg = f"[dry-run] would clear SDK session data from {count} coding sessions"
            self.stdout.write(msg)
            logger.info(
                "cleanup_coding_sessions_dry_run",
                cleared=count,
                days=days,
            )
            return

        updated = qs.update(
            sdk_session_id="",
            sdk_transcript="",
            sdk_session_saved_at=None,
        )

        logger.info(
            "cleanup_coding_sessions_completed",
            cleared=updated,
            days=days,
            cutoff=cutoff.isoformat(),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"已清理 {updated} 个编码会话的 SDK 会话数据（cutoff={cutoff.isoformat()}）"
            )
        )

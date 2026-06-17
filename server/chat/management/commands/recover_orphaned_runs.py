"""恢复孤儿编排运行（zombie run）—— 从 LangGraph checkpoint 兜底落库。

背景见 ``chat/recovery.py`` 模块 docstring：``uvicorn --reload`` 热重载 / 进程
退出会在「graph 已写完终态 checkpoint」与「Django 落库 assistant 消息」之间把
收尾 task 杀掉，留下 ``OrchestrationRun.status=running/waiting`` +
``Conversation.status=running`` + 缺失 assistant 消息的孤儿 run，前端永久卡在
「正在整理回答…」。

本命令扫描所有未收尾的 run（或指定 conversation），对其中「graph 已 END 且
phase 为终态」的孤儿 run 从 checkpoint 重建落库。幂等。

用法::

    cd server
    # 扫描全部未收尾 run
    uv run python manage.py recover_orphaned_runs
    # 只恢复某个会话
    uv run python manage.py recover_orphaned_runs --conversation 3b16b945-ec8b-4c50-abec-be14d1f284a5
    # 放宽年龄闸（显式恢复时通常希望立即处理，不留避让窗口）
    uv run python manage.py recover_orphaned_runs --min-age 0
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandParser

from chat.recovery import recover_orphaned_run
from orchestration.models import OrchestrationRun

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "从 checkpoint 兜底恢复卡死的孤儿编排运行（zombie run）"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--conversation",
            dest="conversation",
            default=None,
            help="只恢复指定 conversation_id（带或不带连字符均可）",
        )
        parser.add_argument(
            "--min-age",
            dest="min_age",
            type=int,
            default=0,
            help="run 最小年龄（秒），低于该值跳过以避让在线收尾；显式恢复默认 0",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        conversation: str | None = options.get("conversation")
        min_age: int = options.get("min_age", 0)

        recovered, scanned = asyncio.run(self._run(conversation, min_age))

        if recovered:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ 扫描 {scanned} 条未收尾 run，恢复了 {recovered} 条孤儿 run"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"扫描 {scanned} 条未收尾 run，未发现可恢复的孤儿 run"
                )
            )

    async def _run(self, conversation: str | None, min_age: int) -> tuple[int, int]:
        qs = OrchestrationRun.objects.filter(
            status__in=[OrchestrationRun.Status.RUNNING, OrchestrationRun.Status.WAITING],
        ).order_by("created_at")
        if conversation:
            from uuid import UUID

            try:
                conv_key: Any = UUID(conversation)
            except ValueError:
                conv_key = conversation
            qs = qs.filter(conversation_id=conv_key)

        recovered = 0
        scanned = 0
        async for run in qs:
            scanned += 1
            try:
                if await recover_orphaned_run(run, min_age_seconds=min_age):
                    recovered += 1
                    self.stdout.write(
                        f"  ✓ recovered run={run.run_id} conversation={run.conversation_id}"
                    )
            except Exception:
                logger.exception(
                    "recover_orphaned_runs_command_error",
                    run_id=str(run.run_id),
                )
                self.stderr.write(
                    self.style.ERROR(f"  ✗ failed run={run.run_id}: see logs")
                )
        return recovered, scanned

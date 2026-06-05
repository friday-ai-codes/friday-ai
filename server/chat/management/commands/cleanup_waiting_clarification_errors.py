"""一次性数据修复：清理 initial implementation 集成漏洞导致 status=error 的 conv。

背景：work-item review round Test 2 调查发现，从 commit ``83218e04`` (initial implementation)
起，``chat/conversation_service.py`` 的 graph 收尾分发未识别新增的
``phase="waiting_clarification"``，导致 graph 正确 ``interrupt()`` 暂停后 chat
层把它当成"正常完成"调 ``do_finalize`` + ``result_metadata={}`` → ``finalize.py:67``
``status_str="unknown"`` → ``Conversation.Status.ERROR`` + ``AgentSession.Status.ERROR``。

数据库证据：``OrchestrationRun.status=completed + phase=waiting_clarification +
Conversation.status=error`` 三元组完全自相矛盾，是本 bug 的标识签名。

本命令查所有命中签名的 conv，把：

- ``Conversation.status`` 从 error → completed（assistant message 完整落库时）
  或 → interrupted（assistant message 为空时）；
- ``AgentSession.status`` 同步对齐；
- ``OrchestrationRun.status`` 从 completed → waiting（与 phase 一致）。

不删 conversation / message / trace —— 用户已有数据零损失。

**注意：** 不补建 ``ConversationIntentTrace`` —— 因为本 bug 引入之前
``ConversationIntentTrace`` 生产代码 0 个 create 位点（work-item 次因 #2），
历史 conv 没有可挽回的 trace。修复后用户重发同样 query 才能走完整 roundtrip。

用法：

    cd server
    uv run python manage.py cleanup_waiting_clarification_errors --dry-run   # 预览
    uv run python manage.py cleanup_waiting_clarification_errors --apply     # 实际改写

只跑一次；幂等 —— 重复跑不影响（条件查不到任何 row）。
"""

from __future__ import annotations

from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from agents.models import AgentSession
from chat.models import Conversation, Message
from orchestration.models import OrchestrationRun

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "清理因 initial implementation 漏分发导致 status=error 的 conversation"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            help="实际写库；省略则 dry-run 只打印将要变更的 conv",
        )
        # 显式 --dry-run flag（与默认行为等价）— 让 CLI 用户直觉对齐：
        # `--dry-run` / `--apply` 二选一明显比"省略 = dry-run"更友好。
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="显式 dry-run（与省略 --apply 等价）；与 --apply 互斥",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        apply_changes: bool = options.get("apply", False)
        dry_run_explicit: bool = options.get("dry_run", False)
        if apply_changes and dry_run_explicit:
            self.stderr.write(self.style.ERROR("--apply 与 --dry-run 互斥，请二选一"))
            return
        runs_qs = OrchestrationRun.objects.filter(
            status=OrchestrationRun.Status.COMPLETED,
            phase="waiting_clarification",
            conversation__status=Conversation.Status.ERROR,
        ).select_related("conversation")

        targets = list(runs_qs)
        if not targets:
            self.stdout.write(self.style.SUCCESS("✓ 无需修复 — 未发现命中签名的 conversation"))
            return

        self.stdout.write(
            self.style.WARNING(f"发现 {len(targets)} 条命中签名的 conversation：")
        )
        self.stdout.write(
            "  签名 = OrchestrationRun.status=completed + phase=waiting_clarification + Conversation.status=error"
        )
        self.stdout.write("")

        for run in targets:
            conv = run.conversation
            assistant_has_content = Message.objects.filter(
                conversation=conv,
                role=Message.Role.ASSISTANT,
            ).exclude(content="").exists()

            target_conv_status = (
                Conversation.Status.COMPLETED
                if assistant_has_content
                else Conversation.Status.INTERRUPTED
            )
            target_run_status = OrchestrationRun.Status.WAITING

            self.stdout.write(
                f"  conv={conv.id} ({conv.title[:30] if conv.title else '(no title)'!r})"
            )
            self.stdout.write(
                f"    Conversation.status: error → {target_conv_status}"
            )
            self.stdout.write(
                f"    OrchestrationRun.status: completed → {target_run_status} (phase=waiting_clarification 保持)"
            )

            if not apply_changes:
                continue

            with transaction.atomic():
                Conversation.objects.filter(id=conv.id).update(status=target_conv_status)
                OrchestrationRun.objects.filter(id=run.id).update(status=target_run_status)
                # AgentSession 与 conversation 同步对齐
                session_target = (
                    AgentSession.Status.COMPLETED
                    if target_conv_status == Conversation.Status.COMPLETED
                    else AgentSession.Status.SUSPENDED
                )
                AgentSession.objects.filter(
                    session_id__startswith=f"chat-{conv.id}-",
                    status=AgentSession.Status.ERROR,
                ).update(status=session_target)

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"\n✓ 已修复 {len(targets)} 条 conversation"))
            logger.info(
                "cleanup_waiting_clarification_errors_applied",
                affected_count=len(targets),
                conv_ids=[str(r.conversation_id) for r in targets],
            )
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("⚠ Dry-run：未写库；加 --apply 实际执行"))

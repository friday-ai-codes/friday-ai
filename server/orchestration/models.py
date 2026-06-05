"""编排运行模型 — graph state 的 DB 投影。"""

import uuid

from django.db import models


class OrchestrationRun(models.Model):
    """编排运行实例 — graph state 的 DB 投影。

    每次用户发消息创建一个。状态始终从 graph checkpoint 派生，
    不独立维护状态机。
    """

    class Status(models.TextChoices):
        PENDING = "pending", "待处理"
        RUNNING = "running", "运行中"
        WAITING = "waiting", "等待中"
        INTERRUPTED = "interrupted", "已中断"
        COMPLETED = "completed", "已完成"
        ERROR = "error", "错误"

    class Phase(models.TextChoices):
        PLANNING = "planning", "规划"
        EXECUTING = "executing", "执行"
        WAITING = "waiting", "等待"
        # UAT 2026-05-27 hotfix（review review round Fix #1）：
        # initial implementation 在 graph 加了 WAITING_CLARIFICATION 状态（见
        # orchestration/state.py:14），但 OrchestrationRun.Phase 当时未同步登记，
        # 导致 conversation_service.py 的分发分支拿到原始字符串 "waiting_clarification"
        # 后落到 else（被当成正常完成）。这里补登枚举值，与 graph 层 RunPhase 一致。
        # 注：phase 字段 max_length=20，"waiting_clarification" 为 21 字符 — 在
        # SQLite 下能存（动态类型），未来迁移 PG 需要把 max_length 扩到 30+ migration。
        WAITING_CLARIFICATION = "waiting_clarification", "等待澄清"
        FINALIZING = "finalizing", "收尾"
        COMPLETED = "completed", "完成"
        ERROR = "error", "错误"

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    conversation = models.ForeignKey(
        "chat.Conversation",
        on_delete=models.CASCADE,
        related_name="orchestration_runs",
    )
    thread_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="LangGraph thread_id，等于 str(conversation.id)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    phase = models.CharField(
        # review review round Fix #1：max_length 从 20 扩到 32 容纳新增 WAITING_CLARIFICATION
        # （21 字符）+ 未来潜在的更长 phase 名称。SQLite 此前能存 21 字符（动态类型
        # 不强制），但 Django 系统 check 已阻塞 makemigrations，迁移到 PG 也会 truncate，
        # 必须显式扩字段宽度。
        max_length=32,
        choices=Phase.choices,
        default=Phase.PLANNING,
    )
    checkpoint_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="最新 LangGraph checkpoint ID",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["conversation", "-created_at"]),
            models.Index(fields=["thread_id", "status"]),
        ]
        verbose_name = "编排运行"
        verbose_name_plural = "编排运行"

    def __str__(self) -> str:
        return f"OrchestrationRun({self.run_id}, {self.status})"

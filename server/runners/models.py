"""Runners app models - Runner 和 RegistrationToken。"""

import hashlib
import secrets
import uuid

from django.db import models
from django.utils import timezone


def generate_token() -> str:
    """生成随机 token。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA256 哈希 token。"""
    return hashlib.sha256(token.encode()).hexdigest()


class RegistrationToken(models.Model):
    """一次性注册令牌，用于 Runner 注册。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    description = models.CharField(max_length=200, blank=True, default="")
    scope = models.CharField(
        max_length=20,
        choices=[("global", "全局"), ("project", "项目")],
        default="global",
    )
    space = models.ForeignKey("projects.Space", on_delete=models.CASCADE, null=True, blank=True)
    # GitLab 风格预设配置（创建时设定，注册时继承到 Runner）
    tags = models.JSONField(default=list, blank=True, help_text="预设标签")
    run_untagged = models.BooleanField(default=True, help_text="运行未打标签的作业")
    is_paused = models.BooleanField(default=False, help_text="暂停接收新作业")
    is_protected = models.BooleanField(default=False, help_text="仅受保护分支")
    max_timeout = models.PositiveIntegerField(
        null=True, blank=True, help_text="最大作业超时（秒），最小 600"
    )

    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    used_by_runner = models.ForeignKey("Runner", on_delete=models.SET_NULL, null=True, blank=True)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "runner_registration_tokens"

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_used and not self.is_expired

    def __str__(self) -> str:
        return f"RegToken {self.id} ({'used' if self.is_used else 'valid'})"


def _default_tags() -> list[str]:
    return ["coding"]


class Runner(models.Model):
    """已注册的 Runner 实例。"""

    class Scope(models.TextChoices):
        GLOBAL = "global", "全局"
        PROJECT = "project", "项目"

    class Status(models.TextChoices):
        ONLINE = "online", "在线"
        OFFLINE = "offline", "离线"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    token_prefix = models.CharField(max_length=8, default="")
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.GLOBAL)
    spaces = models.ManyToManyField("projects.Space", blank=True)
    concurrent = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OFFLINE)
    version = models.CharField(max_length=50, blank=True, default="")
    is_active = models.BooleanField(default=True)
    is_paused = models.BooleanField(default=False, help_text="暂停接收新作业")
    is_protected = models.BooleanField(default=False, help_text="仅受保护分支")
    run_untagged = models.BooleanField(default=True, help_text="运行未打标签的作业")
    max_timeout = models.PositiveIntegerField(null=True, blank=True, help_text="最大作业超时（秒）")
    description = models.CharField(max_length=500, blank=True, default="")
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    tags = models.JSONField(
        default=_default_tags,
        blank=True,
        verbose_name="标签",
        help_text='Runner 能力标签，如 ["coding", "plan"]',
    )
    current_tasks = models.PositiveIntegerField(
        default=0, verbose_name="当前任务数", help_text="Runner 当前正在执行的任务数量"
    )
    channel_name = models.CharField(max_length=100, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "runners"

    def __str__(self) -> str:
        return f"Runner {self.name} ({self.status})"


class RunnerTaskAssignment(models.Model):
    """Runner-Task 关联记录，追踪任务分发历史。"""

    class Status(models.TextChoices):
        ASSIGNED = "assigned", "已分发"
        RUNNING = "running", "执行中"
        COMPLETED = "completed", "已完成"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    runner = models.ForeignKey(Runner, on_delete=models.CASCADE, related_name="task_assignments")
    session = models.ForeignKey(
        "subagent.SubAgentSession", on_delete=models.CASCADE, related_name="runner_assignments"
    )
    feishu_message_id = models.CharField(
        max_length=128, blank=True, default="",
        db_index=True,
        help_text="触发此任务的飞书消息 ID，用于断连恢复时映射",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ASSIGNED)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "runner_task_assignments"
        indexes = [
            models.Index(fields=["runner", "status"]),
            models.Index(fields=["session"]),
            models.Index(fields=["assigned_at"]),
        ]

    def __str__(self) -> str:
        return f"RunnerTaskAssignment({self.runner_id}, {self.session_id}, {self.status})"


class RunnerEvent(models.Model):
    """Runner 级别事件日志。"""

    class EventType(models.TextChoices):
        CONNECTED = "connected", "连接"
        DISCONNECTED = "disconnected", "断开"
        HEARTBEAT = "heartbeat", "心跳"
        TASK_ASSIGNED = "task_assigned", "任务分发"
        TASK_COMPLETED = "task_completed", "任务完成"
        TASK_FAILED = "task_failed", "任务失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    runner = models.ForeignKey(Runner, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "runner_events"
        indexes = [
            models.Index(fields=["runner", "-created_at"]),
            models.Index(fields=["event_type"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"RunnerEvent({self.runner_id}, {self.event_type})"

"""Prompts models: Prompt + PromptVersion (append-only versioning)。"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class PromptCategory(models.TextChoices):
    """提示词类型分类（implementation 共 5 类）。"""

    AI_NODE = "ai_node", "AI 工作流节点"
    CHAT_AGENT = "chat_agent", "对话 Agent"
    AUX_MODEL = "aux_model", "辅助小模型"
    FEISHU_BOT = "feishu_bot", "飞书群聊"
    REPO_SUMMARY = "repo_summary", "仓库智能描述"


class PromptScope(models.TextChoices):
    """提示词作用域：系统级 / 项目级。"""

    SYSTEM = "system", "系统级"
    PROJECT = "project", "项目级"


class Prompt(models.Model):
    """提示词定义 — 用 slug 作为代码引用键。

    一个 slug 在 scope=system 时全局唯一（系统级），
    在 scope=project 时每 project 唯一（项目级覆盖系统级）。
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    slug = models.CharField(
        max_length=120,
        help_text=(
            "代码引用键，如 'chat.system.developer' / "
            "'ai_node.code_review.system' / 'repo.summary_generator'"
        ),
    )
    category = models.CharField(
        max_length=20,
        choices=PromptCategory.choices,
    )
    scope = models.CharField(
        max_length=10,
        choices=PromptScope.choices,
    )
    space = models.ForeignKey(
        "projects.Space",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="prompts",
        help_text="项目级覆盖时非空；系统级为空",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    active_version = models.ForeignKey(
        "PromptVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for",
    )
    is_builtin = models.BooleanField(
        default=False,
        help_text="系统内置项（来自 data migration），禁止删除，只能编辑",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "prompts"
        verbose_name = "提示词"
        verbose_name_plural = "提示词"
        constraints = [
            # 系统级：每 slug 全局唯一
            models.UniqueConstraint(
                fields=["slug", "scope"],
                condition=models.Q(scope="system"),
                name="uq_prompt_system_slug",
            ),
            # 项目级：同一 slug 每项目唯一
            models.UniqueConstraint(
                fields=["slug", "scope", "space"],
                condition=models.Q(scope="project"),
                name="uq_prompt_project_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["slug", "scope"]),
            models.Index(fields=["category", "scope"]),
            models.Index(fields=["space", "scope"]),
        ]

    def __str__(self) -> str:
        scope_label = (
            "系统" if self.scope == PromptScope.SYSTEM else f"项目{self.space_id}"
        )
        return f"[{scope_label}] {self.slug}"


class PromptVersion(models.Model):
    """版本化历史 — append-only。

    每次 Prompt.body 变更追加一行，version 自增。
    Prompt.active_version 指针决定当前生效版本；回滚 = 切换指针。
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    prompt = models.ForeignKey(
        Prompt,
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version = models.PositiveIntegerField(
        help_text="自增版本号（每 prompt 从 1 开始）",
    )
    body = models.TextField(
        help_text="提示词正文，支持 {{variable}} 占位符（Jinja2 sandbox 渲染）",
    )
    variables_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "变量元数据：{'user_message': {'type':'str','required':True,"
            "'description':'...','default':''}}。"
            "注意这是元数据，与 body 实际 {{var}} 集合（运行时 regex 派生）可能不一致"
        ),
    )
    change_note = models.CharField(
        max_length=500,
        blank=True,
        default="",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prompt_versions"
        verbose_name = "提示词版本"
        verbose_name_plural = "提示词版本"
        constraints = [
            models.UniqueConstraint(
                fields=["prompt", "version"],
                name="uq_prompt_version",
            ),
        ]
        ordering = ["-version"]
        indexes = [
            models.Index(fields=["prompt", "-version"]),
        ]

    def __str__(self) -> str:
        return f"{self.prompt.slug} v{self.version}"

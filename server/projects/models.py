"""Projects app models - Lightweight project management."""

import secrets
import uuid
from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from feishu.models import TriggerLog
    from workflows.models.workflow import Workflow


def generate_webhook_token():
    """Generate a random webhook token."""
    return secrets.token_urlsafe(16)[:16]


class Space(models.Model):
    """Space model for managing Feishu integration (formerly Space)."""

    # 反向关系类型声明
    workflows: "QuerySet[Workflow]"
    trigger_logs: "QuerySet[TriggerLog]"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)

    # Feishu integration
    feishu_project_key = models.CharField(max_length=100, blank=True, null=True, unique=True)
    feishu_plugin_id = models.CharField(max_length=100, blank=True, null=True)
    feishu_plugin_secret_encrypted = models.TextField(blank=True, null=True)
    feishu_webhook_token = models.CharField(max_length=32, default=generate_webhook_token)
    feishu_user_key = models.CharField(max_length=100, blank=True, null=True)

    # Feishu IM App (for sending messages via Open API)
    feishu_app_id = models.CharField(
        max_length=100, blank=True, null=True,
        help_text="飞书自建应用 App ID (cli_xxx 格式)"
    )
    feishu_app_secret_encrypted = models.TextField(
        blank=True, null=True,
        help_text="飞书自建应用 App Secret (加密存储)"
    )

    # 飞书文档导出目标文件夹
    feishu_doc_folder_token = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="飞书文档导出目标文件夹 token",
    )

    # implementation（contract/contract）：v8.1 Claude configuration 字段硬删
    # 删除：claude_api_key_encrypted / claude_base_url / claude_default_model
    #       default_provider_type / default_model
    # 替代：ProviderCredential(scope="project", scope_id=project.id) + default_provider_credential_id FK

    # implementation contract contract：项目级默认 Provider 凭证（四层解析 L3）
    default_provider_credential_id = models.ForeignKey(
        "system.ProviderCredential",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_for_spaces",
        help_text="项目级默认 Provider 凭证（contract 四层解析 L3）",
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Many-to-many relationship with repositories (use string reference)
    repositories = models.ManyToManyField(
        "repositories.Repository",
        through="SpaceRepository",
        related_name="spaces",
    )

    class Meta:
        db_table = "projects"
        verbose_name = "项目"
        verbose_name_plural = "项目"

    def __str__(self):
        return self.name

    def has_feishu_config(self) -> bool:
        """Check if Feishu Plugin is configured."""
        return bool(self.feishu_plugin_id and self.feishu_plugin_secret_encrypted)

    def has_feishu_im_config(self) -> bool:
        """Check if Feishu IM App is configured."""
        return bool(self.feishu_app_id and self.feishu_app_secret_encrypted)


class RepositoryPermission(models.TextChoices):
    """仓库关联权限级别。"""

    READ_WRITE = "read_write", "读写"
    READ_ONLY = "read_only", "只读"


class SpaceRepository(models.Model):
    """Through model for Space-Repository many-to-many relationship."""

    space = models.ForeignKey(Space, on_delete=models.CASCADE)
    repository = models.ForeignKey("repositories.Repository", on_delete=models.CASCADE)
    permission_level = models.CharField(
        max_length=20,
        choices=RepositoryPermission.choices,
        default=RepositoryPermission.READ_WRITE,
        verbose_name="权限级别",
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        db_table = "project_repositories"
        unique_together = ["space", "repository"]

    def __str__(self) -> str:
        return f"{self.space.name} - {self.repository.name} ({self.permission_level})"


__all__ = [
    "Space",
    "SpaceRepository",
    "RepositoryPermission",
    "generate_webhook_token",
]

"""Repositories models: Repository and GitCredential."""
import uuid
from typing import TYPE_CHECKING
from django.db import models
if TYPE_CHECKING:
 from django.db.models import QuerySet
 from workflows.models.coding_task import CodingTask
class GitPlatform(models.TextChoices):
 """Git platform choices."""
 GITHUB = "github", "GitHub"
 GITLAB = "gitlab", "GitLab"
 GITEA = "gitea", "Gitea"
 BITBUCKET = "bitbucket", "Bitbucket"
class AuthType(models.TextChoices):
 """Authentication type choices."""
 SSH_KEY = "ssh_key", "SSH Key"
 ACCESS_TOKEN = "access_token", "Access Token"
 DEPLOY_KEY = "deploy_key", "Deploy Key"
class IndexStatus(models.TextChoices):
 """Index status choices."""
 NOT_INDEXED = "not_indexed", "未索引"
 INDEXING = "indexing", "索引中"
 INDEXED = "indexed", "已索引"
 FAILED = "failed", "索引失败"
class TriggerType(models.TextChoices):
 """索引触发类型。"""
 MANUAL = "manual", "手动触发"
 WEBHOOK = "webhook", "Webhook 触发"
 SCHEDULED = "scheduled", "定时触发"
class IndexHistoryStatus(models.TextChoices):
 """索引历史记录状态。"""
 PENDING = "pending", "等待中"
 RUNNING = "running", "运行中"
 COMPLETED = "completed", "已完成"
 FAILED = "failed", "失败"
class Repository(models.Model):
 """Repository model for Git repositories."""
 # 反向关系类型声明
 coding_tasks: "QuerySet[CodingTask]"
 credential: "GitCredential"
 index_history: "QuerySet[IndexHistory]"
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 name = models.CharField(max_length=200)
 git_url = models.CharField(max_length=500)
 git_platform = models.CharField(
 max_length=20,
 choices=GitPlatform.choices,
 default=GitPlatform.GITLAB,
 )
 default_branch = models.CharField(max_length=100, default="main")
 description = models.TextField(blank=True, null=True)
 proxy_url = models.CharField(
 max_length=500,
 blank=True,
 null=True,
 help_text="HTTP proxy URL for Git operations (e.g. http://proxy.example.com:8080)",
 )
 # Index status fields
 index_status = models.CharField(
 max_length=20,
 choices=IndexStatus.choices,
 default=IndexStatus.NOT_INDEXED,
 )
 last_indexed_at = models.DateTimeField(blank=True, null=True)
 index_error = models.TextField(blank=True, null=True)
 # Progress tracking - embedding generation
 index_total_chunks = models.IntegerField(default=0)
 index_processed_chunks = models.IntegerField(default=0)
 # Progress tracking - Qdrant write
 index_write_total = models.IntegerField(default=0)
 index_write_processed = models.IntegerField(default=0)
 # 增量索引与自动触发字段
 last_indexed_commit_sha = models.CharField(max_length=40, blank=True, null=True)
 auto_index_enabled = models.BooleanField(default=False)
 webhook_secret = models.CharField(max_length=100, blank=True, null=True)
 # Soft delete fields
 is_deleted = models.BooleanField(default=False)
 deleted_at = models.DateTimeField(blank=True, null=True)
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "repositories"
 verbose_name = "仓库"
 verbose_name_plural = "仓库"
 def __str__(self):
 return self.name
 def soft_delete(self) -> None:
 """Mark the repository as deleted."""
 from django.utils import timezone
 self.is_deleted = True
 self.deleted_at = timezone.now
 self.save(update_fields=["is_deleted", "deleted_at"])
 async def asoft_delete(self) -> None:
 """Mark the repository as deleted (async version)."""
 from django.utils import timezone
 self.is_deleted = True
 self.deleted_at = timezone.now
 await self.asave(update_fields=["is_deleted", "deleted_at"])
class IndexHistory(models.Model):
 """索引操作历史记录，追踪每次索引的完整元数据。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 repository = models.ForeignKey(
 Repository,
 on_delete=models.CASCADE,
 related_name="index_history",
 )
 trigger_type = models.CharField(max_length=20, choices=TriggerType.choices)
 status = models.CharField(
 max_length=20,
 choices=IndexHistoryStatus.choices,
 default=IndexHistoryStatus.PENDING,
 )
 from_sha = models.CharField(max_length=40, blank=True, null=True)
 to_sha = models.CharField(max_length=40, blank=True, null=True)
 files_added = models.IntegerField(default=0)
 files_modified = models.IntegerField(default=0)
 files_deleted = models.IntegerField(default=0)
 error_message = models.TextField(blank=True, null=True)
 summary_text = models.TextField(blank=True, null=True, help_text="人可读的差异摘要文本")
 started_at = models.DateTimeField(blank=True, null=True)
 finished_at = models.DateTimeField(blank=True, null=True)
 created_at = models.DateTimeField(auto_now_add=True)
 class Meta:
 db_table = "index_history"
 ordering = ["-created_at"]
 verbose_name = "索引历史"
 verbose_name_plural = "索引历史"
 def __str__(self) -> str:
 return f"{self.repository.name} - {self.trigger_type} ({self.status})"
class GitCredential(models.Model):
 """Git credential model for authentication."""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 repository = models.OneToOneField(
 Repository,
 on_delete=models.CASCADE,
 related_name="credential",
 )
 auth_type = models.CharField(
 max_length=20,
 choices=AuthType.choices,
 default=AuthType.ACCESS_TOKEN,
 )
 ssh_key_encrypted = models.TextField(blank=True, null=True)
 encrypted_token = models.TextField(blank=True, null=True)
 git_user_name = models.CharField(max_length=200, default="Friday Codes AI Agent")
 git_user_email = models.CharField(max_length=200, default="ai@friday.codes")
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "git_credentials"
 verbose_name = "Git 凭证"
 verbose_name_plural = "Git 凭证"
 def __str__(self):
 return f"Credential for {self.repository.name}"

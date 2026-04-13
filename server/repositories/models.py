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
class BranchIndexStatus(models.TextChoices):
 """分支索引状态。"""
 NOT_INDEXED = "not_indexed", "未索引"
 INDEXING = "indexing", "索引中"
 INDEXED = "indexed", "已索引"
 INHERITED = "inherited", "继承自基础分支"
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
class AISummaryStatus(models.TextChoices):
 """AI 描述生成状态。"""
 NOT_STARTED = "not_started", "未生成"
 PENDING = "pending", "等待中"
 RUNNING = "running", "生成中"
 COMPLETED = "completed", "已完成"
 FAILED = "failed", "生成失败"
class Repository(models.Model):
 """Repository model for Git repositories."""
 # 反向关系类型声明
 coding_tasks: "QuerySet[CodingTask]"
 credential: "GitCredential"
 index_history: "QuerySet[IndexHistory]"
 file_indexes: "QuerySet[FileIndex]"
 branch_indexes: "QuerySet[RepositoryBranchIndex]"
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
 base_branch = models.CharField(
 max_length=100,
 null=True,
 blank=True,
 help_text="索引基础分支，为空时回退到 default_branch",
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
 # AI 描述生成字段（Phase）
 ai_summary = models.TextField(null=True, blank=True)
 ai_summary_status = models.CharField(
 max_length=20,
 choices=AISummaryStatus.choices,
 default=AISummaryStatus.NOT_STARTED,
 )
 ai_summary_generated_at = models.DateTimeField(null=True, blank=True)
 ai_summary_error = models.TextField(blank=True, default="")
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
class FileIndex(models.Model):
 """文件级索引记录——DB 级幂等性保障，替代 Qdrant hash 比较。
 通过 unique_together(repository, file_path) 约束确保多进程部署下
 同一文件不会被重复索引。
 """
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 repository = models.ForeignKey(
 Repository,
 on_delete=models.CASCADE,
 related_name="file_indexes",
 )
 file_path = models.CharField(max_length=1000)
 file_hash = models.CharField(max_length=64)
 indexed_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "file_indexes"
 verbose_name = "文件索引记录"
 verbose_name_plural = "文件索引记录"
 constraints = [
 models.UniqueConstraint(
 fields=["repository", "file_path"],
 name="uq_repo_file_path",
 ),
 ]
 def __str__(self) -> str:
 return f"{self.file_path} ({self.file_hash[:8]})"
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
class RepositoryBranchIndex(models.Model):
 """分支索引记录——追踪每个分支的索引状态与 overlay collection 映射。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 repository = models.ForeignKey(
 Repository,
 on_delete=models.CASCADE,
 related_name="branch_indexes",
 )
 branch_name = models.CharField(max_length=200)
 is_base_branch = models.BooleanField(default=False)
 head_sha = models.CharField(max_length=40, blank=True, null=True)
 merge_base_sha = models.CharField(max_length=40, blank=True, null=True)
 last_indexed_commit_sha = models.CharField(max_length=40, blank=True, null=True)
 last_indexed_at = models.DateTimeField(blank=True, null=True)
 is_stale = models.BooleanField(default=False)
 status = models.CharField(
 max_length=20,
 choices=BranchIndexStatus.choices,
 default=BranchIndexStatus.NOT_INDEXED,
 )
 effective_chunks_count = models.IntegerField(default=0)
 collection_name = models.CharField(max_length=300, blank=True, null=True)
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "repository_branch_indexes"
 verbose_name = "分支索引"
 verbose_name_plural = "分支索引"
 constraints = [
 models.UniqueConstraint(
 fields=["repository", "branch_name"],
 name="uq_repo_branch",
 ),
 ]
 def __str__(self) -> str:
 return f"{self.repository.name}:{self.branch_name} ({self.status})"
class BranchFileIndex(models.Model):
 """分支内文件级变更记录——追踪 overlay 中每个文件的变更类型。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 branch_index = models.ForeignKey(
 RepositoryBranchIndex,
 on_delete=models.CASCADE,
 related_name="file_indexes",
 )
 file_path = models.CharField(max_length=1000)
 change_type = models.CharField(max_length=20)
 indexed_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "branch_file_indexes"
 verbose_name = "分支文件索引"
 verbose_name_plural = "分支文件索引"
 constraints = [
 models.UniqueConstraint(
 fields=["branch_index", "file_path"],
 name="uq_branch_file",
 ),
 ]
 def __str__(self) -> str:
 return f"{self.file_path} ({self.change_type})"

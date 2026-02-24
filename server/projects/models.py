"""Projects app models - Lightweight project management."""
import secrets
import uuid
from typing import TYPE_CHECKING
from django.db import models
if TYPE_CHECKING:
 from django.db.models import QuerySet
 from feishu.models import TriggerLog
 from workflows.models.workflow import Workflow
def generate_webhook_token:
 """Generate a random webhook token."""
 return secrets.token_urlsafe(16)[:16]
class Project(models.Model):
 """Project model for managing Feishu integration."""
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
 # Claude configuration
 claude_api_key_encrypted = models.TextField(blank=True, null=True)
 claude_base_url = models.CharField(max_length=500, blank=True, null=True)
 claude_default_model = models.CharField(max_length=200, blank=True, null=True)
 # Timestamps
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 # Many-to-many relationship with repositories (use string reference)
 repositories = models.ManyToManyField(
 "repositories.Repository",
 through="ProjectRepository",
 related_name="projects",
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
class ProjectRepository(models.Model):
 """Through model for Project-Repository many-to-many relationship."""
 project = models.ForeignKey(Project, on_delete=models.CASCADE)
 repository = models.ForeignKey("repositories.Repository", on_delete=models.CASCADE)
 class Meta:
 db_table = "project_repositories"
 unique_together = ["project", "repository"]
__all__ = [
 "Project",
 "ProjectRepository",
 "generate_webhook_token",
]

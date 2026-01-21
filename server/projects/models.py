"""Projects app models - Lightweight project management."""
import secrets
import uuid
from django.db import models
def generate_webhook_token:
 """Generate a random webhook token."""
 return secrets.token_urlsafe(16)[:16]
class Project(models.Model):
 """Project model for managing Feishu integration."""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 name = models.CharField(max_length=200)
 description = models.TextField(blank=True, null=True)
 # Feishu integration
 feishu_project_key = models.CharField(max_length=100, blank=True, null=True, unique=True)
 feishu_plugin_id = models.CharField(max_length=100, blank=True, null=True)
 feishu_plugin_secret_encrypted = models.TextField(blank=True, null=True)
 feishu_webhook_token = models.CharField(max_length=32, default=generate_webhook_token)
 feishu_user_key = models.CharField(max_length=100, blank=True, null=True)
 # Claude configuration
 claude_api_key_encrypted = models.TextField(blank=True, null=True)
 claude_base_url = models.CharField(max_length=500, blank=True, null=True)
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
 """Check if Feishu is configured."""
 return bool(self.feishu_plugin_id and self.feishu_plugin_secret_encrypted)
class ProjectRepository(models.Model):
 """Through model for Project-Repository many-to-many relationship."""
 project = models.ForeignKey(Project, on_delete=models.CASCADE)
 repository = models.ForeignKey("repositories.Repository", on_delete=models.CASCADE)
 class Meta:
 db_table = "project_repositories"
 unique_together = ["project", "repository"]
# Re-export for backward compatibility
# These are now in repositories.models
def get_repository_model:
 """Get Repository model from repositories app."""
 from repositories.models import Repository
 return Repository
def get_git_credential_model:
 """Get GitCredential model from repositories app."""
 from repositories.models import GitCredential
 return GitCredential
# Backward compatibility imports (deprecated)
# Import these from repositories.models instead
from repositories.models import Repository, GitCredential, GitPlatform, AuthType
__all__ = [
 "Project",
 "ProjectRepository",
 "generate_webhook_token",
 # Backward compatibility (deprecated - use repositories.models)
 "Repository",
 "GitCredential",
 "GitPlatform",
 "AuthType",
]

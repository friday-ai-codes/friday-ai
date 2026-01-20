"""Projects app models."""
import secrets
import uuid
from django.db import models
def generate_webhook_token:
 """Generate a random webhook token."""
 return secrets.token_urlsafe(16)[:16]
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
class Project(models.Model):
 """Project model for managing Git repositories and Feishu integration."""
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
 # Many-to-many relationship with repositories
 repositories = models.ManyToManyField(
 "Repository",
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
class Repository(models.Model):
 """Repository model for Git repositories."""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 name = models.CharField(max_length=200)
 git_url = models.CharField(max_length=500)
 git_platform = models.CharField(
 max_length=20,
 choices=GitPlatform.choices,
 default=GitPlatform.GITHUB,
 )
 default_branch = models.CharField(max_length=100, default="main")
 claude_md_path = models.CharField(max_length=500, default="developer-notes.md")
 description = models.TextField(blank=True, null=True)
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "repositories"
 verbose_name = "仓库"
 verbose_name_plural = "仓库"
 def __str__(self):
 return self.name
class ProjectRepository(models.Model):
 """Through model for Project-Repository many-to-many relationship."""
 project = models.ForeignKey(Project, on_delete=models.CASCADE)
 repository = models.ForeignKey(Repository, on_delete=models.CASCADE)
 class Meta:
 db_table = "project_repositories"
 unique_together = ["project", "repository"]
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
 git_user_name = models.CharField(max_length=200, default="Friday AI Agent")
 git_user_email = models.CharField(max_length=200, default="ai-agent@friday.dev")
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "git_credentials"
 verbose_name = "Git 凭证"
 verbose_name_plural = "Git 凭证"
 def __str__(self):
 return f"Credential for {self.repository.name}"

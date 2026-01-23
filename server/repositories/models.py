"""Repositories models: Repository and GitCredential."""
import uuid
from django.db import models
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
class Repository(models.Model):
 """Repository model for Git repositories."""
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
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "repositories"
 verbose_name = "仓库"
 verbose_name_plural = "仓库"
 def __str__(self):
 return self.name
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

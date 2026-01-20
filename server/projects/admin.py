"""Projects admin configuration."""
from django.contrib import admin
from .models import GitCredential, Project, ProjectRepository, Repository
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
 """Admin for Project model."""
 list_display = ["name", "feishu_project_key", "has_feishu_config", "created_at"]
 list_filter = ["created_at"]
 search_fields = ["name", "feishu_project_key"]
 ordering = ["-created_at"]
 def has_feishu_config(self, obj):
 return obj.has_feishu_config
 has_feishu_config.boolean = True
 has_feishu_config.short_description = "飞书已配置"
@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
 """Admin for Repository model."""
 list_display = ["name", "git_url", "git_platform", "default_branch", "created_at"]
 list_filter = ["git_platform", "created_at"]
 search_fields = ["name", "git_url"]
 ordering = ["-created_at"]
@admin.register(GitCredential)
class GitCredentialAdmin(admin.ModelAdmin):
 """Admin for GitCredential model."""
 list_display = ["repository", "auth_type", "git_user_name", "created_at"]
 list_filter = ["auth_type"]
 search_fields = ["repository__name"]
 ordering = ["-created_at"]
@admin.register(ProjectRepository)
class ProjectRepositoryAdmin(admin.ModelAdmin):
 """Admin for ProjectRepository model."""
 list_display = ["project", "repository"]
 list_filter = ["project"]

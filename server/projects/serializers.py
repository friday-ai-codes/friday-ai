"""Projects app serializers."""
from rest_framework import serializers
from .models import GitCredential, Project, Repository
class RepositorySerializer(serializers.ModelSerializer):
 """Serializer for Repository model."""
 has_credential = serializers.SerializerMethodField
 class Meta:
 model = Repository
 fields = [
 "id",
 "name",
 "git_url",
 "git_platform",
 "default_branch",
 "claude_md_path",
 "description",
 "created_at",
 "updated_at",
 "has_credential",
 ]
 read_only_fields = ["id", "created_at", "updated_at"]
 def get_has_credential(self, obj):
 return hasattr(obj, "credential") and obj.credential is not None
class RepositoryCreateSerializer(serializers.ModelSerializer):
 """Serializer for creating Repository with credential."""
 access_token = serializers.CharField(write_only=True)
 git_user_name = serializers.CharField(default="Friday Codes AI Agent")
 git_user_email = serializers.CharField(default="ai@friday.codes")
 class Meta:
 model = Repository
 fields = [
 "name",
 "git_url",
 "git_platform",
 "default_branch",
 "claude_md_path",
 "description",
 "access_token",
 "git_user_name",
 "git_user_email",
 ]
class ProjectSerializer(serializers.ModelSerializer):
 """Serializer for Project model."""
 has_feishu_config = serializers.SerializerMethodField
 webhook_token = serializers.CharField(source="feishu_webhook_token", read_only=True)
 repositories = RepositorySerializer(many=True, read_only=True)
 class Meta:
 model = Project
 fields = [
 "id",
 "name",
 "description",
 "feishu_project_key",
 "has_feishu_config",
 "webhook_token",
 "repositories",
 "created_at",
 "updated_at",
 ]
 read_only_fields = ["id", "created_at", "updated_at"]
 def get_has_feishu_config(self, obj):
 return obj.has_feishu_config
class ProjectCreateSerializer(serializers.ModelSerializer):
 """Serializer for creating Project."""
 class Meta:
 model = Project
 fields = ["name", "description", "feishu_project_key"]
class ProjectUpdateSerializer(serializers.ModelSerializer):
 """Serializer for updating Project."""
 class Meta:
 model = Project
 fields = ["name", "description", "feishu_project_key"]
 extra_kwargs = {field: {"required": False} for field in fields}
class FeishuConfigSerializer(serializers.Serializer):
 """Serializer for Feishu configuration."""
 project_key = serializers.CharField(source="feishu_project_key", read_only=True)
 plugin_id = serializers.CharField(source="feishu_plugin_id", read_only=True)
 user_key = serializers.CharField(source="feishu_user_key", read_only=True)
 has_plugin_secret = serializers.SerializerMethodField
 is_configured = serializers.SerializerMethodField
 def get_has_plugin_secret(self, obj):
 return bool(obj.feishu_plugin_secret_encrypted)
 def get_is_configured(self, obj):
 return obj.has_feishu_config
class FeishuConfigCreateSerializer(serializers.Serializer):
 """Serializer for creating/updating Feishu configuration."""
 plugin_id = serializers.CharField
 plugin_secret = serializers.CharField(write_only=True)
 user_key = serializers.CharField(required=False, allow_blank=True)
class ClaudeConfigSerializer(serializers.Serializer):
 """Serializer for Claude configuration."""
 has_api_key = serializers.BooleanField
 base_url = serializers.CharField(allow_null=True)
 config_source = serializers.CharField(source="source")
class ClaudeConfigCreateSerializer(serializers.Serializer):
 """Serializer for creating/updating Claude configuration."""
 api_key = serializers.CharField(required=False, allow_blank=True, allow_null=True)
 base_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
class WebhookTokenSerializer(serializers.Serializer):
 """Serializer for webhook token."""
 webhook_token = serializers.CharField
class WebhookTokenUpdateSerializer(serializers.Serializer):
 """Serializer for updating webhook token."""
 token = serializers.CharField(max_length=32)
class GitCredentialSerializer(serializers.ModelSerializer):
 """Serializer for GitCredential model."""
 has_ssh_key = serializers.SerializerMethodField
 has_access_token = serializers.SerializerMethodField
 class Meta:
 model = GitCredential
 fields = [
 "id",
 "repository_id",
 "auth_type",
 "git_user_name",
 "git_user_email",
 "created_at",
 "has_ssh_key",
 "has_access_token",
 ]
 read_only_fields = ["id", "created_at"]
 def get_has_ssh_key(self, obj):
 return bool(obj.ssh_key_encrypted)
 def get_has_access_token(self, obj):
 return bool(obj.encrypted_token)
class RepositoryWithProjectsSerializer(RepositorySerializer):
 """Serializer for Repository with associated projects."""
 projects = serializers.SerializerMethodField
 class Meta(RepositorySerializer.Meta):
 fields = RepositorySerializer.Meta.fields + ["projects"]
 def get_projects(self, obj):
 return [{"id": str(p.id), "name": p.name} for p in obj.projects.all]

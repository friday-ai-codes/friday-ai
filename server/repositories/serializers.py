"""Repositories serializers."""
from rest_framework import serializers
from .models import GitCredential, Repository
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
class RepositoryWithProjectsSerializer(RepositorySerializer):
 """Serializer for Repository with associated projects."""
 projects = serializers.SerializerMethodField
 class Meta(RepositorySerializer.Meta):
 fields = RepositorySerializer.Meta.fields + ["projects"]
 def get_projects(self, obj):
 return [{"id": str(p.id), "name": p.name} for p in obj.projects.all]
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

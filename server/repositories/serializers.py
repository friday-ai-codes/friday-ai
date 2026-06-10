"""Repositories serializers."""

from rest_framework import serializers

from .models import GitCredential, Repository


def validate_https_git_url(git_url: str) -> str:
    """仅允许与 Access Token 认证兼容的 HTTPS 仓库地址。"""
    if not git_url.startswith(("http://", "https://")):
        raise serializers.ValidationError(
            "当前仅支持 HTTPS 仓库 URL；SSH URL 需要 SSH Key，暂未支持。"
        )
    return git_url


class RepositorySerializer(serializers.ModelSerializer):
    """Serializer for Repository model."""

    has_credential = serializers.SerializerMethodField()
    linked_projects_count = serializers.SerializerMethodField()

    class Meta:
        model = Repository
        fields = [
            "id",
            "name",
            "git_url",
            "git_platform",
            "default_branch",
            "base_branch",
            "description",
            "proxy_url",
            "auto_index_enabled",
            "auto_build_graph_enabled",
            "webhook_secret",
            "index_status",
            "last_indexed_at",
            "created_at",
            "updated_at",
            "has_credential",
            "linked_projects_count",
            "ai_summary",
            "ai_summary_status",
            "ai_summary_generated_at",
            "ai_summary_error",
            # contract freshness 字段（contract/contract）
            "remote_head_sha",
            "remote_head_checked_at",
            "behind_commits",
            "last_indexed_commit_sha",
            # implementation-01：图谱进度 6 字段（全 read-only，由
            # 后端 indexer / graph_builder 控写；auto_build_graph_enabled
            # implementation 已暴露为 read-write，不在此列）。
            "graph_build_status",
            "graph_stage",
            "current_graph_file",
            "graph_files_processed",
            "graph_files_total",
            "graph_last_built_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "webhook_secret",
            "index_status",
            "last_indexed_at",
            "ai_summary",
            "ai_summary_status",
            "ai_summary_generated_at",
            "ai_summary_error",
            "remote_head_sha",
            "remote_head_checked_at",
            "behind_commits",
            "last_indexed_commit_sha",
            "graph_build_status",
            "graph_stage",
            "current_graph_file",
            "graph_files_processed",
            "graph_files_total",
            "graph_last_built_at",
        ]

    def get_has_credential(self, obj: Repository) -> bool:
        return hasattr(obj, "credential") and obj.credential is not None

    def get_linked_projects_count(self, obj: Repository) -> int:
        """返回关联到此仓库的项目数量。"""
        return obj.projects.count()

    def validate_git_url(self, value: str) -> str:
        return validate_https_git_url(value)


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
            "base_branch",
            "description",
            "proxy_url",
            "access_token",
            "git_user_name",
            "git_user_email",
        ]

    def validate_git_url(self, value: str) -> str:
        return validate_https_git_url(value)


class RepositoryWithProjectsSerializer(RepositorySerializer):
    """Serializer for Repository with associated projects."""

    projects = serializers.SerializerMethodField()

    class Meta(RepositorySerializer.Meta):
        fields = RepositorySerializer.Meta.fields + ["projects"]

    def get_projects(self, obj):
        return [{"id": str(p.id), "name": p.name} for p in obj.projects.all()]


class GitCredentialSerializer(serializers.ModelSerializer):
    """Serializer for GitCredential model."""

    has_ssh_key = serializers.SerializerMethodField()
    has_access_token = serializers.SerializerMethodField()

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

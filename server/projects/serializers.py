"""Spaces app serializers."""

from __future__ import annotations

from rest_framework import serializers

from permissions.models import ProjectMembership
from repositories.models import GitCredential, Repository

from .models import Project, ProjectRepository, RepositoryPermission


class RepositorySerializer(serializers.ModelSerializer):
    """Serializer for Repository model."""

    has_credential = serializers.SerializerMethodField()

    class Meta:
        model = Repository
        fields = [
            "id",
            "name",
            "git_url",
            "git_platform",
            "default_branch",
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
            "access_token",
            "git_user_name",
            "git_user_email",
        ]


class SpaceSerializer(serializers.ModelSerializer):
    """Serializer for Space (Project) model."""

    has_feishu_config = serializers.SerializerMethodField()
    webhook_token = serializers.SerializerMethodField()
    repositories = serializers.SerializerMethodField()
    execution_count = serializers.SerializerMethodField()
    recent_work_items = serializers.SerializerMethodField()
    admins = serializers.SerializerMethodField()

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
            "execution_count",
            "recent_work_items",
            "admins",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_has_feishu_config(self, obj):
        return obj.has_feishu_config()

    def get_webhook_token(self, obj):
        """Webhook Token 属配置敏感项，仅空间管理员/系统管理员可见（#12）。

        空间 ``key``（feishu_project_key）对所有成员可见，但 webhook token 仅管理员可见。
        无 request 上下文（如创建响应直出）时不暴露。
        """
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        if getattr(user, "is_superuser", False):
            return obj.feishu_webhook_token
        admins = getattr(obj, "admin_memberships", None)
        if admins is not None:
            is_admin = any(str(m.user_id) == str(user.id) for m in admins)
        else:
            is_admin = ProjectMembership.objects.filter(
                user=user, project=obj, role="admin"
            ).exists()
        return obj.feishu_webhook_token if is_admin else None

    def get_admins(self, obj):
        """空间管理员列表（role=admin 成员），便于前端展示"找谁"。

        优先用 ViewSet 预取的 ``admin_memberships``（to_attr），避免 N+1。
        """
        memberships = getattr(obj, "admin_memberships", None)
        if memberships is None:
            memberships = list(
                obj.memberships.filter(role="admin").select_related("user")
            )
        return [
            {
                "id": str(m.user.id),
                "username": m.user.username,
                "display_name": getattr(m.user, "display_name", "") or m.user.username,
            }
            for m in memberships
        ]

    def get_repositories(self, obj):
        """Return only non-deleted repositories (already filtered via Prefetch in ViewSet)."""
        return RepositorySerializer(obj.repositories.all(), many=True).data

    def get_execution_count(self, obj):
        return getattr(obj, 'execution_count', 0)

    def get_recent_work_items(self, obj):
        logs = obj.trigger_logs.exclude(work_item_name="").order_by("-created_at")[:3]
        return [{"id": log.work_item_id, "name": log.work_item_name} for log in logs]


class SpaceCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating Space."""

    class Meta:
        model = Project
        fields = ["name", "description", "feishu_project_key"]


class SpaceUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating Space."""

    class Meta:
        model = Project
        fields = ["name", "description", "feishu_project_key"]
        extra_kwargs = {field: {"required": False} for field in fields}


class FeishuConfigSerializer(serializers.Serializer):
    """Serializer for Feishu configuration."""

    project_key = serializers.CharField(source="feishu_project_key", read_only=True)
    plugin_id = serializers.CharField(source="feishu_plugin_id", read_only=True)
    user_key = serializers.CharField(source="feishu_user_key", read_only=True)
    has_plugin_secret = serializers.SerializerMethodField()
    is_configured = serializers.SerializerMethodField()

    def get_has_plugin_secret(self, obj):
        return bool(obj.feishu_plugin_secret_encrypted)

    def get_is_configured(self, obj):
        return obj.has_feishu_config()


class FeishuConfigCreateSerializer(serializers.Serializer):
    """Serializer for creating/updating Feishu configuration."""

    plugin_id = serializers.CharField()
    plugin_secret = serializers.CharField(write_only=True)
    user_key = serializers.CharField(required=False, allow_blank=True)


# implementation（contract）：ClaudeConfigSerializer / ClaudeConfigCreateSerializer 整体硬删。
# 替代：implementation ProviderCredentialSerializer（system/serializers.py）+ 空间级 scope。


class WebhookTokenSerializer(serializers.Serializer):
    """Serializer for webhook token."""

    webhook_token = serializers.CharField()


class WebhookTokenUpdateSerializer(serializers.Serializer):
    """Serializer for updating webhook token."""

    token = serializers.CharField(max_length=32)


class FeishuIMConfigSerializer(serializers.Serializer):
    """Serializer for Feishu IM App configuration (read)."""

    app_id = serializers.CharField(source="feishu_app_id", read_only=True)
    has_app_secret = serializers.SerializerMethodField()
    is_configured = serializers.SerializerMethodField()

    def get_has_app_secret(self, obj):
        return bool(obj.feishu_app_secret_encrypted)

    def get_is_configured(self, obj):
        return obj.has_feishu_im_config()


class FeishuIMConfigCreateSerializer(serializers.Serializer):
    """Serializer for creating/updating Feishu IM App configuration."""

    app_id = serializers.CharField(
        help_text="飞书自建应用 App ID (cli_xxx 格式)"
    )
    app_secret = serializers.CharField(
        write_only=True,
        help_text="飞书自建应用 App Secret"
    )


class FeishuIMTestSerializer(serializers.Serializer):
    """Serializer for testing Feishu IM message sending."""

    user_id = serializers.CharField(
        help_text="飞书用户 ID (ou_xxx 格式)，可在飞书管理后台 > 成员管理中查看"
    )
    message = serializers.CharField(
        default="这是一条测试消息，来自 Friday AI Agent 配置测试。",
        help_text="测试消息内容"
    )


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


class RepositoryWithSpacesSerializer(RepositorySerializer):
    """Serializer for Repository with associated spaces."""

    spaces = serializers.SerializerMethodField()

    class Meta(RepositorySerializer.Meta):
        fields = RepositorySerializer.Meta.fields + ["spaces"]

    def get_spaces(self, obj):
        return [{"id": str(p.id), "name": p.name} for p in obj.projects.all()]


class SpaceRepositorySerializer(serializers.ModelSerializer):
    """序列化空间仓库关联记录。"""

    repository_id = serializers.UUIDField(source="repository.id", read_only=True)
    repository_name = serializers.CharField(source="repository.name", read_only=True)

    class Meta:
        model = ProjectRepository
        fields = [
            "id",
            "repository_id",
            "repository_name",
            "permission_level",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class SpaceRepositoryCreateSerializer(serializers.Serializer):
    """批量关联仓库请求。"""

    repository_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        help_text="仓库 ID 列表",
    )


class SpaceRepositoryUpdateSerializer(serializers.Serializer):
    """更新关联权限级别。"""

    permission_level = serializers.ChoiceField(
        choices=RepositoryPermission.choices,
        help_text="权限级别: read_write | read_only",
    )

"""Accounts serializers."""

import hashlib

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password as dj_validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Invitation, User


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "is_active",
            "is_superuser",
            "source",
            "created_at",
        ]
        read_only_fields = ["id", "source", "created_at"]


class MeSerializer(serializers.ModelSerializer):
    """当前用户信息序列化器（包含空间关系和 gravatar）。"""

    gravatar_url = serializers.SerializerMethodField()
    space_memberships = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "display_name",
            "gravatar_url",
            "is_superuser",
            "is_active",
            "space_memberships",
            "created_at",
        ]
        read_only_fields = list(fields)

    def get_gravatar_url(self, obj: User) -> str | None:
        if not obj.email:
            return None
        email_hash = hashlib.md5(obj.email.lower().strip().encode()).hexdigest()
        return f"https://www.gravatar.com/avatar/{email_hash}?d=identicon&s=80"

    def get_space_memberships(self, obj: User) -> list[dict[str, str]]:
        # 注意：此方法在同步上下文中调用（由调用方 sync_to_async 包装）
        from permissions.models import SpaceMembership

        memberships = SpaceMembership.objects.filter(user=obj).select_related("space")
        return [
            {
                "space_id": str(m.space.id),
                "space_name": m.space.name,
                "role": m.role,
            }
            for m in memberships
        ]


class ProfileUpdateSerializer(serializers.Serializer):
    """用户个人资料更新序列化器。"""

    display_name = serializers.CharField(max_length=100, required=True, allow_blank=True)


class InvitationCreateSerializer(serializers.Serializer):
    """创建邀请请求。"""

    email = serializers.EmailField(required=False, allow_blank=True, default="")


class InvitationResponseSerializer(serializers.ModelSerializer):
    """邀请创建响应。"""

    class Meta:
        model = Invitation
        fields = ["id", "token", "email", "expires_at", "created_at"]


class InvitationAcceptSerializer(serializers.Serializer):
    """接受邀请请求。"""

    token = serializers.CharField(max_length=64)
    username = serializers.CharField(max_length=150, min_length=3)
    password = serializers.CharField(min_length=6, write_only=True)
    display_name = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )


class LoginSerializer(serializers.Serializer):
    """Serializer for login request."""

    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs: dict) -> dict:
        username = attrs.get("username")
        password = attrs.get("password")

        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError("用户名或密码错误")
        if not user.is_active:
            raise serializers.ValidationError("用户已被禁用")

        attrs["user"] = user
        return attrs


class LoginResponseSerializer(serializers.Serializer):
    """Serializer for login response."""

    access_token = serializers.CharField()
    user = UserSerializer()
    must_change_password = serializers.BooleanField()


class TokenResponseSerializer(serializers.Serializer):
    """Serializer for token refresh response."""

    access_token = serializers.CharField()


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for password change request."""

    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=6)


class ForceChangePasswordSerializer(serializers.Serializer):
    """Serializer for force password change request (no old password required)."""

    new_password = serializers.CharField(write_only=True, min_length=6)


class AdminProfileSerializer(serializers.ModelSerializer):
    """Serializer for admin profile response."""

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "is_superuser", "created_at", "updated_at"]
        read_only_fields = ["id", "is_superuser", "created_at", "updated_at"]


class AdminProfileUpdateSerializer(serializers.Serializer):
    """Serializer for admin profile update request."""

    username = serializers.CharField(max_length=150, required=False)
    display_name = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_username(self, value: str) -> str:
        """Check that the username is not already taken by another user."""
        user: User | None = self.context.get("user")
        if user is None:
            raise serializers.ValidationError("用户上下文缺失")
        if User.objects.exclude(pk=user.pk).filter(username=value).exists():
            raise serializers.ValidationError("该用户名已被使用")
        return value


class SetupInitSerializer(serializers.Serializer):
    """首启初始化请求体校验。

    在 sync_to_async 包装内的线程中执行 DB 查询（由调用方
    await sync_to_async(serializer.is_valid)(raise_exception=True) 包装），安全。
    """

    username = serializers.CharField(
        min_length=1,
        max_length=150,
        error_messages={"blank": "用户名不能为空"},
    )
    password = serializers.CharField(
        min_length=8,
        error_messages={"min_length": "密码至少 8 位"},
    )
    display_name = serializers.CharField(
        required=False,
        default="系统管理员",
        max_length=150,
    )

    def validate_username(self, value: str) -> str:
        """用户名唯一性校验（在 sync_to_async 包装内的线程中安全执行）。"""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("该用户名已被使用")
        return value

    def validate_password(self, value: str) -> str:
        """密码强度校验：复用 settings.AUTH_PASSWORD_VALIDATORS（ADMIN-01）。

        传入未保存的 User(username=...) 实例，使「密码与用户名过于相似」校验生效。
        Django 校验器错误消息因 LANGUAGE_CODE=zh-hans 已为中文，直接透传为字段错误。
        在调用方 await sync_to_async(serializer.is_valid) 包装的线程中安全执行。
        """
        username = self.initial_data.get("username", "") if self.initial_data else ""
        tmp_user = User(username=username)
        try:
            dj_validate_password(value, user=tmp_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

"""Space members serializers."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from permissions.models import SpaceMembership, SpaceRole

User = get_user_model()


class MemberUserSerializer(serializers.ModelSerializer):
    """项目成员的用户信息（内嵌）。"""

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "email", "is_active"]


class ProjectMembershipSerializer(serializers.ModelSerializer):
    """项目成员关系序列化器（响应）。"""

    user = MemberUserSerializer(read_only=True)

    class Meta:
        model = SpaceMembership
        fields = ["id", "user", "role", "joined_at"]


class MemberAddSerializer(serializers.Serializer):
    """添加项目成员请求。"""

    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=SpaceRole.choices, default=SpaceRole.MEMBER)


class MemberUpdateSerializer(serializers.Serializer):
    """更新项目成员角色请求。"""

    role = serializers.ChoiceField(choices=SpaceRole.choices)

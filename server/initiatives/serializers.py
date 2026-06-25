"""initiatives app serializers（项目聚合根 REST 契约）。"""

from __future__ import annotations

from rest_framework import serializers

from initiatives.models import Project, ProjectMember, ProjectRole, ProjectStatus


class ProjectMemberUserSerializer(serializers.Serializer):
    """成员用户信息（内嵌，只读）。"""

    id = serializers.UUIDField(read_only=True)
    username = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)


class ProjectMemberSerializer(serializers.ModelSerializer):
    """项目成员关系序列化（响应）。"""

    user = ProjectMemberUserSerializer(read_only=True)

    class Meta:
        model = ProjectMember
        fields = ["id", "user", "role", "created_at"]
        read_only_fields = ["id", "created_at"]


class ProjectSerializer(serializers.ModelSerializer):
    """项目详情序列化（响应）。"""

    space_id = serializers.UUIDField(source="space.id", read_only=True)
    space_name = serializers.CharField(source="space.name", read_only=True)
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "space_id",
            "space_name",
            "name",
            "description",
            "status",
            "feishu_project_key",
            "feishu_board_url",
            "feishu_board_id",
            "created_by_id",
            "member_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_member_count(self, obj) -> int:
        return getattr(obj, "member_count", None) or obj.members.count()


class ProjectCreateSerializer(serializers.Serializer):
    """创建项目请求（PROJ-05）。"""

    space_id = serializers.UUIDField()
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    feishu_project_key = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=100
    )
    feishu_board_url = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1000
    )
    feishu_board_id = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=100
    )


class ProjectUpdateSerializer(serializers.Serializer):
    """更新项目请求（仅可变字段，不含 status）。"""

    name = serializers.CharField(required=False, max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    feishu_board_url = serializers.CharField(
        required=False, allow_blank=True, max_length=1000
    )
    feishu_board_id = serializers.CharField(
        required=False, allow_blank=True, max_length=100
    )


class ProjectTransitionSerializer(serializers.Serializer):
    """项目状态流转请求（PROJ-02）。"""

    to_status = serializers.ChoiceField(choices=ProjectStatus.choices)


class ProjectMemberAddSerializer(serializers.Serializer):
    """添加项目成员请求（MEMBER-01）。"""

    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(
        choices=ProjectRole.choices, default=ProjectRole.BACKEND
    )


class ProjectMemberUpdateSerializer(serializers.Serializer):
    """变更成员角色请求（不含 owner）。"""

    role = serializers.ChoiceField(choices=ProjectRole.choices)


class ProjectOwnerTransferSerializer(serializers.Serializer):
    """转移主R 请求（MEMBER-02）。"""

    new_owner_user_id = serializers.UUIDField()

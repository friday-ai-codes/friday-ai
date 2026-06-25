"""initiatives app serializers（项目聚合根 REST 契约）。"""

from __future__ import annotations

from rest_framework import serializers

from initiatives.models import (
    Artifact,
    ArtifactCarrier,
    ArtifactType,
    MergeRequest,
    Project,
    ProjectMember,
    ProjectMemory,
    ProjectMemoryDraft,
    ProjectRole,
    ProjectStatus,
)


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


# ---- 工件类型（ARTIFACT-01/05）----


class ArtifactTypeSerializer(serializers.ModelSerializer):
    """工件类型序列化（响应）。"""

    class Meta:
        model = ArtifactType
        fields = [
            "id",
            "key",
            "name",
            "carrier",
            "ragable",
            "enabled",
            "builtin",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ArtifactTypeCreateSerializer(serializers.Serializer):
    """新增自定义工件类型请求（超管）。"""

    key = serializers.SlugField(max_length=80)
    name = serializers.CharField(max_length=100)
    carrier = serializers.ChoiceField(choices=ArtifactCarrier.choices)
    ragable = serializers.BooleanField(default=False)
    enabled = serializers.BooleanField(default=True)


class ArtifactTypeUpdateSerializer(serializers.Serializer):
    """更新工件类型请求（name/carrier/ragable/enabled；禁用即 enabled=False）。"""

    name = serializers.CharField(required=False, max_length=100)
    carrier = serializers.ChoiceField(required=False, choices=ArtifactCarrier.choices)
    ragable = serializers.BooleanField(required=False)
    enabled = serializers.BooleanField(required=False)


# ---- 工件实例（ARTIFACT-02/03）----


class ArtifactSerializer(serializers.ModelSerializer):
    """工件实例序列化（响应）。"""

    type_key = serializers.CharField(source="type.key", read_only=True)
    type_name = serializers.CharField(source="type.name", read_only=True)
    ragable = serializers.BooleanField(source="type.ragable", read_only=True)

    class Meta:
        model = Artifact
        fields = [
            "id",
            "project_id",
            "type_id",
            "type_key",
            "type_name",
            "ragable",
            "carrier",
            "title",
            "url",
            "content_ref",
            "version",
            "contributor_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ArtifactCreateSerializer(serializers.Serializer):
    """新建工件请求（ARTIFACT-02）。"""

    type_id = serializers.UUIDField()
    title = serializers.CharField(max_length=300)
    carrier = serializers.ChoiceField(
        required=False, allow_blank=True, default="", choices=ArtifactCarrier.choices
    )
    url = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)
    content_ref = serializers.CharField(required=False, allow_blank=True, default="")


class ArtifactUpdateSerializer(serializers.Serializer):
    """更新工件请求（ARTIFACT-03 md/内部可编辑）。"""

    title = serializers.CharField(required=False, max_length=300)
    carrier = serializers.ChoiceField(required=False, choices=ArtifactCarrier.choices)
    url = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    content_ref = serializers.CharField(required=False, allow_blank=True)


# ---- 知识关联（KLINK-01/02）----


class ProjectKnowledgeLinkSerializer(serializers.Serializer):
    """关联一个已存在的知识实体到项目（KLINK-01）。"""

    entity_id = serializers.UUIDField()
    relation = serializers.CharField(required=False, default="REFERENCES", max_length=30)


# ---- 项目记忆（MEM-01~04）----


class ProjectMemorySerializer(serializers.ModelSerializer):
    """项目记忆序列化（响应）。"""

    class Meta:
        model = ProjectMemory
        fields = [
            "id",
            "project_id",
            "content",
            "contributor_id",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProjectMemoryCreateSerializer(serializers.Serializer):
    """新增项目记忆请求（MEM-01）。"""

    content = serializers.CharField()


class ProjectMemoryEditSerializer(serializers.Serializer):
    """编辑项目记忆请求（MEM-03）。"""

    content = serializers.CharField()


class ProjectMemoryDraftSerializer(serializers.ModelSerializer):
    """项目记忆草稿序列化（响应，MEM-04）。"""

    class Meta:
        model = ProjectMemoryDraft
        fields = [
            "id",
            "project_id",
            "content",
            "status",
            "source_conversation_id",
            "proposed_by_id",
            "confirmed_memory_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProjectMemoryDistillSerializer(serializers.Serializer):
    """从成员会话蒸馏记忆草稿请求（MEM-04）。"""

    conversation_id = serializers.UUIDField()


# ---- MergeRequest（MR-01）----


class MergeRequestSerializer(serializers.ModelSerializer):
    """MR 实体序列化（响应）。"""

    class Meta:
        model = MergeRequest
        fields = [
            "id",
            "project_id",
            "repository_id",
            "work_item_id",
            "platform",
            "external_id",
            "url",
            "title",
            "source_branch",
            "target_branch",
            "status",
            "review_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

"""initiatives app serializers（项目聚合根 REST 契约）。"""

from __future__ import annotations

from rest_framework import serializers

from initiatives.models import (
    ApiStatus,
    Artifact,
    ArtifactCarrier,
    ArtifactType,
    BranchSource,
    MergeRequest,
    Project,
    ProjectBranch,
    ProjectDoc,
    ProjectMember,
    ProjectMemory,
    ProjectMemoryDraft,
    ProjectRole,
    ProjectStateApi,
    ProjectStatus,
    ProjectVisibility,
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
            "visibility",
            "feishu_project_key",
            "feishu_board_url",
            "feishu_board_id",
            "feishu_folder_token",
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
    """更新项目请求（仅可变字段，不含 status；含 visibility 翻转，WS-02/03）。

    ``feishu_folder_token`` 不可经此 PATCH（仅后台 set_folder_token 可写，Pitfall 3）。
    """

    name = serializers.CharField(required=False, max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        required=False, choices=ProjectVisibility.choices
    )
    feishu_board_url = serializers.CharField(
        required=False, allow_blank=True, max_length=1000
    )
    feishu_board_id = serializers.CharField(
        required=False, allow_blank=True, max_length=100
    )


class ProjectRehomeSerializer(serializers.Serializer):
    """项目改归空间请求（WS-03）。"""

    new_space_id = serializers.UUIDField()


class ProjectDocSerializer(serializers.ModelSerializer):
    """项目工作区文件容器序列化（响应，DOC-01~05）。"""

    class Meta:
        model = ProjectDoc
        fields = [
            "id",
            "project_id",
            "doc_type",
            "feishu_document_id",
            "feishu_doc_token",
            "sync_status",
            "last_synced_revision",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProjectStateApiSerializer(serializers.ModelSerializer):
    """项目结构化 API 清单条目序列化（响应，DOC-02）。"""

    class Meta:
        model = ProjectStateApi
        fields = [
            "id",
            "project_id",
            "method",
            "path",
            "params",
            "description",
            "request_fields",
            "response_fields",
            "status",
            "source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ProjectStateApiCreateSerializer(serializers.Serializer):
    """手动新增结构化 API 清单条目请求（DOC-02 + #5 完整 schema；source 固定 manual 由 view 注入）。"""

    method = serializers.CharField(max_length=10)
    path = serializers.CharField(max_length=500)
    params = serializers.JSONField(required=False, default=dict)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    request_fields = serializers.JSONField(required=False, default=list)
    response_fields = serializers.JSONField(required=False, default=list)
    status = serializers.ChoiceField(
        required=False, choices=ApiStatus.choices, default=ApiStatus.PLANNED
    )


class ProjectStateApiUpdateSerializer(serializers.Serializer):
    """更新单条结构化 API 清单条目请求（DOC-02 + #5）：仅可变字段，全部可选。"""

    method = serializers.CharField(required=False, max_length=10)
    path = serializers.CharField(required=False, max_length=500)
    params = serializers.JSONField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    request_fields = serializers.JSONField(required=False)
    response_fields = serializers.JSONField(required=False)
    status = serializers.ChoiceField(required=False, choices=ApiStatus.choices)


# ---- 工作区单文档内容 + 人工区写回（WB-03，84-01）----


class ProjectDocBlockSerializer(serializers.Serializer):
    """工作区文档单 block（系统区/人工区分区，响应）。

    **wire 契约单一来源**：字段名 snake_case，84-02 前端 TS 接口须照此对齐。
    """

    block_id = serializers.CharField(read_only=True)
    db_ref = serializers.CharField(read_only=True, allow_blank=True)
    section = serializers.CharField(read_only=True)
    text = serializers.CharField(read_only=True, allow_blank=True)
    editable = serializers.BooleanField(read_only=True)


class ProjectDocContentSerializer(serializers.Serializer):
    """工作区单文档渲染内容 + block 分区（响应，WB-03）。

    **wire 契约单一来源**：``rendered_markdown`` / ``sync_status`` /
    ``last_synced_revision`` / ``blocks[*]`` 字段名即前端契约（84-02 W2 约束照此对齐）。
    """

    doc_type = serializers.CharField(read_only=True)
    sync_status = serializers.CharField(read_only=True)
    last_synced_revision = serializers.IntegerField(read_only=True)
    rendered_markdown = serializers.CharField(read_only=True, allow_blank=True)
    blocks = ProjectDocBlockSerializer(many=True, read_only=True)


class ProjectDocHumanBlockInputSerializer(serializers.Serializer):
    """人工区写回单 block 入参（请求；仅 block_id + text）。"""

    block_id = serializers.CharField(max_length=200)
    text = serializers.CharField(allow_blank=True, trim_whitespace=False)


class ProjectDocHumanBlocksWriteSerializer(serializers.Serializer):
    """人工区写回请求（WB-03；blocks 至少一项，写回触发同步引擎 block 级回灌）。"""

    blocks = ProjectDocHumanBlockInputSerializer(many=True, allow_empty=False)


# ---- feature list 树 + 进度灯（WB-02，84-01）----


class ProjectFeatureNodeSerializer(serializers.Serializer):
    """单个功能点节点（功能点 + 验收项 + 四态进度灯，响应）。

    **wire 契约单一来源**：``name`` / ``acceptance`` / ``progress`` /
    ``status_display_name`` 字段名即前端契约。
    """

    name = serializers.CharField(read_only=True)
    acceptance = serializers.ListField(
        child=serializers.CharField(), read_only=True
    )
    progress = serializers.CharField(read_only=True)
    status_display_name = serializers.CharField(read_only=True, allow_blank=True)


class ProjectFeatureModuleSerializer(serializers.Serializer):
    """模块节点（模块名 + 功能点列表，响应）。"""

    module = serializers.CharField(read_only=True)
    features = ProjectFeatureNodeSerializer(many=True, read_only=True)


class ProjectFeatureTreeSerializer(serializers.Serializer):
    """feature 树（模块→功能点→验收项，响应，WB-02）。"""

    modules = ProjectFeatureModuleSerializer(many=True, read_only=True)


# ---- 项目基础搜索（WB-05，84-01）----


class ProjectSearchLocatorSerializer(serializers.Serializer):
    """搜索结果定位（属哪个仓库/项目，响应）。"""

    project_id = serializers.CharField(read_only=True)
    project_name = serializers.CharField(read_only=True, allow_blank=True)
    repository_id = serializers.CharField(
        read_only=True, allow_blank=True, allow_null=True, required=False
    )


class ProjectSearchResultSerializer(serializers.Serializer):
    """单条项目搜索结果（响应，WB-05）。

    **wire 契约单一来源**：``kind`` / ``title`` / ``snippet`` / ``score`` /
    ``source`` / ``locator`` 字段名即前端契约。
    """

    kind = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True, allow_blank=True)
    snippet = serializers.CharField(read_only=True, allow_blank=True)
    score = serializers.FloatField(read_only=True)
    source = serializers.CharField(read_only=True)
    locator = ProjectSearchLocatorSerializer(read_only=True)


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


class ProjectWorkItemAttachSerializer(serializers.Serializer):
    """手动并入工作项请求（COMPOSE-01）。``work_item_id`` 为 delivery.WorkItem 的 UUID 主键。"""

    work_item_id = serializers.UUIDField()


class ProjectWorkItemSerializer(serializers.Serializer):
    """项目关联工作项摘要（响应，COMPOSE-01/02）。

    84-01 起含 WorkItem 状态镜像字段（``status_state_key`` / ``status_display_name`` /
    ``module_normalized``），供前端 feature 进度灯 / 里程碑映射。
    """

    id = serializers.UUIDField(read_only=True)
    feishu_work_item_id = serializers.IntegerField(read_only=True)
    work_item_type = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    feishu_project_key = serializers.CharField(read_only=True)
    provenance = serializers.CharField(read_only=True)
    attached_at = serializers.DateTimeField(read_only=True)
    status_state_key = serializers.CharField(read_only=True, allow_blank=True)
    status_display_name = serializers.CharField(read_only=True, allow_blank=True)
    module_normalized = serializers.CharField(read_only=True, allow_blank=True)


# ---- 工件类型（ARTIFACT-01/05）----


class ArtifactTypeSerializer(serializers.ModelSerializer):
    """工件类型序列化（响应）。"""

    instance_count = serializers.SerializerMethodField()

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
            "instance_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_instance_count(self, obj) -> int:
        # 有实例的类型受删除保护（ARTIFACT-05）；前端据此禁用删除按钮。
        return getattr(obj, "instance_count", None) or obj.artifacts.count()


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
    entity_id = serializers.SerializerMethodField()

    def get_entity_id(self, obj) -> str:
        # 函数内 import 避免 initiatives→knowledge 顶层耦合；确定性 uuid5 派生 document 实体 id。
        from knowledge.models import EntityKind, generate_entity_id

        return str(generate_entity_id(EntityKind.DOCUMENT, "artifact", str(obj.id)))

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
            "entity_id",
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


# ---- 分支↔项目绑定（BIND-01）----


class ProjectBranchSerializer(serializers.ModelSerializer):
    """项目分支绑定序列化（响应）。"""

    repository_name = serializers.CharField(source="repository.name", read_only=True)

    class Meta:
        model = ProjectBranch
        fields = [
            "id",
            "repository_id",
            "repository_name",
            "branch_name",
            "source",
            "feishu_board_id",
            "created_at",
        ]
        read_only_fields = fields


class ProjectBranchBindRequestSerializer(serializers.Serializer):
    """绑定分支请求（BIND-01）：必填 repository_id/branch_name，可选 source/feishu_board_id。"""

    repository_id = serializers.UUIDField()
    branch_name = serializers.CharField(max_length=255)
    source = serializers.ChoiceField(
        required=False, choices=BranchSource.choices, default=BranchSource.MANUAL
    )
    feishu_board_id = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=100
    )


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


class IdeHookAssetsQuerySerializer(serializers.Serializer):
    """IDE hook 资产下发查询参数校验（HOOK-01）。

    ``runtime`` 必填（``cursor`` / ``claude_code`` / ``codex``）；``kind`` 默认 ``read``
    （读路径 always-on 规则 + 注入），``write`` 下发写路径 stop hook 资产（86-05）。
    """

    runtime = serializers.ChoiceField(
        choices=["cursor", "claude_code", "codex"], required=True
    )
    kind = serializers.ChoiceField(
        choices=["read", "write"], required=False, default="read"
    )

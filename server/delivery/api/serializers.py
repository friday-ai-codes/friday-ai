"""delivery REST 序列化器（Phase 28-03）。

- read：``WorkItemSerializer``（三元组 + mirror + friday_enhanced + 元数据 + 嵌套
  ``sync_states`` per-facet 完整度只读概要）。
- write：``WorkItemUpsertRequestSerializer``（三元组必填，``work_item_id`` 正整数校验）。
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from delivery.models import (
    Document,
    IngestRun,
    SddSpec,
    SddSpecReview,
    WorkItem,
    WorkItemSyncState,
)


class WorkItemSyncStateSerializer(serializers.ModelSerializer):
    """单 facet 来源完整度只读概要。"""

    class Meta:
        model = WorkItemSyncState
        fields = ["facet", "status", "source", "last_synced_at", "error"]
        read_only_fields = fields


class WorkItemSerializer(serializers.ModelSerializer):
    """WorkItem 只读序列化（含 sync_states 完整度概要）。

    纯只读：所有字段 read-only，落库只经 ``WorkItemService.upsert``（INV-6）。
    """

    sync_states = WorkItemSyncStateSerializer(many=True, read_only=True)
    project = serializers.PrimaryKeyRelatedField(read_only=True, source="space")

    class Meta:
        model = WorkItem
        fields = [
            "id",
            "feishu_project_key",
            "work_item_type",
            "work_item_id",
            "feishu_project_simple_name",
            "project",
            "origin",
            # mirror
            "title",
            "status_state_key",
            "status_sub_stage",
            "status_display_name",
            "is_archived_state",
            "is_init_state",
            "feishu_fields",
            "prd_url",
            "tech_doc_url",
            # friday_enhanced
            "business_line_normalized",
            "module_normalized",
            "internal_note",
            # 元数据
            "field_provenance",
            "last_synced_at",
            "created_at",
            "updated_at",
            "event_time",
            # per-facet 完整度概要
            "sync_states",
        ]
        read_only_fields = fields


class WorkItemUpsertRequestSerializer(serializers.Serializer):
    """手动 upsert 入参校验：三元组必填，work_item_id 为正整数。"""

    feishu_project_key = serializers.CharField(max_length=64)
    work_item_type = serializers.CharField(max_length=32)
    work_item_id = serializers.IntegerField(min_value=1)


class CommentTreeNodeSerializer(serializers.Serializer):
    """评论树节点只读序列化（递归子节点）。

    输入为 ``project_comment_tree`` 产出的 dict 节点（非 ORM 实例），透传投影形状
    （feishu_comment_id / author / body / event_type / approval_semantic /
    is_deleted / event_time / thread_parent_id / children）；``event_time`` 经
    ``DateTimeField`` 统一 ISO 序列化，``children`` 递归自引用。纯只读，无写入。
    """

    feishu_comment_id = serializers.CharField()
    author = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    event_type = serializers.CharField()
    approval_semantic = serializers.CharField()
    is_deleted = serializers.BooleanField()
    event_time = serializers.DateTimeField(allow_null=True)
    thread_parent_id = serializers.CharField(allow_blank=True)
    children = serializers.SerializerMethodField()

    def get_children(self, obj: dict) -> list[dict]:
        return CommentTreeNodeSerializer(obj.get("children", []), many=True).data


class DocumentSnapshotSerializer(serializers.ModelSerializer):
    """Document 只读快照序列化（元数据 + 当前版本正文，30-04）。

    暴露 Document 操作态元数据 + 当前版本正文快照（``current_version.content``）。
    纯只读：所有字段 read-only，落库只经 ``DocumentService``（INV-6）。``content``/
    ``version`` 取自 ``current_version``——缺当前版本（降级占位）→ content="" / version=null，
    不臆造。``current_version`` 须经 ``select_related`` 预取，避免 async 隐式同步访问。
    """

    content = serializers.SerializerMethodField()
    version = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "document_type",
            "source_kind",
            "content_storage",
            "external_ref",
            "canonical_url",
            "feishu_tenant",
            "last_synced_at",
            "content",
            "version",
        ]
        read_only_fields = fields

    def get_content(self, obj: Document) -> str:
        current = obj.current_version
        return current.content if current is not None else ""

    def get_version(self, obj: Document) -> int | None:
        current = obj.current_version
        return current.version if current is not None else None


class SddSpecReviewSerializer(serializers.ModelSerializer):
    """SddSpecReview 只读序列化（Phase 50-03，D-50-4）。

    reviewer 展示为用户标识（username）；用户被删（SET_NULL）→ reviewer 为 None → 回 null。
    纯只读：评审记录 append-only，落库只经 ``SddSpecService.approve/reject``（INV-6）。
    """

    reviewer = serializers.SerializerMethodField()

    class Meta:
        model = SddSpecReview
        fields = ["id", "reviewer", "decision", "comment", "created_at"]
        read_only_fields = fields

    def get_reviewer(self, obj: SddSpecReview) -> str | None:
        return obj.reviewer.get_username() if obj.reviewer_id else None


class SddSpecListSerializer(serializers.ModelSerializer):
    """SddSpec 列表轻量只读序列化（Phase 50-03，D-50-4）。

    列表项不含正文/评审历史（detail 才展开）。状态一律 read_only：状态仅经
    ``transition`` action 改，禁直接 PATCH（对齐 Phase 24 范式）。
    """

    repository_id = serializers.UUIDField(read_only=True)
    repository_name = serializers.CharField(source="repository.name", read_only=True)
    work_item = serializers.SerializerMethodField()

    class Meta:
        model = SddSpec
        fields = [
            "id",
            "status",
            "change_kind",
            "repository_id",
            "repository_name",
            "work_item",
            "updated_at",
        ]
        read_only_fields = fields

    def get_work_item(self, obj: SddSpec) -> dict[str, Any] | None:
        if obj.work_item_id is None:
            return None
        return {"id": str(obj.work_item_id), "title": obj.work_item.title}


class SddSpecDetailSerializer(SddSpecListSerializer):
    """SddSpec 详情只读序列化（正文 + 评审历史 + 关联摘要，D-50-4）。

    在列表字段上加：``body``（spec 正文，取 ``document.current_version.content``，
    缺失回 None）、``reviews``（嵌套评审历史，倒序由模型 Meta.ordering 保证）、
    ``relations``（repository/work_item/plan_version 关联摘要；缺失项不输出）、
    ``implementation_prs``（实现 PR 列表，Phase 52 D-52-4，LINK-01；直接映射模型 JSON 列，
    缺省 default=list → 空列表，天然 fail-soft）。
    关联预取（select_related/prefetch）由 view 层负责，序列化器不触发额外懒查询。
    """

    body = serializers.SerializerMethodField()
    reviews = SddSpecReviewSerializer(many=True, read_only=True)
    relations = serializers.SerializerMethodField()
    implementation_prs = serializers.JSONField(read_only=True)

    class Meta(SddSpecListSerializer.Meta):
        fields = [
            *SddSpecListSerializer.Meta.fields,
            "body",
            "reviews",
            "relations",
            "implementation_prs",
        ]
        read_only_fields = fields

    def get_body(self, obj: SddSpec) -> str | None:
        doc = obj.document
        if doc is None:
            return None
        current = doc.current_version
        return current.content if current is not None else None

    def get_relations(self, obj: SddSpec) -> dict[str, Any]:
        relations: dict[str, Any] = {}
        repo = obj.repository
        if repo is not None:
            relations["repository"] = {
                "id": str(repo.id),
                "name": repo.name,
                "methodology": (repo.facets or {}).get("methodology"),
            }
        if obj.work_item_id is not None:
            relations["work_item"] = {
                "id": str(obj.work_item_id),
                "title": obj.work_item.title,
                # url 取 prd_url（无则空串，对齐 pr_cross_reference 不构造臆造 URL 范式）。
                "url": obj.work_item.prd_url or "",
            }
        if obj.artifact_version_id is not None:
            relations["artifact_version"] = {
                "id": str(obj.artifact_version_id),
                "version": obj.artifact_version.version_no,
            }
        return relations


class IngestDispatchRequestSerializer(serializers.Serializer):
    """一键摄取触发入参校验（32-02）：board_url + mr_url 必填且须为 http(s)。

    不可信用户输入：仅在此校验非空 + http(s) 前缀（解析/SSRF 边界在编排层）；
    校验错误用中文，对齐前端契约。
    """

    board_url = serializers.CharField(max_length=2000, trim_whitespace=True)
    mr_url = serializers.CharField(max_length=2000, trim_whitespace=True)

    def _validate_http_url(self, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise serializers.ValidationError("URL 必须以 http(s):// 开头")
        return value

    def validate_board_url(self, value: str) -> str:
        return self._validate_http_url(value)

    def validate_mr_url(self, value: str) -> str:
        return self._validate_http_url(value)


class IngestRunSerializer(serializers.ModelSerializer):
    """一键摄取运行记录只读序列化（32-02，字段名对齐 UI-SPEC ``IngestRun`` 契约）。

    暴露 ``run_id``(=id) / ``status`` / ``steps``(三步结构化结果) /
    ``started_at`` / ``completed_at``，供前端派发后轮询真实进度。纯只读。
    """

    run_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = IngestRun
        fields = ["run_id", "status", "steps", "started_at", "completed_at"]
        read_only_fields = fields


class IngestBatchItemSerializer(serializers.Serializer):
    """批量摄取单组 ``(board_url, mr_url)`` 入参（复用单组 http(s) 校验）。"""

    board_url = serializers.CharField(max_length=2000, trim_whitespace=True)
    mr_url = serializers.CharField(max_length=2000, trim_whitespace=True)

    def _validate_http_url(self, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise serializers.ValidationError("URL 必须以 http(s):// 开头")
        return value

    def validate_board_url(self, value: str) -> str:
        return self._validate_http_url(value)

    def validate_mr_url(self, value: str) -> str:
        return self._validate_http_url(value)


class IngestBatchDispatchRequestSerializer(serializers.Serializer):
    """批量摄取触发入参：``items`` 为 1..50 组 ``(board_url, mr_url)``。

    每组校验同单组端点（非空 + http(s)）；空列表 / 超 50 组 → 400。各组失败
    互不影响（每组独立 ``IngestRun``，共享 ``batch_id``，后台并行派发）。
    """

    items = IngestBatchItemSerializer(many=True, allow_empty=False, max_length=50)


class IngestBatchRunSerializer(serializers.ModelSerializer):
    """批量摄取中单条 run 的只读序列化（含原始 ``board_url`` / ``mr_url`` 供前端对应展示）。"""

    run_id = serializers.UUIDField(source="id", read_only=True)

    class Meta:
        model = IngestRun
        fields = [
            "run_id",
            "board_url",
            "mr_url",
            "status",
            "steps",
            "started_at",
            "completed_at",
        ]
        read_only_fields = fields


# ============================================================================
# JSON 批量摄取（空间 + 工作项 id + 可选类型/ MR）
# ============================================================================


class JsonIngestRequestSerializer(serializers.Serializer):
    """JSON 批量摄取入参：1..200 条宽松 item + 可选并发数。

    item 保持宽松（``DictField``）以便 resolve 预览能逐项回报错误（空间/ID 非法不应
    整请求 400）；权威校验在 ``aresolve_items`` 内逐项进行。
    """

    items = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
        max_length=200,
    )
    concurrency = serializers.IntegerField(required=False, default=3, min_value=1, max_value=10)


class CrawlRequestSerializer(serializers.Serializer):
    """URL 爬取入参：一个待爬取链接（飞书文档 / 多维表格 / wiki / 通用 URL）。"""

    url = serializers.CharField(max_length=2048, trim_whitespace=True)


class IngestQueueItemSerializer(serializers.Serializer):
    """爬取入库队列单批聚合项只读序列化（Phase 62-01，CRAWL-01）。

    承载从 ``IngestRun``（DB 真相源）按 ``batch_id`` 分组重建的聚合形状，**不依赖任何
    内存态**——刷新页面 / 容器重建后队列可经 list 端点完整恢复。``status`` 为该批聚合态
    （优先级 running>queued>stopped>failed>completed）；``total`` 行数、``done`` 已完成行数、
    ``url_count`` 该批 URL 集合数（=行数）；时间戳取该批 min(started_at)/max(updated_at)。
    """

    batch_id = serializers.UUIDField()
    status = serializers.CharField()
    total = serializers.IntegerField()
    done = serializers.IntegerField()
    url_count = serializers.IntegerField()
    durable_job_id = serializers.CharField(allow_blank=True)
    idempotency_key = serializers.CharField(allow_blank=True)
    started_at = serializers.DateTimeField(allow_null=True)
    updated_at = serializers.DateTimeField(allow_null=True)
    error = serializers.CharField(allow_blank=True)


class WorkItemArtifactsQuerySerializer(serializers.Serializer):
    """工作项关联文档查询入参（三元组）。"""

    feishu_project_key = serializers.CharField(max_length=64)
    work_item_type = serializers.CharField(max_length=32)
    work_item_id = serializers.IntegerField(min_value=1)


# ============================================================================
# 截图识别需求（Phase 35-01，VIS-01）—— 仅用于 drf-spectacular 文档，运行时直接透传
# screenshot_recall 服务返回的 dict（形状对齐 35-UI-SPEC ScreenshotRecallResult）。
# ============================================================================


class ExtractedSemanticsSerializer(serializers.Serializer):
    """多模态 LLM 提取的语义三段（文档化用）。"""

    text = serializers.CharField(required=False, allow_blank=True)
    ui_elements = serializers.CharField(required=False, allow_blank=True)
    business_intent = serializers.CharField(required=False, allow_blank=True)


class RecalledRequirementSerializer(serializers.Serializer):
    """召回的单条需求（work_item，文档化用）。"""

    work_item_id = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    link = serializers.CharField(required=False)
    relevance = serializers.FloatField(required=False)
    source = serializers.CharField(required=False)


class ScreenshotRecallResultSerializer(serializers.Serializer):
    """截图识别结果（degraded 三态，文档化用）。"""

    degraded = serializers.BooleanField()
    degraded_code = serializers.CharField(required=False)
    degraded_reason = serializers.CharField(required=False)
    semantics = ExtractedSemanticsSerializer(required=False, allow_null=True)
    query = serializers.CharField(required=False, allow_null=True)
    results = RecalledRequirementSerializer(many=True)

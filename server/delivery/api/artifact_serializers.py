"""Artifact 版本轨 / 时间线只读序列化器（Chassis v2 · P7）。

read-only 呈现 ``Artifact`` / ``ArtifactVersion`` 时间线 + 下游引用聚合，回答三问：

- **当前最新版本是什么**：``current_version`` + ``current_version_markdown``（render_markdown 摘要）。
- **为何变成它**：每版本的 ``produced_by_ref`` / ``produced_by_session_id`` + ``supersedes_id`` 链。
- **哪些下游产物引用它**：``RepoCodingTask`` / ``SddSpec``（真实 FK） + ``ArchitectMerge``
  （``merged_artifact_version`` 软 UUID 引用）按版本聚合。

纯只读：所有字段 read-only，落库只经 ``ArtifactService``（INV-6）；关联预取由 view 负责，
序列化器不触发额外懒查询（避免 async 上下文隐式同步访问）。
"""

from __future__ import annotations

import structlog
from rest_framework import serializers

from delivery.artifacts.registry import render_markdown
from delivery.models import (
    ArchitectMerge,
    Artifact,
    ArtifactVersion,
    RepoCodingTask,
    SddSpec,
)

logger = structlog.get_logger(__name__)


class ArtifactVersionTimelineSerializer(serializers.ModelSerializer):
    """单个 ArtifactVersion 的时间线条目（版本号 / 时间 / hash / supersedes 链 / 来源 / 审批）。

    ``is_current`` 由 context["current_version_id"] 判定（与 artifact.current_version 比对）。
    """

    supersedes_id = serializers.UUIDField(read_only=True, allow_null=True)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = ArtifactVersion
        fields = [
            "id",
            "version_no",
            "created_at",
            "content_hash",
            "supersedes_id",
            "produced_by_ref",
            "produced_by_session_id",
            "approval_status",
            "is_current",
        ]
        read_only_fields = fields

    def get_is_current(self, obj: ArtifactVersion) -> bool:
        return obj.id == self.context.get("current_version_id")


class ArtifactListSerializer(serializers.ModelSerializer):
    """Artifact 轻量只读序列化（元数据 + 当前版本摘要，列表用）。

    ``current_version`` 须经 ``select_related`` 预取，缺当前版本（降级占位）回 None。
    """

    work_item_id = serializers.UUIDField(read_only=True, allow_null=True)
    current_version = serializers.SerializerMethodField()

    class Meta:
        model = Artifact
        fields = [
            "id",
            "artifact_type",
            "title",
            "status",
            "work_item_id",
            "current_version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _version_context(self, obj: Artifact) -> dict:
        return {"current_version_id": obj.current_version_id}

    def get_current_version(self, obj: Artifact) -> dict | None:
        current = obj.current_version
        if current is None:
            return None
        return ArtifactVersionTimelineSerializer(
            current, context=self._version_context(obj)
        ).data


class ArtifactTimelineSerializer(ArtifactListSerializer):
    """Artifact 时间线详情（在列表字段上加全版本时间线 + 当前版本 markdown 摘要）。

    ``versions`` 须经 ``prefetch_related("versions")`` 预取并由 view 倒序传入；
    ``current_version_markdown`` 经类型注册的 ``render_markdown`` 渲染（无渲染器 / 异常回 None，
    best-effort 不反噬主流程）。
    """

    versions = serializers.SerializerMethodField()
    current_version_markdown = serializers.SerializerMethodField()

    class Meta(ArtifactListSerializer.Meta):
        fields = [
            *ArtifactListSerializer.Meta.fields,
            "versions",
            "current_version_markdown",
        ]
        read_only_fields = fields

    def get_versions(self, obj: Artifact) -> list[dict]:
        ctx = self._version_context(obj)
        # 倒序（最新在前）；versions 已由 view prefetch，这里仅本地排序不触发查询。
        ordered = sorted(
            obj.versions.all(), key=lambda v: v.version_no, reverse=True
        )
        return ArtifactVersionTimelineSerializer(ordered, many=True, context=ctx).data

    def get_current_version_markdown(self, obj: Artifact) -> str | None:
        current = obj.current_version
        if current is None:
            return None
        try:
            return render_markdown(obj.artifact_type, current.content)
        except Exception:
            # 渲染 best-effort：失败不反噬时间线呈现。
            logger.warning(
                "artifact_render_markdown_failed",
                category="sampling",
                component="artifact_timeline_api",
                artifact_id=str(obj.id),
                artifact_type=obj.artifact_type,
            )
            return None


# ============================================================================
# 下游引用聚合（哪些下游产物引用某 ArtifactVersion）
# ============================================================================


class RepoCodingTaskRefSerializer(serializers.ModelSerializer):
    """引用某版本的编码子任务摘要（真实 FK artifact_version）。"""

    repository_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = RepoCodingTask
        fields = ["id", "repository_id", "status", "wave", "attempt"]
        read_only_fields = fields


class SddSpecRefSerializer(serializers.ModelSerializer):
    """引用某版本的 SDD spec 摘要（真实 FK artifact_version）。"""

    repository_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = SddSpec
        fields = ["id", "repository_id", "status", "change_kind"]
        read_only_fields = fields


class ArchitectMergeRefSerializer(serializers.ModelSerializer):
    """引用某版本的架构师融合摘要（软 UUID merged_artifact_version）。"""

    session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ArchitectMerge
        fields = ["id", "session_id", "validation_status", "attempt"]
        read_only_fields = fields

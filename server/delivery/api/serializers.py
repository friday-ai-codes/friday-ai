"""delivery REST 序列化器（Phase 28-03）。

- read：``WorkItemSerializer``（三元组 + mirror + friday_enhanced + 元数据 + 嵌套
  ``sync_states`` per-facet 完整度只读概要）。
- write：``WorkItemUpsertRequestSerializer``（三元组必填，``work_item_id`` 正整数校验）。
"""

from __future__ import annotations

from rest_framework import serializers

from delivery.models import WorkItem, WorkItemSyncState


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

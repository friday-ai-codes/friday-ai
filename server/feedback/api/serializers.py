"""Feedback / FeedbackReply 序列化器。"""

from __future__ import annotations

from rest_framework import serializers

from feedback.attachments import MAX_ATTACHMENTS
from feedback.models import Feedback, FeedbackReply


class FeedbackAttachmentSerializer(serializers.Serializer):
    """反馈附件项（已上传后回填的引用）。"""

    storage_ref = serializers.CharField(max_length=512)
    kind = serializers.ChoiceField(choices=["image", "video"])
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    size = serializers.IntegerField(required=False, default=0)
    mime = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    url = serializers.CharField(max_length=1024, required=False, allow_blank=True, default="")


class FeedbackReplySerializer(serializers.ModelSerializer):
    """反馈回复只读序列化器。"""

    author_name = serializers.SerializerMethodField()

    class Meta:
        model = FeedbackReply
        fields = ["id", "content", "is_admin", "author_repr", "author_name", "created_at"]
        read_only_fields = fields

    def get_author_name(self, obj: FeedbackReply) -> str:
        if obj.author_repr:
            return obj.author_repr
        if obj.author_id and obj.author:
            return getattr(obj.author, "username", "") or getattr(obj.author, "email", "")
        return ""


class FeedbackSerializer(serializers.ModelSerializer):
    """反馈序列化器（列表/详情，含回复线程）。"""

    replies = FeedbackReplySerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Feedback
        fields = [
            "id",
            "category",
            "category_label",
            "title",
            "content",
            "attachments",
            "page_url",
            "conversation_id",
            "message_id",
            "status",
            "status_label",
            "created_by_name",
            "replies",
            "created_at",
            "updated_at",
            "resolved_at",
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj: Feedback) -> str:
        if obj.created_by_id and obj.created_by:
            return getattr(obj.created_by, "username", "") or getattr(obj.created_by, "email", "")
        return ""


class FeedbackCreateSerializer(serializers.Serializer):
    """反馈创建入参校验。"""

    category = serializers.ChoiceField(choices=Feedback.Category.choices)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    content = serializers.CharField(max_length=20000)
    attachments = FeedbackAttachmentSerializer(many=True, required=False, default=list)
    page_url = serializers.CharField(max_length=1024, required=False, allow_blank=True, default="")
    conversation_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    message_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def validate_attachments(self, value):
        if len(value) > MAX_ATTACHMENTS:
            raise serializers.ValidationError(f"附件数量不能超过 {MAX_ATTACHMENTS} 个。")
        return value

"""Notification / Announcement 序列化器。"""

from __future__ import annotations

from rest_framework import serializers

from notifications.models import Announcement, Notification


class NotificationSerializer(serializers.ModelSerializer):
    """站内信通知只读序列化器。"""

    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "title",
            "body",
            "link",
            "metadata",
            "read_at",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields


class AdminAnnouncementSerializer(serializers.ModelSerializer):
    """系统公告管理端序列化器（读：完整字段；写：CRUD 输入校验）。"""

    created_by_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Announcement
        fields = [
            "id",
            "title",
            "body",
            "link",
            "status",
            "notify_mode",
            "audience",
            "target_user_ids",
            "starts_at",
            "ends_at",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_by_name", "created_at", "updated_at"]

    def get_created_by_name(self, obj: Announcement) -> str:
        user = obj.created_by
        if user is None:
            return ""
        return getattr(user, "username", "") or getattr(user, "email", "") or str(user.id)

    def validate(self, attrs):
        audience = attrs.get("audience", getattr(self.instance, "audience", None))
        target = attrs.get("target_user_ids", getattr(self.instance, "target_user_ids", None))
        if audience == Announcement.Audience.SPECIFIC and not target:
            raise serializers.ValidationError(
                {"target_user_ids": "指定用户受众时必须选择至少一个用户"}
            )
        starts_at = attrs.get("starts_at", getattr(self.instance, "starts_at", None))
        ends_at = attrs.get("ends_at", getattr(self.instance, "ends_at", None))
        if starts_at and ends_at and starts_at >= ends_at:
            raise serializers.ValidationError({"ends_at": "结束时间必须晚于开始时间"})
        return attrs

    def validate_target_user_ids(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("必须是用户 id 列表")
        return [str(v) for v in value]

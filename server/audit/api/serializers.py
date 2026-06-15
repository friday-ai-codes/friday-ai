"""AuditEvent REST serializer —— 只读序列化。"""

from rest_framework import serializers

from audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    """审计事件序列化器 —— 所有字段只读。"""

    actor_username = serializers.CharField(source="actor_display", read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "timestamp",
            "actor",
            "actor_username",
            "actor_type",
            "action",
            "target_type",
            "target_id",
            "before",
            "after",
            "source",
            "ip_address",
        ]
        read_only_fields = fields

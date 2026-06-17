"""AuditEvent 查询序列化器（AUDITUI-01）。

只读序列化器：直出全字段。``before`` / ``after`` / ``metadata`` 已在写入端
（``AuditService`` 入口）强制脱敏，查询面无需二次处理；不暴露任何写入口（append-only）。
"""

from __future__ import annotations

from rest_framework import serializers

from audit.models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    """审计事件只读序列化器（全字段直出）。"""

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "actor_id",
            "actor_repr",
            "action",
            "target_type",
            "target_id",
            "target_repr",
            "before",
            "after",
            "source",
            "occurred_at",
            "recorded_at",
            "metadata",
        ]
        read_only_fields = fields

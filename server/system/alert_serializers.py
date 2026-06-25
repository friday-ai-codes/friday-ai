"""系统告警序列化器（ALERT-01/02）。

镜像 ``serializers.py`` 的"读 ModelSerializer + 写白名单防御"范式：
- ``SystemAlertRuleSerializer``：规则读序列化器（含全字段 + 时间戳）。
- ``SystemAlertRuleWriteSerializer``：规则写序列化器（create + partial_update 共用），
  metric/op/severity ChoiceField 白名单 + channels/dimension 受控校验，
  禁任意字符串 / 用户原文污染评估与 label 基数（T-74-01-02）。
- ``AlertEventSerializer``：告警事件只读序列化器（查询端点不写）。
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .models import AlertEvent, SystemAlertRule

# 受控 metric 枚举——与 74-02 评估器 metric 解析表对齐（单一受控集合）。
_METRIC_CHOICES = [
    "qps",
    "error_rate",
    "ttft",
    "cpu",
    "memory",
    "db_connections",
    "redis_clients",
    "qdrant",
    "queue_depth",
]
_OP_CHOICES = ["gt", "gte", "lt", "lte"]
_SEVERITY_CHOICES = ["P0", "P1", "P2"]
# 通知通道受控子集。
_CHANNEL_CHOICES = frozenset({"email", "feishu", "webhook"})
# 维度受控键集合（禁用户原文，防 label 基数失控；对齐 STATE 关键约束）。
_DIMENSION_KEYS = frozenset({"provider", "credential", "model", "source", "queue", "route"})


class SystemAlertRuleSerializer(serializers.ModelSerializer):
    """系统告警规则读序列化器（list / retrieve）。"""

    class Meta:
        model = SystemAlertRule
        fields = [
            "id",
            "name",
            "metric",
            "op",
            "value",
            "window",
            "dimension",
            "severity",
            "enabled",
            "channels",
            "cooldown",
            "title_template",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SystemAlertRuleWriteSerializer(serializers.ModelSerializer):
    """系统告警规则写序列化器（create + partial_update 共用，白名单防御）。

    metric/op/severity 为闭集 ChoiceField；channels ⊆ {email,feishu,webhook}；
    dimension 限 dict 且键 ⊆ 受控集合、值为 str。非法入参抛中文 ValidationError → 400。
    """

    metric = serializers.ChoiceField(choices=_METRIC_CHOICES)
    op = serializers.ChoiceField(choices=_OP_CHOICES)
    severity = serializers.ChoiceField(choices=_SEVERITY_CHOICES)
    value = serializers.FloatField()
    window = serializers.IntegerField(min_value=1, default=300)
    cooldown = serializers.IntegerField(min_value=0, default=600)

    class Meta:
        model = SystemAlertRule
        fields = [
            "name",
            "metric",
            "op",
            "value",
            "window",
            "dimension",
            "severity",
            "enabled",
            "channels",
            "cooldown",
            "title_template",
        ]

    def validate_channels(self, value: Any) -> list[str]:
        """通道列表受控子集校验：必须为 list 且元素 ⊆ {email,feishu,webhook}。"""
        if not isinstance(value, list):
            raise serializers.ValidationError("channels 必须是数组")
        invalid = [c for c in value if c not in _CHANNEL_CHOICES]
        if invalid:
            raise serializers.ValidationError(
                f"非法通道：{invalid}；仅支持 email/feishu/webhook"
            )
        return value

    def validate_dimension(self, value: Any) -> dict[str, str]:
        """维度受控校验：dict 且键 ⊆ 受控集合、值为 str（禁任意嵌套 / 用户原文）。"""
        if not isinstance(value, dict):
            raise serializers.ValidationError("dimension 必须是对象")
        for key, val in value.items():
            if key not in _DIMENSION_KEYS:
                raise serializers.ValidationError(
                    f"非法维度键：{key}；仅支持 {sorted(_DIMENSION_KEYS)}"
                )
            if not isinstance(val, str):
                raise serializers.ValidationError(f"维度 {key} 的值必须是字符串")
        return value


class AlertEventSerializer(serializers.ModelSerializer):
    """告警事件只读序列化器（ALERT-02 查询）。

    暴露全部事件字段（含 rule_info / target / duration_s / email_sent /
    notified_channels），列对齐 REFERENCE-UI §1.4。全字段 read_only（查询端点不写）；
    内容由 74-02/03 写入时已脱敏，绝不含明文凭证（T-74-01-04）。
    """

    class Meta:
        model = AlertEvent
        fields = [
            "id",
            "rule",
            "severity",
            "title_zh",
            "rule_info",
            "target",
            "target_key",
            "status",
            "started_at",
            "ended_at",
            "duration_s",
            "current_value",
            "last_seen_at",
            "email_sent",
            "notified_channels",
            "created_at",
        ]
        read_only_fields = fields

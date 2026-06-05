"""执行分析 API 序列化器。"""

from rest_framework import serializers


class AnalyticsOverviewSerializer(serializers.Serializer):
    """KPI 概览数据序列化器。"""

    total_executions = serializers.IntegerField()
    success_rate = serializers.FloatField()
    avg_duration_seconds = serializers.FloatField(allow_null=True)
    total_cost_usd = serializers.FloatField()


class TrendDataPointSerializer(serializers.Serializer):
    """趋势数据点序列化器。"""

    date = serializers.CharField()
    completed = serializers.IntegerField()
    failed = serializers.IntegerField()
    total = serializers.IntegerField()


class DurationBucketSerializer(serializers.Serializer):
    """时长分布桶序列化器。"""

    bucket_label = serializers.CharField()
    count = serializers.IntegerField()


class TokenCostDataPointSerializer(serializers.Serializer):
    """Token 成本数据点序列化器。"""

    date = serializers.CharField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    total_cost_usd = serializers.FloatField()


class NodePerformanceSerializer(serializers.Serializer):
    """节点性能排行序列化器。"""

    node_type = serializers.CharField()
    execution_count = serializers.IntegerField()
    avg_duration_seconds = serializers.FloatField(allow_null=True)
    success_rate = serializers.FloatField()
    total_tokens = serializers.IntegerField()


# ============================================================================
# implementation — contract group_by 扩展（contract）
# ============================================================================


class GroupedOverviewSerializer(serializers.Serializer):
    """按维度分组的 Overview 响应。

    Shape（Pitfall 6 Option B 包装）：
        {
            "group_by": "provider_type",
            "groups": {"anthropic": {total_tokens, total_cost_usd, count}, ...},
            "total": {total_executions, success_rate, avg_duration_seconds, total_cost_usd}
        }

    group_by=none 时：`groups` 省略，`total` 承载全部 flat KPI。
    """

    group_by = serializers.ChoiceField(choices=["none", "provider_type", "project"])
    groups = serializers.DictField(required=False, allow_null=True)
    total = serializers.DictField(required=False, allow_null=True)


class GroupedTokenCostSerializer(serializers.Serializer):
    """按维度分组的 TokenCost 响应。

    Shape：
        {
            "group_by": "provider_type",
            "groups": {
                "anthropic": [{date, input_tokens, output_tokens, total_cost_usd}, ...],
                "gemini":    [...]
            }
        }

    group_by=none 时兼容旧 Phase flat list shape（不走本 Serializer）。
    """

    group_by = serializers.ChoiceField(choices=["none", "provider_type", "project"])
    groups = serializers.DictField(
        required=False,
        child=serializers.ListField(child=TokenCostDataPointSerializer()),
    )

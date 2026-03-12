"""执行分析 API 序列化器。"""
from rest_framework import serializers
class AnalyticsOverviewSerializer(serializers.Serializer):
 """KPI 概览数据序列化器。"""
 total_executions = serializers.IntegerField
 success_rate = serializers.FloatField
 avg_duration_seconds = serializers.FloatField(allow_null=True)
 total_cost_usd = serializers.FloatField
class TrendDataPointSerializer(serializers.Serializer):
 """趋势数据点序列化器。"""
 date = serializers.CharField
 completed = serializers.IntegerField
 failed = serializers.IntegerField
 total = serializers.IntegerField
class DurationBucketSerializer(serializers.Serializer):
 """时长分布桶序列化器。"""
 bucket_label = serializers.CharField
 count = serializers.IntegerField
class TokenCostDataPointSerializer(serializers.Serializer):
 """Token 成本数据点序列化器。"""
 date = serializers.CharField
 input_tokens = serializers.IntegerField
 output_tokens = serializers.IntegerField
 total_cost_usd = serializers.FloatField
class NodePerformanceSerializer(serializers.Serializer):
 """节点性能排行序列化器。"""
 node_type = serializers.CharField
 execution_count = serializers.IntegerField
 avg_duration_seconds = serializers.FloatField(allow_null=True)
 success_rate = serializers.FloatField
 total_tokens = serializers.IntegerField

"""容器回调 API 序列化器（Phase）。"""
from rest_framework import serializers
from services.protocols import CallbackType
from subagent.models import ActionLog
class CallbackSerializer(serializers.Serializer):
 """统一回调端点请求序列化器。
 验证容器发送的回调请求结构。
 """
 type = serializers.ChoiceField(
 choices=[
 CallbackType.COMPLETED,
 CallbackType.FAILED,
 CallbackType.QUESTION,
 CallbackType.HEARTBEAT,
 CallbackType.PROGRESS,
 CallbackType.ACTION_LOG,
 CallbackType.TOKEN_USAGE,
 ],
 )
 session_id = serializers.CharField(max_length=64)
 token = serializers.CharField(max_length=256)
 timestamp = serializers.DateTimeField(required=False)
 payload = serializers.DictField(default=dict)
class CompletedPayloadSerializer(serializers.Serializer):
 """type=completed 时的 payload 验证。"""
 result_type = serializers.ChoiceField(choices=["text", "git"])
 output = serializers.DictField(default=dict)
 duration_ms = serializers.IntegerField(required=False, default=0)
 # Git 产物字段（result_type=git 时必填）
 branch_name = serializers.CharField(required=False, default="", allow_blank=True)
 commit_sha = serializers.CharField(required=False, default="", allow_blank=True)
 modified_files = serializers.ListField(
 child=serializers.CharField, required=False, default=list
 )
class FailedPayloadSerializer(serializers.Serializer):
 """type=failed 时的 payload 验证。"""
 error = serializers.CharField(default="", allow_blank=True)
 exit_code = serializers.IntegerField(required=False, default=1)
 logs = serializers.CharField(required=False, default="", allow_blank=True)
class QuestionPayloadSerializer(serializers.Serializer):
 """type=question 时的 payload 验证。"""
 question = serializers.CharField
 options = serializers.ListField(
 child=serializers.CharField, required=False, default=list
 )
 context = serializers.CharField(required=False, default="", allow_blank=True)
 code_snippet = serializers.CharField(required=False, default="", allow_blank=True) # Phase 新增
 default_option = serializers.CharField(required=False, default="", allow_blank=True)
 timeout_minutes = serializers.IntegerField(required=False, default=10)
class HeartbeatPayloadSerializer(serializers.Serializer):
 """type=heartbeat 时的 payload 验证。"""
 progress = serializers.FloatField(required=False, default=0.0)
 message = serializers.CharField(required=False, default="", allow_blank=True)
class ProgressPayloadSerializer(serializers.Serializer):
 """type=progress 时的 payload 验证。"""
 phase = serializers.CharField(required=False, default="", allow_blank=True)
 progress = serializers.FloatField(required=False, default=0.0)
 message = serializers.CharField(required=False, default="", allow_blank=True)
class ActionLogPayloadSerializer(serializers.Serializer):
 """type=action_log 时的 payload 验证。"""
 action_type = serializers.ChoiceField(choices=ActionLog.ActionType.choices)
 tool_name = serializers.CharField(required=False, default="", allow_blank=True)
 input = serializers.DictField(default=dict)
 output = serializers.DictField(default=dict)
 timestamp = serializers.DateTimeField
 duration_ms = serializers.IntegerField(required=False, default=0)
 thinking = serializers.CharField(required=False, default="", allow_blank=True)
 model = serializers.CharField(required=False, default="", allow_blank=True)
 sequence = serializers.IntegerField(default=0)
class TokenUsagePayloadSerializer(serializers.Serializer):
 """type=token_usage 时的 payload 验证。"""
 input_tokens = serializers.IntegerField
 output_tokens = serializers.IntegerField
 cache_read_tokens = serializers.IntegerField(required=False, default=0)
 cache_write_tokens = serializers.IntegerField(required=False, default=0)
 model = serializers.CharField
 timestamp = serializers.DateTimeField
 total_cost_usd = serializers.DecimalField(
 max_digits=10, decimal_places=6, required=False, default=0
 )

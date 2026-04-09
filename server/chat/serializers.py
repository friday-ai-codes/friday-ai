"""Serializers for chat API."""
from rest_framework import serializers
class ChatMessageSerializer(serializers.Serializer):
 """Serializer for chat message."""
 role = serializers.ChoiceField(choices=["user", "assistant", "system"])
 content = serializers.CharField
class ChatCompletionRequestSerializer(serializers.Serializer):
 """Serializer for chat completion request."""
 model = serializers.CharField(help_text="模型 ID")
 messages = ChatMessageSerializer(many=True, help_text="消息列表")
 source = serializers.ChoiceField(
 choices=["system", "project"],
 default="system",
 help_text="配置来源",
 )
 project_id = serializers.IntegerField(
 required=False,
 allow_null=True,
 help_text="项目 ID（当 source=project 时必填）",
 )
 api_key = serializers.CharField(
 required=False,
 allow_null=True,
 allow_blank=True,
 help_text="临时 API Key（用于测试未保存的配置）",
 )
 base_url = serializers.CharField(
 required=False,
 allow_null=True,
 allow_blank=True,
 help_text="临时 Base URL（用于测试未保存的配置）",
 )
 max_tokens = serializers.IntegerField(
 default=4096,
 min_value=1,
 max_value=100000,
 help_text="最大 token 数",
 )
 def validate(self, attrs):
 """Validate the request."""
 if attrs.get("source") == "project" and not attrs.get("project_id"):
 # Check if temporary credentials are provided
 if not attrs.get("api_key"):
 raise serializers.ValidationError(
 {"project_id": "使用项目配置时必须提供 project_id 或临时 api_key"}
 )
 return attrs
class ModelsRequestSerializer(serializers.Serializer):
 """Serializer for models list request."""
 source = serializers.ChoiceField(
 choices=["system", "project"],
 default="system",
 help_text="配置来源",
 )
 project_id = serializers.IntegerField(
 required=False,
 allow_null=True,
 help_text="项目 ID（当 source=project 时必填）",
 )
 api_key = serializers.CharField(
 required=False,
 allow_null=True,
 allow_blank=True,
 help_text="临时 API Key（用于测试未保存的配置）",
 )
 base_url = serializers.CharField(
 required=False,
 allow_null=True,
 allow_blank=True,
 help_text="临时 Base URL（用于测试未保存的配置）",
 )
 def validate(self, attrs):
 """Validate the request."""
 if attrs.get("source") == "project" and not attrs.get("project_id"):
 if not attrs.get("api_key"):
 raise serializers.ValidationError(
 {"project_id": "使用项目配置时必须提供 project_id 或临时 api_key"}
 )
 return attrs
class ModelSerializer(serializers.Serializer):
 """Serializer for model info."""
 id = serializers.CharField
 name = serializers.CharField
 created = serializers.IntegerField(allow_null=True)
class ModelsResponseSerializer(serializers.Serializer):
 """Serializer for models list response."""
 models = ModelSerializer(many=True)
class ChatCompletionResponseSerializer(serializers.Serializer):
 """Serializer for chat completion response."""
 content = serializers.CharField
 model = serializers.CharField
 usage = serializers.DictField(child=serializers.IntegerField, allow_null=True)
# ============================================================================
# Conversation Serializers (Phase)
# ============================================================================
class CreateConversationSerializer(serializers.Serializer):
 """创建对话请求。"""
 project_id = serializers.UUIDField(help_text="项目 ID")
 title = serializers.CharField(max_length=200, default="新对话", required=False)
 model = serializers.CharField(
 max_length=100,
 required=False,
 default="",
 allow_blank=True,
 help_text="LLM 模型 ID（可选，为空时使用系统默认）",
 )
class ConversationListSerializer(serializers.Serializer):
 """对话列表项。"""
 id = serializers.UUIDField
 project_id = serializers.UUIDField
 title = serializers.CharField
 model = serializers.CharField(required=False, allow_blank=True)
 created_at = serializers.DateTimeField
 updated_at = serializers.DateTimeField
class ConversationMessageSerializer(serializers.Serializer):
 """对话消息。"""
 id = serializers.UUIDField
 role = serializers.CharField
 content = serializers.CharField(allow_blank=True)
 tool_calls = serializers.JSONField(required=False, allow_null=True)
 tool_call_id = serializers.CharField(required=False, allow_blank=True)
 metadata = serializers.JSONField(required=False)
 created_at = serializers.DateTimeField
class ConversationDetailSerializer(serializers.Serializer):
 """对话详情（含消息列表）。"""
 id = serializers.UUIDField
 project_id = serializers.UUIDField
 title = serializers.CharField
 created_at = serializers.DateTimeField
 updated_at = serializers.DateTimeField
 messages = ConversationMessageSerializer(many=True, required=False)
class RuntimeLogSerializer(serializers.Serializer):
 """运行态日志。"""
 type = serializers.CharField
 content = serializers.CharField(allow_blank=True)
 ts = serializers.IntegerField
class TaskProgressSerializer(serializers.Serializer):
 """编排任务进度。"""
 completed = serializers.IntegerField
 total = serializers.IntegerField
class ConversationRuntimeSerializer(serializers.Serializer):
 """对话运行态。"""
 conversation_id = serializers.UUIDField
 active = serializers.BooleanField
 mode = serializers.CharField(allow_null=True, required=False)
 status = serializers.CharField(allow_null=True, required=False)
 orchestration_run_id = serializers.CharField(allow_blank=True, required=False)
 phase = serializers.CharField(allow_null=True, allow_blank=True, required=False)
 task_progress = TaskProgressSerializer(allow_null=True, required=False)
 session_id = serializers.CharField(allow_blank=True, required=False)
 task_description = serializers.CharField(allow_blank=True, required=False)
 progress_message = serializers.CharField(allow_blank=True, required=False)
 progress_percent = serializers.FloatField(allow_null=True, required=False)
 logs = RuntimeLogSerializer(many=True, required=False)
class WebPushPublicKeySerializer(serializers.Serializer):
 """Web Push 公钥响应。"""
 public_key = serializers.CharField
 subject = serializers.CharField
class WebPushSubscriptionKeysSerializer(serializers.Serializer):
 """Push 订阅密钥。"""
 p256dh = serializers.CharField
 auth = serializers.CharField
class WebPushSubscriptionSerializer(serializers.Serializer):
 """Push 订阅请求。"""
 endpoint = serializers.CharField
 keys = WebPushSubscriptionKeysSerializer
 user_agent = serializers.CharField(required=False, allow_blank=True)
class WebPushUnsubscribeSerializer(serializers.Serializer):
 """Push 取消订阅请求。"""
 endpoint = serializers.CharField
class SendMessageSerializer(serializers.Serializer):
 """发送消息请求。"""
 content = serializers.CharField(min_length=1, help_text="消息内容")
 role = serializers.ChoiceField(
 choices=["developer", "pm", "designer", "qa", "general"],
 default="developer",
 required=False,
 help_text="用户角色（影响 AI 回答风格）",
 )
 force_deep_analysis = serializers.BooleanField(
 default=False,
 required=False,
 help_text="强制使用深度分析模式（跳过 RAG，直接调用 Runner + Claude Code）",
 )
 feishu_doc_id = serializers.CharField(
 required=False,
 allow_blank=True,
 default="",
 help_text="前端从消息中提取的飞书文档 ID",
 )
# ============================================================================
# CodingSession Serializers (Phase)
# ============================================================================
class CodingSessionSerializer(serializers.Serializer):
 """CodingSession 详情序列化器。"""
 id = serializers.UUIDField(read_only=True)
 status = serializers.CharField(read_only=True)
 tech_plan = serializers.CharField(read_only=True)
 affected_files = serializers.JSONField(read_only=True)
 revision_count = serializers.IntegerField(read_only=True)
 repository_id = serializers.UUIDField(read_only=True)
 branch_name = serializers.CharField(read_only=True)
 pr_url = serializers.URLField(read_only=True, allow_blank=True)
 error_message = serializers.CharField(read_only=True, allow_blank=True)
 confirmation_step = serializers.CharField(read_only=True, allow_blank=True)
 suggested_commit_message = serializers.CharField(read_only=True, allow_blank=True)
 suggested_pr_title = serializers.CharField(read_only=True, allow_blank=True)
 suggested_pr_description = serializers.CharField(read_only=True, allow_blank=True)
 conflict_check_result = serializers.JSONField(read_only=True)
 diff_summary = serializers.JSONField(read_only=True)
 created_at = serializers.DateTimeField(read_only=True)
 updated_at = serializers.DateTimeField(read_only=True)
class ExportToFeishuSerializer(serializers.Serializer):
 """导出对话消息到飞书文档。"""
 message_ids = serializers.ListField(
 child=serializers.UUIDField,
 min_length=1,
 help_text="要导出的消息 ID 列表",
 )
 title = serializers.CharField(
 max_length=200,
 help_text="飞书文档标题",
 )
 folder_token = serializers.CharField(
 required=False,
 allow_blank=True,
 default="",
 help_text="目标文件夹 token（可选，覆盖项目配置）",
 )

"""Prompt DRF serializers。
Phase Task 1 产出：6 个 Serializer 覆盖 list / retrieve / create /
update / preview / version 路径。
-：扁平 `/api/prompts/` 下的单一 Prompt ViewSet 共享这套 serializer
-：`declared_variables` 是运行时 regex 派生的 SerializerMethodField，不持久化
- T-：`body` max_length 32KB、`variables.value` max_length 1024，serializer
 层早拒 DoS 值
"""
from __future__ import annotations
from typing import Any
from rest_framework import serializers
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.services import get_declared_variables
# DoS / body 长度防护（与 Plan VARIABLE_MAX_LENGTH 对齐 + 32KB body cap）
_BODY_MAX_LENGTH = 32768
_VARIABLE_VALUE_MAX_LENGTH = 1024
class PromptVersionSerializer(serializers.ModelSerializer):
 """PromptVersion 只读 serializer（嵌套在 Detail + 用于 versions list）。"""
 declared_variables = serializers.SerializerMethodField
 class Meta:
 model = PromptVersion
 fields = [
 "id",
 "version",
 "body",
 "variables_schema",
 "declared_variables",
 "change_note",
 "created_by",
 "created_at",
 ]
 read_only_fields = fields
 def get_declared_variables(self, obj: PromptVersion) -> list[str]:
 return get_declared_variables(obj.body)
class PromptListSerializer(serializers.ModelSerializer):
 """list 端点：轻量，不含 body。"""
 active_version_number = serializers.IntegerField(
 source="active_version.version",
 read_only=True,
 default=None,
 )
 class Meta:
 model = Prompt
 fields = [
 "id",
 "slug",
 "category",
 "scope",
 "project",
 "title",
 "description",
 "is_builtin",
 "active_version_number",
 "created_at",
 "updated_at",
 ]
 read_only_fields = ["id", "is_builtin", "created_at", "updated_at"]
class PromptDetailSerializer(serializers.ModelSerializer):
 """detail 端点：嵌套 active_version 完整 body + 运行时 declared_variables。"""
 active_version = PromptVersionSerializer(read_only=True)
 declared_variables = serializers.SerializerMethodField
 class Meta:
 model = Prompt
 fields = [
 "id",
 "slug",
 "category",
 "scope",
 "project",
 "title",
 "description",
 "is_builtin",
 "active_version",
 "declared_variables",
 "created_by",
 "created_at",
 "updated_at",
 ]
 read_only_fields = [
 "id",
 "is_builtin",
 "active_version",
 "declared_variables",
 "created_by",
 "created_at",
 "updated_at",
 ]
 def get_declared_variables(self, obj: Prompt) -> list[str]:
 if obj.active_version is None:
 return
 return get_declared_variables(obj.active_version.body)
class PromptCreateSerializer(serializers.ModelSerializer):
 """POST 端点：含首版 body 字段。scope + project 互斥校验在 validate。"""
 body = serializers.CharField(required=True, max_length=_BODY_MAX_LENGTH)
 variables_schema = serializers.JSONField(required=False, default=dict)
 change_note = serializers.CharField(
 required=False,
 allow_blank=True,
 default="",
 )
 class Meta:
 model = Prompt
 fields = [
 "slug",
 "category",
 "scope",
 "project",
 "title",
 "description",
 "body",
 "variables_schema",
 "change_note",
 ]
 def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
 scope = attrs.get("scope")
 project = attrs.get("project")
 if scope == PromptScope.SYSTEM and project is not None:
 raise serializers.ValidationError(
 {"project": "系统级 prompt 不能绑定 project"}
 )
 if scope == PromptScope.PROJECT and project is None:
 raise serializers.ValidationError(
 {"project": "项目级 prompt 必须指定 project"}
 )
 return attrs
class PromptUpdateSerializer(serializers.Serializer):
 """PATCH 端点：body 变更触发新版本；其他字段 inline 更新。
 所有字段可选 —— partial=True 由 view 层传入。
 """
 title = serializers.CharField(required=False, max_length=200)
 description = serializers.CharField(required=False, allow_blank=True)
 body = serializers.CharField(required=False, max_length=_BODY_MAX_LENGTH)
 variables_schema = serializers.JSONField(required=False)
 change_note = serializers.CharField(
 required=False,
 allow_blank=True,
 default="",
 )
class PromptPreviewRequestSerializer(serializers.Serializer):
 """POST /{id}/preview/ 的请求体 serializer。
 `variables` 每个值 max_length=1024，与 Plan `_sanitize_variables` 的
 `VARIABLE_MAX_LENGTH` 对齐 —— DoS 防护 serializer 层兜底。
 """
 variables = serializers.DictField(
 child=serializers.CharField(
 allow_blank=True,
 max_length=_VARIABLE_VALUE_MAX_LENGTH,
 ),
 required=False,
 default=dict,
 )

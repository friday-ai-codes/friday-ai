"""tools app serializers —— 绑定读/写、可绑定列表、执行端点四类序列化器。

输出序列化器严格走字段白名单，**绝不**暴露 ``token_hash`` 或令牌明文
（沿用 ``AccessTokenSerializer`` 契约，T-10-05）。写入序列化器的两个
``validate_*`` 是绑定维度的唯一授权关卡：access_token 归属校验（owner 隔离，
T-10-01）+ source/active 白名单（仅 mcp/skill 且激活，T-10-06）。
"""

from __future__ import annotations

from access_tokens.models import AccessToken
from rest_framework import serializers

from .models import RemoteTool, ToolTokenBinding


class BoundTokenSerializer(serializers.ModelSerializer):
    """绑定所引用令牌的最小只读视图 —— 仅元数据，绝不含明文 / token_hash。"""

    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = AccessToken
        fields = ["id", "name", "token_prefix", "token_suffix", "is_valid"]
        read_only_fields = fields


class ToolTokenBindingSerializer(serializers.ModelSerializer):
    """绑定输出 —— 嵌套令牌元数据 + 扁平工具信息，全只读。"""

    access_token = BoundTokenSerializer(read_only=True)
    remote_tool_name = serializers.CharField(source="remote_tool.name", read_only=True)
    remote_tool_source = serializers.CharField(source="remote_tool.source", read_only=True)

    class Meta:
        model = ToolTokenBinding
        fields = [
            "id",
            "access_token",
            "remote_tool",
            "remote_tool_name",
            "remote_tool_source",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ToolTokenBindingCreateSerializer(serializers.Serializer):
    """绑定写入入参 —— access_token 归属校验 + source/active 白名单。

    两个 ``validate_*`` 是 owner 隔离在 access_token 维度的唯一关卡：
    - ``validate_access_token``：断言令牌属当前用户且仍有效，越权引用一律
      ValidationError（per Pitfall 1，不泄漏存在性）；已吊销/过期令牌一律拒绝
      （per Pitfall 5，服务端强校验，绝不让用户绑到失效令牌——不只是前端过滤）。
    - ``validate_remote_tool``：仅可绑 source ∈ {mcp, skill} 且 is_active 的工具。
    """

    remote_tool = serializers.PrimaryKeyRelatedField(queryset=RemoteTool.objects.all())
    access_token = serializers.PrimaryKeyRelatedField(queryset=AccessToken.objects.all())

    def validate_access_token(self, value: AccessToken) -> AccessToken:
        request = self.context["request"]
        if value.created_by_id != request.user.id:
            raise serializers.ValidationError("无法引用他人的 Access Token。")
        # 服务端强校验令牌有效性（per Pitfall 5）：吊销/过期令牌不可绑定，
        # 否则直接 API 调用可绕过前端过滤绑到失效令牌（执行时才 401，绑定形同虚设）。
        if not value.is_valid:
            raise serializers.ValidationError("令牌已吊销或已过期，无法绑定。")
        return value

    def validate_remote_tool(self, value: RemoteTool) -> RemoteTool:
        if value.source not in (RemoteTool.Source.MCP, RemoteTool.Source.SKILL):
            raise serializers.ValidationError("仅可绑定 mcp / skill 工具。")
        if not value.is_active:
            raise serializers.ValidationError("工具未激活，无法绑定。")
        return value


class BindableToolSerializer(serializers.ModelSerializer):
    """可绑定工具的只读展示视图（id / name / description / source）。"""

    class Meta:
        model = RemoteTool
        fields = ["id", "name", "description", "source"]
        read_only_fields = fields


class RemoteToolExecuteSerializer(serializers.Serializer):
    """执行端点入参 —— 按 name 执行（RTOOL-01）；arguments 缺省为空 dict。"""

    name = serializers.CharField()
    arguments = serializers.DictField(required=False, default=dict)

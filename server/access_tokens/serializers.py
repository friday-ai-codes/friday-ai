"""access_tokens app serializers。

输出序列化器严禁暴露 ``token_hash`` 或明文（contract / contract），仅返回元数据。
"""

from __future__ import annotations

from rest_framework import serializers

from .models import AccessToken


class AccessTokenSerializer(serializers.ModelSerializer):
    """token 元数据输出 —— 绝不含明文与 token_hash。"""

    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = AccessToken
        fields = [
            "id",
            "name",
            "note",
            "token_prefix",
            "token_suffix",
            "created_at",
            "expires_at",
            "revoked_at",
            "last_used_at",
            "is_valid",
        ]
        read_only_fields = fields


class AccessTokenCreateSerializer(serializers.Serializer):
    """创建入参 —— name 必填，note/expires_at 可选（缺省由 view 填 now()+90d，可为 None 永不过期）。

    note 仅创建时填写；token_suffix 由服务端从明文派生，不接受入参。
    """

    name = serializers.CharField(max_length=200)
    note = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

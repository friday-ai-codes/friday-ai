"""tools app serializers —— 执行端点入参。"""

from __future__ import annotations

from rest_framework import serializers


class RemoteToolExecuteSerializer(serializers.Serializer):
    """执行端点入参 —— 按 name 执行（RTOOL-01）；arguments 缺省为空 dict。"""

    name = serializers.CharField()
    arguments = serializers.DictField(required=False, default=dict)

"""HumanTask 统一待办序列化器（Chassis v2 · P8）。

- ``HumanTaskViewSerializer``：统一待办呈现形态（物化行 + 投影行共用，镜像
  ``HumanTaskView`` dataclass），收件箱 list 输出用。
- ``OpenHumanTaskSerializer``：``open_task`` 入参校验（risk_ack / takeover 等原生待办）。
- ``AnswerClarificationSerializer`` / ``ResolveSerializer`` 等动作入参校验。

写入仅经 ``HumanTaskService`` / ``ClarificationService``（INV-6）；序列化器只做形状/校验。
"""

from __future__ import annotations

from rest_framework import serializers

from delivery.models import HumanTaskScope, HumanTaskType

# 注：统一待办呈现形态见 ``HumanTaskService.HumanTaskView`` dataclass；inbox list 直接返回其
# ``to_dict()`` 标量 dict（含保留字段 ``source``，DRF Serializer 字段名占用 ``source`` 与
# ``Field.source`` 冲突，故输出不经 Serializer 二次塑形）。


class OpenHumanTaskSerializer(serializers.Serializer):
    """开原生待办入参（risk_ack / takeover / 其它显式待办）。"""

    task_type = serializers.ChoiceField(choices=HumanTaskType.values)
    scope = serializers.ChoiceField(choices=HumanTaskScope.values)
    subject_id = serializers.CharField(max_length=64)
    assignee_user_id = serializers.CharField(
        max_length=64, required=False, allow_null=True, allow_blank=True
    )
    assignee_role = serializers.CharField(
        max_length=64, required=False, allow_null=True, allow_blank=True
    )
    source_signal = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    dedup_key = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default=""
    )
    resolution = serializers.DictField(required=False, default=dict)

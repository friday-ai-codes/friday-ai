"""initial implementation plan contract/contract：硬删 Conversation.provider_type 字段。

forwards:
    1. 把 Conversation.provider_type 的值保底写入 metadata.legacy_provider_type
       （若 Conversation 模型含 metadata JSONField；当前 chat/models.py 未引入 metadata
       字段，因此本 migration 采用 log-only 路径：直接 RemoveField）
    2. RemoveField provider_type

reverse:
    1. AddField provider_type 恢复字段
    2. RunPython.noop（历史值丢失；admin 可基于 ProviderCredential 反向推导）

RunPython elidable=False 防 squash 丢失；依赖 plan 的 0010_add_conversation_provider_credential_fk。
"""
from __future__ import annotations

from django.db import migrations


def forwards_noop(apps, schema_editor):
    """initial implementation plan：Conversation.provider_type 已在 initial implementation/229 UI cutover 后
    不再被写入。本函数作为 RunPython 的 forwards 钩子保留结构（便于测试观察），
    不做实际数据转换。
    """
    # 历史数据：由于 Conversation 无 metadata JSONField，provider_type 值硬删即丢失。
    # 调用方（前端 / ProviderConfigService）已在 plan-07 切换到 provider_credential_id FK。
    return


def reverse_noop(apps, schema_editor):
    """reverse：字段结构由 AddField 重建；历史值不可还原。"""
    return


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0010_add_conversation_provider_credential_fk"),
    ]

    operations = [
        migrations.RunPython(forwards_noop, reverse_noop, elidable=False),
        migrations.RemoveField(
            model_name="Conversation",
            name="provider_type",
        ),
    ]

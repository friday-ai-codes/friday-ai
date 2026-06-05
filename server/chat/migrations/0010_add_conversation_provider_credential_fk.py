"""initial implementation plan Task 01：Conversation 新增 provider_credential_id FK + status 字段。

contract contract/contract 依赖字段：
    - provider_credential_id → system.ProviderCredential（on_delete=SET_NULL）：对话级 pin 凭证
    - status → TextChoices(draft/running/paused/interrupted/completed/stopped/error)：pin 冻结判据真源

两字段均允许 null/default，存量对话默认 status=draft 且 provider_credential_id=NULL。
Reversible：AddField 纯 schema op，无需 RunPython。
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0009_alter_conversation_provider_type"),
        ("system", "0005_seed_provider_credentials"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="provider_credential_id",
            field=models.ForeignKey(
                blank=True,
                help_text="对话级固定 Provider 凭证（contract pin 语义 contract）",
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="conversations",
                to="system.providercredential",
            ),
        ),
        migrations.AddField(
            model_name="conversation",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "草稿"),
                    ("running", "进行中"),
                    ("paused", "已暂停"),
                    ("interrupted", "已中断"),
                    ("completed", "已完成"),
                    ("stopped", "已停止"),
                    ("error", "异常"),
                ],
                default="draft",
                help_text="contract pin 冻结判据；frozen 态（completed/stopped/error）拒绝修改 provider_credential_id",
                max_length=20,
                verbose_name="对话状态",
            ),
        ),
    ]

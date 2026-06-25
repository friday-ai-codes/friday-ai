"""Phase 76：feishu TriggerLog/FeishuBotThread project→space FK 字段重命名。"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("feishu", "0004_add_chat_type_to_feishu_bot_message"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RenameField(
            model_name="triggerlog", old_name="project", new_name="space"
        ),
        migrations.RenameField(
            model_name="feishubotthread", old_name="project", new_name="space"
        ),
    ]

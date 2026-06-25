"""Phase 76：chat.Conversation.project→space FK 字段重命名（元数据级列重命名）。"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0025_codingsession_target_branch"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RenameField(
            model_name="conversation", old_name="project", new_name="space"
        ),
    ]

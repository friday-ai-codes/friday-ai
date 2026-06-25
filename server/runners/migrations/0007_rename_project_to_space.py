"""Phase 76：runners RegistrationToken.project→space、Runner.projects→spaces 重命名。

``Runner.spaces`` 为 M2M 字段：``RenameField`` 重命名隐式关联表（元数据级，无数据搬迁）。
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("runners", "0006_runnertaskassignment_feishu_message_id"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RenameField(
            model_name="registrationtoken", old_name="project", new_name="space"
        ),
        migrations.RenameField(
            model_name="runner", old_name="projects", new_name="spaces"
        ),
    ]

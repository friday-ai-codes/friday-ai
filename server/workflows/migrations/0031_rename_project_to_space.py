"""Phase 76：workflows 内 project→space FK 字段重命名（含命名索引重建）。

顺序命门（SQLite）：先 RemoveIndex，再 RenameField，最后 AddIndex。
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0030_feishu_trigger_token"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="alertrule", name="workflow_al_project_85785c_idx"
        ),
        migrations.RemoveIndex(
            model_name="workflow", name="workflows_project_570176_idx"
        ),
        migrations.RemoveIndex(
            model_name="workflowexecution", name="workflow_ex_project_774a8b_idx"
        ),
        migrations.RenameField(
            model_name="workflow", old_name="project", new_name="space"
        ),
        migrations.RenameField(
            model_name="workflowexecution", old_name="project", new_name="space"
        ),
        migrations.RenameField(
            model_name="alertrule", old_name="project", new_name="space"
        ),
        migrations.AlterField(
            model_name="alertrule",
            name="space",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="alert_rules",
                to="projects.space",
                verbose_name="所属空间",
            ),
        ),
        migrations.AlterField(
            model_name="workflow",
            name="space",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workflows",
                to="projects.space",
                verbose_name="所属空间",
            ),
        ),
        migrations.AlterField(
            model_name="workflowexecution",
            name="space",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workflow_executions",
                to="projects.space",
                verbose_name="所属空间",
            ),
        ),
        migrations.AddIndex(
            model_name="alertrule",
            index=models.Index(
                fields=["space", "enabled"], name="workflow_al_space_i_80e8fa_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="workflow",
            index=models.Index(
                fields=["space", "is_active"], name="workflows_space_i_6cd729_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="workflowexecution",
            index=models.Index(
                fields=["space", "status"], name="workflow_ex_space_i_b40a89_idx"
            ),
        ),
    ]

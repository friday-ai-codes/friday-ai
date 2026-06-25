"""Phase 76：mcp_tools McpWorkItemContext/McpWorkItemTechnicalPlan project→space。

顺序命门（SQLite）：先 RemoveIndex，再 RenameField，最后 AddIndex。
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mcp_tools", "0008_mcpworkitemtechnicalplan_canonical_plan_id"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="mcpworkitemcontext", name="mcp_work_it_project_372e56_idx"
        ),
        migrations.RemoveIndex(
            model_name="mcpworkitemtechnicalplan",
            name="mcp_work_it_project_59ee4c_idx",
        ),
        migrations.RenameField(
            model_name="mcpworkitemcontext", old_name="project", new_name="space"
        ),
        migrations.RenameField(
            model_name="mcpworkitemtechnicalplan", old_name="project", new_name="space"
        ),
        migrations.AlterField(
            model_name="mcpworkitemcontext",
            name="space",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="mcp_work_item_contexts",
                to="projects.space",
            ),
        ),
        migrations.AlterField(
            model_name="mcpworkitemtechnicalplan",
            name="space",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="mcp_work_item_technical_plans",
                to="projects.space",
            ),
        ),
        migrations.AddIndex(
            model_name="mcpworkitemcontext",
            index=models.Index(
                fields=["space", "-created_at"], name="mcp_work_it_space_i_6a3ba6_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="mcpworkitemtechnicalplan",
            index=models.Index(
                fields=["space", "-created_at"], name="mcp_work_it_space_i_8fbe4e_idx"
            ),
        ),
    ]

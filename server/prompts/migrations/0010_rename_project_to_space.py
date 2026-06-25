"""Phase 76：prompts.Prompt.project→space FK 重命名（含唯一约束/索引重建）。

顺序命门（SQLite）：先 RemoveConstraint/RemoveIndex，再 RenameField，最后 Add*。
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("prompts", "0009_resync_plan_generation_clarification"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="prompt", name="uq_prompt_project_slug"
        ),
        migrations.RemoveIndex(
            model_name="prompt", name="prompts_project_caaa23_idx"
        ),
        migrations.RenameField(
            model_name="prompt", old_name="project", new_name="space"
        ),
        migrations.AlterField(
            model_name="prompt",
            name="space",
            field=models.ForeignKey(
                blank=True,
                help_text="项目级覆盖时非空；系统级为空",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="prompts",
                to="projects.space",
            ),
        ),
        migrations.AddIndex(
            model_name="prompt",
            index=models.Index(
                fields=["space", "scope"], name="prompts_space_i_a5af8c_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="prompt",
            constraint=models.UniqueConstraint(
                condition=models.Q(("scope", "project")),
                fields=("slug", "scope", "space"),
                name="uq_prompt_project_slug",
            ),
        ),
    ]

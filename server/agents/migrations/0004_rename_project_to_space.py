"""Phase 76：agents.AgentSession.project→space FK 字段重命名。

顺序命门（SQLite 表重建）：先 RemoveIndex（引用旧字段的命名索引），再 RenameField，
最后 AddIndex（新字段）；否则 RenameField 的 _remake_table 会重建引用 ``project`` 的
旧索引而报 FieldDoesNotExist。
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0003_nullable_session_project_user"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="agentsession", name="agents_agen_project_8a78f4_idx"
        ),
        migrations.RenameField(
            model_name="agentsession", old_name="project", new_name="space"
        ),
        migrations.AlterField(
            model_name="agentsession",
            name="space",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="agent_sessions",
                to="projects.space",
            ),
        ),
        migrations.AddIndex(
            model_name="agentsession",
            index=models.Index(
                fields=["space", "status"], name="agents_agen_space_i_6db261_idx"
            ),
        ),
    ]

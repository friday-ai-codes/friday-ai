"""Phase 76：knowledge.KnowledgeEntity.project→space FK 重命名（含命名索引重建）。

顺序命门（SQLite）：先 RemoveIndex，再 RenameField，最后 AddIndex。
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("knowledge", "0005_version_toc_tree"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="knowledgeentity", name="idx_kentity_proj_kind"
        ),
        migrations.RenameField(
            model_name="knowledgeentity", old_name="project", new_name="space"
        ),
        migrations.AlterField(
            model_name="knowledgeentity",
            name="space",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="knowledge_entities",
                to="projects.space",
            ),
        ),
        migrations.AddIndex(
            model_name="knowledgeentity",
            index=models.Index(
                fields=["space", "kind"], name="idx_kentity_proj_kind"
            ),
        ),
    ]

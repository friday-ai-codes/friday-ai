"""Phase 76：delivery WorkItem/IngestRun project→space FK 字段重命名（含命名索引重建）。

顺序命门（SQLite）：先 RemoveIndex，再 RenameField，最后 AddIndex。
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("delivery", "0024_ingestrun_durable_queue"),
        ("projects", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="workitem", name="delivery_wo_project_823ff4_idx"
        ),
        migrations.RenameField(
            model_name="workitem", old_name="project", new_name="space"
        ),
        migrations.RenameField(
            model_name="ingestrun", old_name="project", new_name="space"
        ),
        migrations.AlterField(
            model_name="ingestrun",
            name="space",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ingest_runs",
                to="projects.space",
            ),
        ),
        migrations.AlterField(
            model_name="workitem",
            name="space",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="work_items",
                to="projects.space",
            ),
        ),
        migrations.AddIndex(
            model_name="workitem",
            index=models.Index(
                fields=["space", "work_item_type"],
                name="delivery_wo_space_i_39fe04_idx",
            ),
        ),
    ]

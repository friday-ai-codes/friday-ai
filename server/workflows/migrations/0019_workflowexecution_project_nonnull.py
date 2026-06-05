"""Step 3: 移除 null=True，添加非空约束和索引。"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0018_backfill_execution_project"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowexecution",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="workflow_executions",
                to="projects.project",
                verbose_name="所属项目",
            ),
        ),
        migrations.AddIndex(
            model_name="workflowexecution",
            index=models.Index(
                fields=["project", "status"],
                name="workflow_ex_project_774a8b_idx",
            ),
        ),
    ]

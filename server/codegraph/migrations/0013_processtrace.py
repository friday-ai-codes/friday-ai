# Generated manually for Phase 126 / EXEC-01 — ADD TABLE only (D-01).

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("codegraph", "0012_symbolcommunity_member_keys"),
        ("repositories", "0026_repository_graph_build_progress"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProcessTrace",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "branch_name",
                    models.CharField(blank=True, default="", max_length=200),
                ),
                ("process_key", models.CharField(max_length=640)),
                ("name", models.CharField(max_length=640)),
                ("entry_endpoint", models.JSONField(default=dict)),
                ("steps", models.JSONField(default=list)),
                (
                    "community_class",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("intra_community", "社区内"),
                            ("cross_community", "跨社区"),
                        ],
                        default="",
                        max_length=32,
                    ),
                ),
                ("step_count", models.PositiveIntegerField(default=0)),
                ("flags", models.JSONField(blank=True, default=dict)),
                (
                    "built_at_sha",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "repository",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="process_traces",
                        to="repositories.repository",
                    ),
                ),
            ],
            options={
                "verbose_name": "执行流",
                "verbose_name_plural": "执行流",
                "indexes": [
                    models.Index(
                        fields=["repository", "branch_name"],
                        name="codegraph_p_reposit_proc_br_idx",
                    ),
                ],
                "unique_together": {("repository", "branch_name", "process_key")},
            },
        ),
    ]

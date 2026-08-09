# Generated manually for Phase 127 / D-05 — ADD TABLE only (soft refs, no Symbol FK).

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("codegraph", "0013_processtrace"),
        ("repositories", "0026_repository_graph_build_progress"),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityFinding",
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
                (
                    "mr_key",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=200
                    ),
                ),
                ("rule_id", models.CharField(db_index=True, max_length=512)),
                ("severity", models.CharField(db_index=True, max_length=32)),
                ("file_path", models.CharField(max_length=1024)),
                ("line", models.PositiveIntegerField(blank=True, null=True)),
                ("message", models.TextField(blank=True, default="")),
                ("fingerprint", models.CharField(db_index=True, max_length=128)),
                ("scan_sha", models.CharField(blank=True, default="", max_length=64)),
                (
                    "status",
                    models.CharField(db_index=True, default="open", max_length=32),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "repository",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="security_findings",
                        to="repositories.repository",
                    ),
                ),
            ],
            options={
                "verbose_name": "安全 finding",
                "verbose_name_plural": "安全 findings",
                "indexes": [
                    models.Index(
                        fields=["repository", "branch_name"],
                        name="codegraph_s_reposit_sf_br_idx",
                    ),
                    models.Index(
                        fields=["repository", "mr_key"],
                        name="codegraph_s_reposit_sf_mr_idx",
                    ),
                    models.Index(
                        fields=["repository", "fingerprint"],
                        name="codegraph_s_reposit_sf_fp_idx",
                    ),
                ],
            },
        ),
    ]

# Generated manually for Phase 125 / MOD-01 — ADD TABLE only (D-01).

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("codegraph", "0010_branch_name_constraints"),
        ("repositories", "0026_repository_graph_build_progress"),
    ]

    operations = [
        migrations.CreateModel(
            name="SymbolCommunity",
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
                ("community_key", models.CharField(max_length=64)),
                ("algorithm", models.CharField(default="louvain", max_length=32)),
                ("member_count", models.PositiveIntegerField(default=0)),
                ("members", models.JSONField(default=list)),
                ("top_files", models.JSONField(default=list)),
                (
                    "member_fingerprint",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("summary", models.TextField(blank=True, null=True)),
                (
                    "summary_model",
                    models.CharField(blank=True, max_length=128, null=True),
                ),
                ("summary_generated_at", models.DateTimeField(blank=True, null=True)),
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
                        related_name="symbol_communities",
                        to="repositories.repository",
                    ),
                ),
            ],
            options={
                "verbose_name": "符号社区",
                "verbose_name_plural": "符号社区",
                "indexes": [
                    models.Index(
                        fields=["repository", "branch_name"],
                        name="codegraph_s_reposit_comm_br_idx",
                    ),
                    models.Index(
                        fields=["repository", "branch_name", "member_fingerprint"],
                        name="codegraph_s_reposit_comm_fp_idx",
                    ),
                ],
                "unique_together": {("repository", "branch_name", "community_key")},
            },
        ),
    ]

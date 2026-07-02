"""功能点详情结构化缓存表（按 project + 原文哈希持久化 Step 2 结果）。"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("initiatives", "0012_feature_list_draft"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeatureDetailCache",
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
                ("source_hash", models.CharField(max_length=64, verbose_name="原文 SHA-256")),
                (
                    "sections",
                    models.JSONField(blank=True, default=list, verbose_name="结构化段落"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feature_detail_caches",
                        to="initiatives.project",
                        verbose_name="项目",
                    ),
                ),
            ],
            options={
                "verbose_name": "功能点详情缓存",
                "verbose_name_plural": "功能点详情缓存",
                "db_table": "initiative_feature_detail_cache",
            },
        ),
        migrations.AddIndex(
            model_name="featuredetailcache",
            index=models.Index(
                fields=["project", "source_hash"],
                name="initiative__project_f4d25f_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="featuredetailcache",
            constraint=models.UniqueConstraint(
                fields=["project", "source_hash"],
                name="uq_feature_detail_cache_project_hash",
            ),
        ),
    ]

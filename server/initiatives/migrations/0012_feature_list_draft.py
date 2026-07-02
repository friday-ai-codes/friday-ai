"""feature list 异步解析草稿表（每项目一份，OneToOne）。"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("initiatives", "0011_state_api_schema"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeatureListDraft",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("idle", "空闲"),
                            ("parsing", "解析中"),
                            ("partial", "部分完成"),
                            ("ready", "解析完成（待确认）"),
                            ("failed", "解析失败"),
                        ],
                        default="idle",
                        max_length=16,
                        verbose_name="状态",
                    ),
                ),
                (
                    "phase",
                    models.CharField(
                        choices=[
                            ("idle", "未开始"),
                            ("modules", "解析模块中"),
                            ("features", "逐功能点解析中"),
                            ("done", "已完成"),
                        ],
                        default="idle",
                        max_length=16,
                        verbose_name="阶段",
                    ),
                ),
                (
                    "progress",
                    models.PositiveSmallIntegerField(default=0, verbose_name="进度百分比"),
                ),
                (
                    "source_text",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="粘贴/取回的原始文档，供模块任务按行号切片、断点续跑",
                        verbose_name="原文",
                    ),
                ),
                (
                    "tree",
                    models.JSONField(blank=True, default=dict, verbose_name="解析树"),
                ),
                (
                    "error",
                    models.TextField(blank=True, default="", verbose_name="失败原因（脱敏）"),
                ),
                (
                    "job_id",
                    models.CharField(
                        blank=True, default="", max_length=200, verbose_name="作业标识"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feature_list_draft",
                        to="initiatives.project",
                        verbose_name="项目",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="最近操作人",
                    ),
                ),
            ],
            options={
                "verbose_name": "Feature List 草稿",
                "verbose_name_plural": "Feature List 草稿",
                "db_table": "initiative_feature_list_drafts",
            },
        ),
        migrations.AddIndex(
            model_name="featurelistdraft",
            index=models.Index(
                fields=["status"], name="initiative__status_f26224_idx"
            ),
        ),
    ]

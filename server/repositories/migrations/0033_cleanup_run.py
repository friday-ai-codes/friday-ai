# CleanupRun 建表迁移（Phase 23 Plan 02，EXCL-04 / EXCL-06）。
#
# 仅 CreateModel：持久化单次清理运行（status/mode/命中数/失败/sensitive 结果），
# 供后台异步清理结果回流前端（状态查询端点，W1/W2）。不回填历史数据。

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repositories", "0032_repo_exclusion_rule"),
    ]

    operations = [
        migrations.CreateModel(
            name="CleanupRun",
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
                    "mode",
                    models.CharField(
                        choices=[("normal", "普通清理"), ("sensitive", "敏感清理")],
                        default="normal",
                        max_length=16,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "进行中"),
                            ("completed", "已完成"),
                            ("failed", "失败"),
                        ],
                        default="running",
                        max_length=16,
                    ),
                ),
                (
                    "match_count",
                    models.IntegerField(default=0, help_text="本次清理命中（差异）文件数"),
                ),
                (
                    "failures",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="逐文件/逐面失败标记列表（best-effort，不阻断其余）",
                    ),
                ),
                (
                    "sensitive",
                    models.JSONField(
                        blank=True,
                        default=None,
                        help_text="敏感清理结果 dict（各面计数 + unscrubbed + caveat），普通模式为 null",
                        null=True,
                    ),
                ),
                ("error", models.TextField(blank=True, default="")),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "repository",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cleanup_runs",
                        to="repositories.repository",
                    ),
                ),
            ],
            options={
                "verbose_name": "清理运行记录",
                "verbose_name_plural": "清理运行记录",
                "db_table": "cleanup_runs",
                "indexes": [
                    models.Index(
                        fields=["repository", "-started_at"],
                        name="idx_cleanup_repo_started",
                    )
                ],
            },
        ),
    ]

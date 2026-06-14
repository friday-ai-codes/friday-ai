# RepoExclusionRule 建表迁移（Phase 22 fail-closed）。
#
# 仅 CreateModel，不回填历史数据（per D-04）：本阶段只在读取/暴露/扫描侧加判定层，
# 既有部署升级后仅内置全局默认 + SystemSetting 生效，行为向后兼容。
# 存量派生数据的清理 / 对账留待 Phase 23（EXCL-04..06）。

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repositories", "0031_convert_ssh_git_urls"),
    ]

    operations = [
        migrations.CreateModel(
            name="RepoExclusionRule",
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
                    "pattern",
                    models.CharField(
                        help_text="规则模式：dir 为目录前缀，glob 为通配模式，regex 为正则（相对仓库根 POSIX）",
                        max_length=500,
                    ),
                ),
                (
                    "rule_type",
                    models.CharField(
                        choices=[("dir", "目录前缀"), ("glob", "glob 通配"), ("regex", "正则")],
                        default="glob",
                        max_length=16,
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("user", "用户配置"),
                            ("ai_suggested", "AI 建议"),
                            ("global", "全局默认 override 标记"),
                        ],
                        default="user",
                        help_text="source=global + enabled=False 表示关闭某条全局默认的 override 标记",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "repository",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exclusion_rules",
                        to="repositories.repository",
                    ),
                ),
            ],
            options={
                "verbose_name": "仓库排除规则",
                "verbose_name_plural": "仓库排除规则",
                "db_table": "repo_exclusion_rules",
                "indexes": [
                    models.Index(
                        fields=["repository", "enabled"],
                        name="idx_repo_exclusion_enabled",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("repository", "rule_type", "pattern", "source"),
                        name="uq_repo_exclusion_rule",
                    )
                ],
            },
        ),
    ]

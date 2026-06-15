# GitInstanceCredential 建表迁移（Phase 26 REPO-01）。
#
# 仅 CreateModel，不回填历史数据（per D-04 向后兼容）：实例级凭证池为新增可选层，
# 既有 per-repo GitCredential 数据不触碰、行为不回退。解析优先级见
# services.git_credentials（per-repo token 优先 → 实例池 host fallback）。

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repositories", "0035_repository_commit_index_boundary"),
    ]

    operations = [
        migrations.CreateModel(
            name="GitInstanceCredential",
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
                    "host",
                    models.CharField(
                        db_index=True,
                        help_text="归一化小写 host（含端口若有），如 gitlab.example.com 或 gitlab.example.com:8443",
                        max_length=255,
                        unique=True,
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("github", "GitHub"),
                            ("gitlab", "GitLab"),
                            ("gitea", "Gitea"),
                            ("bitbucket", "Bitbucket"),
                        ],
                        default="gitlab",
                        max_length=20,
                    ),
                ),
                (
                    "encrypted_token",
                    models.TextField(help_text="Fernet 密文 access token，绝不存明文"),
                ),
                ("label", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Git 实例凭证",
                "verbose_name_plural": "Git 实例凭证",
                "db_table": "git_instance_credentials",
            },
        ),
    ]

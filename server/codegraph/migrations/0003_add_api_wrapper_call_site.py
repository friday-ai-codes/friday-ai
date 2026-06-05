"""initial implementation: 新建 ApiWrapper + ApiCallSite 表（per work item）。

ApiWrapper: 前端 ApiWrapper 函数（封装 LowLevelHelper 调用），含 JSDoc metadata。
ApiCallSite: ApiWrapper 调用点（通过 volar textDocument/references 反向追踪）。

注意：创建此 migration 后需手动执行：
    cd server && python manage.py migrate codegraph
"""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("codegraph", "0002_add_endpoint_metadata"),
        ("repositories", "0015_alter_repositorybranchindex_status_upgrading"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApiWrapper",
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
                    "file_path",
                    models.CharField(db_index=True, max_length=512),
                ),
                (
                    "function_symbol",
                    models.CharField(max_length=255),
                ),
                (
                    "http_method",
                    models.CharField(max_length=16),
                ),
                (
                    "url_path_raw",
                    models.CharField(max_length=512),
                ),
                (
                    "url_path_pattern",
                    models.CharField(db_index=True, max_length=512),
                ),
                (
                    "detected_via",
                    models.CharField(default="axios_anchor", max_length=64),
                ),
                (
                    "line_number",
                    models.IntegerField(default=0),
                ),
                (
                    "metadata",
                    models.JSONField(
                        blank=True,
                        default=None,
                        null=True,
                        verbose_name="JSDoc 元数据",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "repository",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="api_wrappers",
                        to="repositories.repository",
                    ),
                ),
            ],
            options={
                "verbose_name": "API Wrapper",
                "verbose_name_plural": "API Wrappers",
            },
        ),
        migrations.AddIndex(
            model_name="apiwrapper",
            index=models.Index(
                fields=["repository", "url_path_pattern"],
                name="codegraph_a_reposito_url_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="apiwrapper",
            index=models.Index(
                fields=["repository", "function_symbol"],
                name="codegraph_a_reposito_sym_idx",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="apiwrapper",
            unique_together={("repository", "file_path", "function_symbol")},
        ),
        migrations.CreateModel(
            name="ApiCallSite",
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
                    "caller_file",
                    models.CharField(db_index=True, max_length=512),
                ),
                (
                    "caller_function",
                    models.CharField(max_length=255),
                ),
                (
                    "line_number",
                    models.IntegerField(),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "api_wrapper",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="call_sites",
                        to="codegraph.apiwrapper",
                    ),
                ),
                (
                    "repository",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="api_call_sites",
                        to="repositories.repository",
                    ),
                ),
            ],
            options={
                "verbose_name": "API Call Site",
                "verbose_name_plural": "API Call Sites",
            },
        ),
        migrations.AddIndex(
            model_name="apicallsite",
            index=models.Index(
                fields=["repository", "caller_file"],
                name="codegraph_a_reposito_cfile_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="apicallsite",
            index=models.Index(
                fields=["api_wrapper"],
                name="codegraph_a_wrapper_idx",
            ),
        ),
    ]

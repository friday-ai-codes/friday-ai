"""implementation: 新建 CrossRepoApiCall 表（per work item）。

CrossRepoApiCall: ApiCallSite × Endpoint offline join 结果，含 match_confidence。
unique_together: (call_site, endpoint) 保证幂等。

注意：创建此 migration 后需手动执行：
    cd server && python manage.py migrate codegraph
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("codegraph", "0003_add_api_wrapper_call_site"),
    ]

    operations = [
        migrations.CreateModel(
            name="CrossRepoApiCall",
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
                    "match_confidence",
                    models.FloatField(
                        help_text="1.0=完全匹配 / 0.7=path-only / 0.4=部分匹配",
                    ),
                ),
                (
                    "matched_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "call_site",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cross_repo_calls",
                        to="codegraph.apicallsite",
                    ),
                ),
                (
                    "endpoint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cross_repo_callers",
                        to="codegraph.endpoint",
                    ),
                ),
            ],
            options={
                "verbose_name": "跨仓 API 调用",
                "verbose_name_plural": "跨仓 API 调用",
            },
        ),
        migrations.AddIndex(
            model_name="crossrepoapicall",
            index=models.Index(
                fields=["call_site"],
                name="crossrepo_call_site_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="crossrepoapicall",
            index=models.Index(
                fields=["endpoint"],
                name="crossrepo_endpoint_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="crossrepoapicall",
            index=models.Index(
                fields=["match_confidence"],
                name="crossrepo_confidence_idx",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="crossrepoapicall",
            unique_together={("call_site", "endpoint")},
        ),
    ]

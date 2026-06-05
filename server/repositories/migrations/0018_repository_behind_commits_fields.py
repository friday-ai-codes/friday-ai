"""Repository 新增 behind_commits + behind_commits_calculated_at 字段（implementation contract）。"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repositories", "0017_repository_remote_head_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="repository",
            name="behind_commits",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text="本地索引落后远端的 commit 数，null 表示尚未计算",
            ),
        ),
        migrations.AddField(
            model_name="repository",
            name="behind_commits_calculated_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="behind_commits 最近一次计算时间",
            ),
        ),
    ]

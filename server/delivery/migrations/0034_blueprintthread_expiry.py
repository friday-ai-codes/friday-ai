"""澄清线程提醒计数与显式到期时刻（Phase 117，WAIT-01）。

纯追加两列、均有默认值 ⇒ 已有行零回填风险（`reminder_count` 默认 0 等价于「还没提醒过」，
`expired_at` 默认 null 等价于「未到期」，与改动前行为逐字一致）。
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0033_blueprintthread_last_reminded_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="blueprintthread",
            name="reminder_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="blueprintthread",
            name="expired_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

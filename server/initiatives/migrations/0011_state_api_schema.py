"""扩展 ProjectStateApi 为完整 API schema（#5）：接口说明 + 请求/返回字段结构。"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("initiatives", "0010_repo_association"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectstateapi",
            name="description",
            field=models.TextField(blank=True, default="", verbose_name="接口说明"),
        ),
        migrations.AddField(
            model_name="projectstateapi",
            name="request_fields",
            field=models.JSONField(blank=True, default=list, verbose_name="请求字段"),
        ),
        migrations.AddField(
            model_name="projectstateapi",
            name="response_fields",
            field=models.JSONField(blank=True, default=list, verbose_name="返回字段"),
        ),
    ]

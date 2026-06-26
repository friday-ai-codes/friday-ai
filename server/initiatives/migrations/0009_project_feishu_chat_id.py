# Generated for Phase 87 (87-04): Project.feishu_chat_id 复用项目群字段。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("initiatives", "0008_project_branch"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="feishu_chat_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="项目复用群 chat_id；为空时由 resolve_or_create_group 建群后回写",
                max_length=128,
                verbose_name="飞书项目群 ID",
            ),
        ),
    ]

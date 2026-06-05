from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("repositories", "0019_add_index_stage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="repository",
            name="index_status",
            field=models.CharField(
                choices=[
                    ("not_indexed", "未索引"),
                    ("indexing", "索引中"),
                    ("indexed", "已索引"),
                    ("failed", "索引失败"),
                    ("cancelled", "已停止"),
                ],
                default="not_indexed",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="indexhistory",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "等待中"),
                    ("running", "运行中"),
                    ("completed", "已完成"),
                    ("failed", "失败"),
                    ("cancelled", "已停止"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]

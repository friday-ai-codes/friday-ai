# TRIG-02 / D-02：从 Workflow.trigger_type 的 choices 收窄移除僵尸枚举 schedule。
# TextChoices 不在 DB 层生成约束，AlterField 仅更新 Django 层元数据，存量
# trigger_type='schedule' 行不会因此报错（Pitfall 3：禁止删行/加 CHECK 约束）。
# 附带可选数据迁移：将存量 schedule 行归一为 manual（仅 update，可逆为 noop）。

from django.db import migrations, models


def forwards(apps, schema_editor):
    """将存量 trigger_type='schedule' 的工作流归一为 'manual'（不删行）。"""
    Workflow = apps.get_model("workflows", "Workflow")
    Workflow.objects.filter(trigger_type="schedule").update(trigger_type="manual")


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0026_rename_fetch_project_info_nodes"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflow",
            name="trigger_type",
            field=models.CharField(
                choices=[
                    ("manual", "手动触发"),
                    ("webhook", "Webhook 触发"),
                    ("event", "事件触发"),
                ],
                default="manual",
                max_length=20,
                verbose_name="触发类型",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

from django.db import migrations

RENAME_MAP = {
    "approval": "human_approval",
    "wait_feishu": "wait_feishu_field",
}


def rename_node_types(apps, schema_editor):
    WorkflowNode = apps.get_model("workflows", "WorkflowNode")
    for old_name, new_name in RENAME_MAP.items():
        WorkflowNode.objects.filter(node_type=old_name).update(node_type=new_name)


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0009_remove_deprecated_nodes"),
    ]

    operations = [
        migrations.RunPython(rename_node_types, migrations.RunPython.noop),
    ]

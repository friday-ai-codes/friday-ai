from django.db import migrations

DEPRECATED_NODE_TYPES = [
    "generate_plan",
    "revise_plan",
    "analyze_requirements",
    "analyze_bug",
    "technical_plan",
]


def remove_deprecated_nodes(apps, schema_editor):
    WorkflowNode = apps.get_model("workflows", "WorkflowNode")
    WorkflowNode.objects.filter(node_type__in=DEPRECATED_NODE_TYPES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0008_alter_workflownode_node_type"),
    ]

    operations = [
        migrations.RunPython(remove_deprecated_nodes, migrations.RunPython.noop),
    ]

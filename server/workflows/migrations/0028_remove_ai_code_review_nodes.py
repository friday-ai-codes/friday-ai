"""移除已废弃的 ai_code_review 节点（点9：删除 AI 代码审查环节）。

已存工作流中残留的该类型节点在节点类删除后会导致保存/执行失败，故删除这些
WorkflowNode 行（关联 WorkflowEdge 经 on_delete=CASCADE 自动级联清理）。
"""

from django.db import migrations

DEPRECATED_NODE_TYPES = [
    "ai_code_review",
]


def remove_ai_code_review_nodes(apps, schema_editor):
    WorkflowNode = apps.get_model("workflows", "WorkflowNode")
    WorkflowNode.objects.filter(node_type__in=DEPRECATED_NODE_TYPES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0027_remove_schedule_trigger_type"),
    ]

    operations = [
        migrations.RunPython(remove_ai_code_review_nodes, migrations.RunPython.noop),
    ]

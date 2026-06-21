"""合并 ai_plan_approval → human_approval(mode=plan_feishu)（C2）。

存量工作流中的 ``ai_plan_approval`` 节点在节点类删除后会导致保存/执行失败，故将其
``node_type`` 改名为 ``human_approval`` 并注入 ``config.mode = "plan_feishu"``（保留
既有 ``chat_id`` 等配置），使其行为与原方案审批一致（方案文档 + 飞书卡片审批）。

参考 ``0010_rename_node_types.py`` / ``0011_migrate_technical_plan_to_plan_generation.py``
的 rename + config 注入范式。本迁移按设计不可逆（reverse 为 noop）。
"""

from django.db import migrations


def merge_plan_approval(apps, schema_editor):
    """ai_plan_approval → human_approval，注入 mode=plan_feishu（保留既有 config）。"""
    WorkflowNode = apps.get_model("workflows", "WorkflowNode")
    nodes = WorkflowNode.objects.filter(node_type="ai_plan_approval")
    count = 0
    for node in nodes:
        config = dict(node.config or {})
        config["mode"] = "plan_feishu"
        node.node_type = "human_approval"
        node.config = config
        node.save(update_fields=["node_type", "config"])
        count += 1

    if count > 0:
        print(f"\n  Merged {count} ai_plan_approval node(s) into human_approval(mode=plan_feishu)")


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0028_remove_ai_code_review_nodes"),
    ]

    operations = [
        migrations.RunPython(merge_plan_approval, migrations.RunPython.noop),
    ]

"""数据迁移：幽灵节点 fetch_project_info → fetch_space_info 对齐（D-03）。

历史上前端曾允许保存 node_type='fetch_project_info' 的节点，但后端 registry
从无此类型，执行时会退化为未知节点 / fallback baseNode。前端在 19-ssot 阶段
收敛为真实节点 fetch_space_info 后，存量工作流仍残留旧字符串。本迁移把存量行
重写为真实类型，使老工作流打开后能正确解析。

幂等：filter+update 命中 0 行时无副作用，可重复运行。
仅改 node_type 字符串字段，不触碰 edge/handle/config。
reverse 为 noop，避免误回滚把已对齐的数据破坏。
"""

from django.db import migrations


def rename_ghost_nodes(apps, schema_editor):
    WorkflowNode = apps.get_model("workflows", "WorkflowNode")
    updated = WorkflowNode.objects.filter(node_type="fetch_project_info").update(
        node_type="fetch_space_info"
    )
    if updated > 0:
        print(f"\n  Renamed {updated} fetch_project_info node(s) to fetch_space_info")


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0025_alert_rules"),
    ]

    operations = [
        migrations.RunPython(rename_ghost_nodes, migrations.RunPython.noop),
    ]

# 飞书触发器重构：每工作流专属 webhook 端点。
# WorkflowTrigger 新增 node_id（同步稳定键）与 token（端点路由标识 + 鉴权凭证）。
# token 为 unique，存量行需先回填唯一值再加约束（单 default 会令所有存量行同值而冲突），
# 故走「可空加列 → RunPython 逐行回填唯一 token → AlterField 收紧为非空 unique」三步。
# event_type 放宽为可空（新版按 token 路由，不再依赖事件类型匹配）。

import workflows.models.trigger
from django.db import migrations, models


def fill_tokens(apps, schema_editor):
    """为存量 WorkflowTrigger 行逐个回填唯一 token。"""
    WorkflowTrigger = apps.get_model("workflows", "WorkflowTrigger")
    for trigger in WorkflowTrigger.objects.filter(token__isnull=True).iterator():
        # 极小概率撞车时重试，确保唯一
        while True:
            candidate = workflows.models.trigger.generate_trigger_token()
            if not WorkflowTrigger.objects.filter(token=candidate).exists():
                break
        trigger.token = candidate
        trigger.save(update_fields=["token"])


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0029_merge_plan_approval_into_human_approval"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowtrigger",
            name="node_id",
            field=models.UUIDField(
                blank=True,
                db_index=True,
                help_text="关联的 feishu_event_trigger 画布节点 ID",
                null=True,
                verbose_name="触发节点 ID",
            ),
        ),
        # Step 1：可空加列（存量行先得 NULL，避免单 default 触发唯一冲突）。
        # 注意：此处「不」加 db_index，因 Step 3 收紧为 unique 时会自建唯一索引；
        # 若 Step 1 先建普通索引（含 Postgres 的 varchar_pattern_ops `*_like` 索引），
        # Step 3 再叠加 unique 会重复创建同名 `*_like` 索引而报
        # `relation "..._like" already exists`。
        migrations.AddField(
            model_name="workflowtrigger",
            name="token",
            field=models.CharField(
                max_length=64,
                null=True,
                verbose_name="端点 Token",
            ),
        ),
        # Step 2：逐行回填唯一 token
        migrations.RunPython(fill_tokens, migrations.RunPython.noop),
        # Step 3：收紧为非空 unique（unique 已隐式建索引，无需再加 db_index），
        # 并挂上 callable 默认值供新行使用。
        migrations.AlterField(
            model_name="workflowtrigger",
            name="token",
            field=models.CharField(
                default=workflows.models.trigger.generate_trigger_token,
                help_text="飞书 Webhook 专属端点标识，命中即直接触发对应工作流",
                max_length=64,
                unique=True,
                verbose_name="端点 Token",
            ),
        ),
        migrations.AlterField(
            model_name="workflowtrigger",
            name="event_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("WorkitemCreateEvent", "工作项创建"),
                    ("WorkitemStatusEvent", "状态变更"),
                    ("WorkitemCommentEvent", "评论事件"),
                    ("WorkitemUpdateEvent", "字段更新"),
                    ("WorkFlowNodeStatusEvent", "节点流转"),
                    ("WorkitemFinishEvent", "工作项完成"),
                    ("WorkitemDeleteEvent", "工作项删除"),
                    ("WorkitemAbortedEvent", "工作项终止"),
                    ("WorkitemRestoreEvent", "工作项恢复"),
                    ("TaskCreateEvent", "任务创建"),
                    ("TaskStatusEvent", "任务状态变更"),
                    ("TaskUpdateEvent", "任务修改"),
                ],
                default="",
                help_text="（旧版）监听的飞书 Webhook 事件类型；新版按 token 路由，不再依赖此字段",
                max_length=50,
                verbose_name="事件类型",
            ),
        ),
    ]

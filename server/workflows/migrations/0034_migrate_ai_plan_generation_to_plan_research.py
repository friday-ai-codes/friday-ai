"""Data migration: 把存量 ai_plan_generation 节点迁到 ai_plan_research。

背景：Chassis v2 物理删除了 ``workflows.nodes.ai.plan_generation``（现行 SSOT 见
``tests/workflows/test_node_schema.py`` 断言 registry 查不到该类型），但迁移链只有
0007 / 0011 把 ai_agent / ai_technical_plan **迁入** ai_plan_generation，没有任何
迁移把它迁出。结果：升级后的存量部署里 node_type='ai_plan_generation' 的行成为孤儿，
执行时命中 ``scheduler.py`` 的 ``raise ValueError(f"未知的节点类型: ...")`` 硬失败
（不是降级），违反「已有部署升级后行为不得回退」约束。

配置迁移策略（两个 schema 只部分重叠）：
- 交集键（model / chat_id / use_custom_api / api_base_url / api_key / include_repos）逐字保留；
- user_prompt → requirement_text（旧节点的 user_prompt 承载需求文本；仅在目标为空时写入，不覆盖）；
- 目标 schema 不存在的键（system_prompt / exclude_repos / max_iterations / enabled_tools 等）
  归档到 ``_legacy_ai_plan_generation`` 而非丢弃——config 是 JSONField 且
  ``BaseNode.validate_config`` 用 jsonschema 校验、未设 additionalProperties=false，
  额外键不会导致校验失败，运维可据此人工恢复。

不可逆（与 0011 同例）：反向留 noop。NodeExecution 历史记录保持原样不动。
"""

from django.db import migrations

# ai_plan_research.config_schema 顶层键（含 AIAgentBaseNode 继承部分）中，
# 与旧 ai_plan_generation 配置重叠、可逐字保留的键。
_CARRY_OVER_KEYS = (
    "model",
    "chat_id",
    "use_custom_api",
    "api_base_url",
    "api_key",
    "api_format",
    "provider_type",
    "include_repos",
)

_LEGACY_ARCHIVE_KEY = "_legacy_ai_plan_generation"


def _convert_config(old: dict) -> dict:
    """把旧 ai_plan_generation config 转成 ai_plan_research config。"""
    old = old or {}
    new: dict = {key: old[key] for key in _CARRY_OVER_KEYS if key in old}

    # 旧节点的 user_prompt 即需求文本；不覆盖已有 requirement_text。
    requirement = old.get("requirement_text") or old.get("user_prompt") or ""
    if requirement:
        new["requirement_text"] = requirement

    if "work_item_id" in old:
        new["work_item_id"] = old["work_item_id"]

    # 目标 schema 无对应位置的键归档留痕，避免静默销毁运维数据。
    dropped = {
        key: value
        for key, value in old.items()
        if key not in new and key not in ("user_prompt", _LEGACY_ARCHIVE_KEY)
    }
    if dropped:
        new[_LEGACY_ARCHIVE_KEY] = dropped

    return new


def migrate_plan_generation_nodes(apps, schema_editor):
    """ai_plan_generation → ai_plan_research（含 config 转换）。"""
    WorkflowNode = apps.get_model("workflows", "WorkflowNode")
    nodes = WorkflowNode.objects.filter(node_type="ai_plan_generation")

    count = 0
    for node in nodes:
        node.node_type = "ai_plan_research"
        node.config = _convert_config(node.config)
        node.save(update_fields=["node_type", "config"])
        count += 1

    if count > 0:
        print(f"\n  Migrated {count} ai_plan_generation node(s) to ai_plan_research")


class Migration(migrations.Migration):

    dependencies = [
        ("workflows", "0033_workflow_output_schema"),
    ]

    operations = [
        migrations.RunPython(
            migrate_plan_generation_nodes,
            migrations.RunPython.noop,
        ),
    ]

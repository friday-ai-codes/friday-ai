"""resync ai_node.plan_generation.system —— 澄清出口改造。

方案生成节点不再使用 ask_user_question 就地提问，改为：信息不足时 LLM 输出
need_clarification JSON，节点经 need_clarification 出口分流到下游人工节点。
本迁移把 DB 中 active 的 system prompt body resync 到最新 Python 字面量
（`_PLAN_GENERATION_BASE_PROMPT`），避免 DB hit 路径仍诱导 LLM 调用已移除的
ask_user_question 工具。

复用 0006 的「幂等 upsert + body drift 检测」模式：active body 与最新字面量
字节级一致则 skip，否则 append PromptVersion 并切换 active。
"""
from __future__ import annotations

from typing import Any

from django.db import migrations
from django.db.models import Max

_SLUG = "ai_node.plan_generation.system"
_NOTE = "Resync plan_generation: ask_user_question 移除 → need_clarification 出口分流"


def forwards(apps: Any, schema_editor: Any) -> None:
    # Chassis v2 · P2：ai_plan_generation 节点已删除；其 resync 成为 no-op。
    try:
        from workflows.nodes.ai.plan_generation import (  # type: ignore[import-not-found]
            _PLAN_GENERATION_BASE_PROMPT,
        )
    except ImportError:
        return

    Prompt = apps.get_model("prompts", "Prompt")
    PromptVersion = apps.get_model("prompts", "PromptVersion")

    body = _PLAN_GENERATION_BASE_PROMPT
    try:
        prompt = Prompt.objects.get(slug=_SLUG, scope="system")
    except Prompt.DoesNotExist:
        return

    active = prompt.active_version
    if active is not None and active.body == body:
        return

    max_v = prompt.versions.aggregate(Max("version"))["version__max"] or 0
    new_version = PromptVersion.objects.create(
        prompt=prompt,
        version=max_v + 1,
        body=body,
        variables_schema={},
        change_note=_NOTE,
    )
    prompt.active_version = new_version
    prompt.save(update_fields=["active_version", "updated_at"])


def reverse(apps: Any, schema_editor: Any) -> None:
    """no-op：仅 append + 切 active 指针；回滚请手动选择历史版本。"""
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("prompts", "0008_resync_chat_strategy_route_first"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]

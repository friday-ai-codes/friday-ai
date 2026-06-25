"""implementation: 三 slug resync —— 注入「准确性优先原则」。

涉及 slug：

- ``chat.system.developer`` —— ROLE_PROMPTS["developer"] 末尾追加准确性原则段
- ``chat.strategy.default`` —— _STRATEGY_DEFAULT 末尾追加「必读」段
- ``chat.coding_guidance`` —— _CODING_GUIDANCE 末尾追加「编码请求的前置约束」段

复用 0004 / 0005 的「幂等 upsert + body drift 检测」模式：active version body
与最新 Python 字面量字节级一致则 skip，否则 append PromptVersion 并切换 active。

为什么需要：``_build_system_prompt`` 优先 ``render_prompt()`` 读 DB，fallback
才退回 Python 字面量。若 DB body 仍是 0002 seed 时的旧文案，即便 fallback 已写入
新「准确性优先」段，DB hit 路径仍诱导 LLM 跳过 ``analyze_repository_relevance`` /
``ask_clarification``，与 work item 编排层硬约束不一致。
"""
from __future__ import annotations

from typing import Any, Callable

from django.db import migrations
from django.db.models import Max


def _resync_one(apps: Any, slug: str, get_body: Callable[[], str], note: str) -> None:
    """单 slug 幂等 upsert：active body 与最新字面量一致 → skip；否则 append。

    与 0004 / 0005 的 forwards 主体行为一致；本函数把 8 行核心逻辑抽出，
    避免在同一 migration 内手抄三次。
    """
    Prompt = apps.get_model("prompts", "Prompt")
    PromptVersion = apps.get_model("prompts", "PromptVersion")

    body = get_body()
    try:
        prompt = Prompt.objects.get(slug=slug, scope="system")
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
        change_note=note,
    )
    prompt.active_version = new_version
    prompt.save(update_fields=["active_version", "updated_at"])


def _developer_body() -> str:
    from chat.conversation_service import ROLE_PROMPTS

    return ROLE_PROMPTS["developer"]


def _strategy_default_body() -> str:
    from chat.conversation_service import _STRATEGY_DEFAULT

    return _STRATEGY_DEFAULT


def _coding_guidance_body() -> str:
    from chat.conversation_service import _CODING_GUIDANCE

    return _CODING_GUIDANCE


_RESYNC_NOTE = "Resync after work item (coding-plan workflow 准确性优先原则注入)"


def forwards(apps: Any, schema_editor: Any) -> None:
    _resync_one(apps, "chat.system.developer", _developer_body, _RESYNC_NOTE)
    _resync_one(apps, "chat.strategy.default", _strategy_default_body, _RESYNC_NOTE)
    _resync_one(apps, "chat.coding_guidance", _coding_guidance_body, _RESYNC_NOTE)


def reverse(apps: Any, schema_editor: Any) -> None:
    """与 0004 / 0005 一致：no-op。

    本迁移只是 append PromptVersion + 切换 active 指针，回滚时把 active 指回
    (max_v - 1) 版本即可恢复上一版 body。但若操作员真要回滚，更妥当的做法
    是手动选择历史版本，而不是自动猜。
    """
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("prompts", "0005_resync_chat_strategy_deep_analysis"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]

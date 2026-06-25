"""Resync chat.strategy.default with route-first code understanding guidance.

为什么需要：``_build_system_prompt`` 优先从 Prompt Center 读取系统默认 prompt，
fallback 常量只在 DB miss / disabled 时生效。若只改 ``_STRATEGY_DEFAULT``，
已有部署的 ``chat.strategy.default`` active version 仍会是旧文案，模型仍可能
在“某功能是怎么实现的”这类代码理解问答里先本地检索当前仓库。
"""
from __future__ import annotations

from typing import Any

from django.db import migrations
from django.db.models import Max

SEED_SLUG = "chat.strategy.default"
RESYNC_NOTE = "route-first code understanding guidance resync"


def _strategy_default_body() -> str:
    from chat.conversation_service import _STRATEGY_DEFAULT

    return _STRATEGY_DEFAULT


def forwards(apps: Any, schema_editor: Any) -> None:
    Prompt = apps.get_model("prompts", "Prompt")
    PromptVersion = apps.get_model("prompts", "PromptVersion")

    body = _strategy_default_body()
    try:
        prompt = Prompt.objects.get(slug=SEED_SLUG, scope="system")
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
        change_note=RESYNC_NOTE,
    )
    prompt.active_version = new_version
    prompt.save(update_fields=["active_version", "updated_at"])


def reverse(apps: Any, schema_editor: Any) -> None:
    """No-op: Prompt Center keeps version history; operators can select old versions."""
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("prompts", "0007_seed_repo_summary_tree"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]

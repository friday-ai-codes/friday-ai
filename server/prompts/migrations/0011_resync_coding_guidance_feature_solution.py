"""Resync 已部署实例中停留在旧 seed 的 chat builtin prompts。

``render_prompt`` 命中 DB 后不会使用 Python fallback，因此只更新字面量无法让
既有部署获得 ``start_feature_solution`` 指引。本迁移把 active body 字节级拉齐，
同时保留历史版本供运维手动回滚。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db import migrations
from django.db.models import Max


def _resync_one(
    apps: Any,
    slug: str,
    get_body: Callable[[], str],
    change_note: str,
) -> None:
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
        change_note=change_note,
    )
    prompt.active_version = new_version
    prompt.save(update_fields=["active_version", "updated_at"])


def _coding_guidance_body() -> str:
    from chat.conversation_service import _CODING_GUIDANCE

    return _CODING_GUIDANCE


def _strategy_default_body() -> str:
    from chat.conversation_service import _STRATEGY_DEFAULT

    return _STRATEGY_DEFAULT


def forwards(apps: Any, schema_editor: Any) -> None:
    _resync_one(
        apps,
        "chat.coding_guidance",
        _coding_guidance_body,
        "Resync coding_guidance: 注入 start_feature_solution 成批技术方案指引",
    )
    _resync_one(
        apps,
        "chat.strategy.default",
        _strategy_default_body,
        "Resync strategy.default: 字节级对齐当前 Python 策略",
    )


def reverse(apps: Any, schema_editor: Any) -> None:
    """仅 append 并切换 active 指针；回滚请手动选择历史版本。"""
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("prompts", "0010_rename_project_to_space"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]

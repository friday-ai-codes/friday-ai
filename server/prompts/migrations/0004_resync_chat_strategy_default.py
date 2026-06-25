"""Resync chat.strategy.default 默认策略 prompt。

`_STRATEGY_DEFAULT` 常量在去除"策略二 - 深度分析"段后字节级变更。
0002 seed migration 仅在首次创建条目时写入 body，无法回放此次更新——
本迁移复用 0002 / 0003 的幂等 upsert + body drift detection 模式，
在 active version 与最新常量不一致时创建新 PromptVersion 并切换为 active。

为什么需要：`_build_system_prompt` 优先 `render_prompt()` 读 DB，
fallback 才回退到 Python 字面量。若 DB body 仍是旧的双策略文本，
LLM 仍会被诱导调用 deep_analysis（即便工具列表里已经把它闸掉）。
"""
from __future__ import annotations

from typing import Any

from django.db import migrations
from django.db.models import Max

SEED_SLUG = "chat.strategy.default"


def _load_body() -> str:
    """从 chat.conversation_service 拿当前的 _STRATEGY_DEFAULT 字面量。

    跨 app import 在 RunPython 回调里是安全的（与 0002 一致）。
    """
    from chat.conversation_service import _STRATEGY_DEFAULT

    return _STRATEGY_DEFAULT


def forwards(apps: Any, schema_editor: Any) -> None:
    Prompt = apps.get_model("prompts", "Prompt")
    PromptVersion = apps.get_model("prompts", "PromptVersion")

    body = _load_body()
    try:
        prompt = Prompt.objects.get(slug=SEED_SLUG, scope="system")
    except Prompt.DoesNotExist:
        # 罕见：0002 未跑过。这里不重复 0002 的创建逻辑，留给 0002 处理。
        return

    active = prompt.active_version
    if active is not None and active.body == body:
        return  # 幂等 skip

    max_v = prompt.versions.aggregate(Max("version"))["version__max"] or 0
    new_version = PromptVersion.objects.create(
        prompt=prompt,
        version=max_v + 1,
        body=body,
        variables_schema={},
        change_note=(
            f"Resync after dropping strategy 2 from _STRATEGY_DEFAULT "
            f"(body drift from v{max_v})"
        ),
    )
    prompt.active_version = new_version
    prompt.save(update_fields=["active_version", "updated_at"])


def reverse(apps: Any, schema_editor: Any) -> None:
    """无安全的逆操作：旧 body 已不再保留为 Python 字面量。

    本迁移只是 append PromptVersion + 切换 active 指针，回滚时把 active
    指回 (max_v - 1) 版本即可恢复上一版 body。但若操作员真要回滚，
    更妥当的做法是手动选择历史版本，而不是自动猜。这里 no-op 保守处理。
    """
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("prompts", "0003_seed_repo_summary"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]

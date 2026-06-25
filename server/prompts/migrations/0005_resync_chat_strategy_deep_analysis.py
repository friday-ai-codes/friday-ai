"""Resync chat.strategy.deep_analysis 深度分析策略 prompt。

`_STRATEGY_DEEP_ANALYSIS` 常量在 Phase P15（"deep_analysis 重塑为派单器"）
字节级变更 —— 把「每轮只能调一次 deep_analysis」的串行语义升级为
「必须并行 dispatch N 个 Claude Code 容器、RAG 仅用来定位仓库」的派单器语义。

0002 seed migration 仅在首次创建条目时写入 body，无法回放此次更新 ——
本迁移复用 0004 的幂等 upsert + body drift detection 模式，在 active version
与最新常量不一致时创建新 PromptVersion 并切换为 active。

为什么需要：`_build_system_prompt` 优先 `render_prompt()` 读 DB，
fallback 才回退到 Python 字面量。若 DB body 仍是旧版串行指令，
即使用户开启「深度分析」开关，LLM 也会按旧 prompt「只调一次 deep_analysis」
行事，而不会按新 prompt 对多个相关仓库并行 dispatch。
"""
from __future__ import annotations

from typing import Any

from django.db import migrations
from django.db.models import Max

SEED_SLUG = "chat.strategy.deep_analysis"


def _load_body() -> str:
    """从 chat.conversation_service 拿当前的 _STRATEGY_DEEP_ANALYSIS 字面量。

    跨 app import 在 RunPython 回调里是安全的（与 0002 / 0004 一致）。
    """
    from chat.conversation_service import _STRATEGY_DEEP_ANALYSIS

    return _STRATEGY_DEEP_ANALYSIS


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
            f"Resync after reshaping _STRATEGY_DEEP_ANALYSIS to dispatcher "
            f"semantics in Phase P15 (body drift from v{max_v})"
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
        ("prompts", "0004_resync_chat_strategy_default"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]

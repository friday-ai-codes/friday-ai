"""implementation seed: 12 个系统级内置 Prompt 灌入。

决策依据（work-item.md contract）：
- 通过 Python import 原常量拿字面量，保证字节级单一来源
- 幂等 upsert：已存在且 body 相等 → skip；不同 → append_version
- reverse 限定 is_builtin=True AND slug IN SEED_SLUGS 防误删用户项目级覆盖
"""
from __future__ import annotations

from typing import Any

from django.db import migrations
from django.db.models import Max

SEED_SLUGS_ORDER: list[str] = [
    "chat.system.developer",
    "chat.system.pm",
    "chat.system.designer",
    "chat.system.qa",
    "chat.system.general",
    "chat.strategy.default",
    "chat.strategy.deep_analysis",
    "chat.coding_guidance",
    "aux.title_generation",
    "ai_node.variable_extractor.template",
    "ai_node.code_review.system",
    "ai_node.plan_generation.system",
]


def _load_seed_data() -> list[tuple[str, str, str, str]]:
    """(slug, category, title, body) — 跨 app 顶层 import 常量。

    Django RunPython 回调允许普通 Python import（非 apps.get_model）。
    """
    from chat.conversation_service import (
        _CODING_GUIDANCE,
        _STRATEGY_DEEP_ANALYSIS,
        _STRATEGY_DEFAULT,
        ROLE_PROMPTS,
    )
    from chat.title_service import TITLE_PROMPT
    from workflows.nodes.ai.code_review import REVIEW_SYSTEM_PROMPT
    from workflows.nodes.ai.variable_extractor import EXTRACTION_PROMPT_TEMPLATE

    # Chassis v2 · P2：ai_plan_generation 节点已删除（编排统一走 ai_plan_research +
    # ProcessEngine）；其 seed prompt 条目随之废弃（import 不可用时跳过该条）。
    try:
        from workflows.nodes.ai.plan_generation import (  # type: ignore[import-not-found]
            _PLAN_GENERATION_BASE_PROMPT,
        )
    except ImportError:
        _PLAN_GENERATION_BASE_PROMPT = ""

    return [
        ("chat.system.developer", "chat_agent", "Chat Agent - 开发者角色", ROLE_PROMPTS["developer"]),
        ("chat.system.pm", "chat_agent", "Chat Agent - PM 角色", ROLE_PROMPTS["pm"]),
        ("chat.system.designer", "chat_agent", "Chat Agent - 设计师角色", ROLE_PROMPTS["designer"]),
        ("chat.system.qa", "chat_agent", "Chat Agent - QA 角色", ROLE_PROMPTS["qa"]),
        ("chat.system.general", "chat_agent", "Chat Agent - 通用角色", ROLE_PROMPTS["general"]),
        ("chat.strategy.default", "chat_agent", "Chat Strategy - 默认双策略", _STRATEGY_DEFAULT),
        ("chat.strategy.deep_analysis", "chat_agent", "Chat Strategy - 深度分析", _STRATEGY_DEEP_ANALYSIS),
        ("chat.coding_guidance", "chat_agent", "Chat 编码指引", _CODING_GUIDANCE),
        ("aux.title_generation", "aux_model", "标题生成", TITLE_PROMPT),
        ("ai_node.variable_extractor.template", "ai_node", "AI 节点 - 变量提取", EXTRACTION_PROMPT_TEMPLATE),
        ("ai_node.code_review.system", "ai_node", "AI 节点 - 代码审查", REVIEW_SYSTEM_PROMPT),
        *(
            [("ai_node.plan_generation.system", "ai_node", "AI 节点 - 方案生成", _PLAN_GENERATION_BASE_PROMPT)]
            if _PLAN_GENERATION_BASE_PROMPT
            else []
        ),
    ]


def forwards(apps: Any, schema_editor: Any) -> None:
    """Seed 12 个系统级内置 Prompt slug（幂等 upsert + append_version on drift）。"""
    Prompt = apps.get_model("prompts", "Prompt")
    PromptVersion = apps.get_model("prompts", "PromptVersion")

    seed_data = _load_seed_data()

    for slug, category, title, body in seed_data:
        prompt, created = Prompt.objects.get_or_create(
            slug=slug,
            scope="system",
            project=None,
            defaults={
                "category": category,
                "title": title,
                "description": "系统内置默认 Prompt（implementation seed）",
                "is_builtin": True,
            },
        )

        if created:
            version = PromptVersion.objects.create(
                prompt=prompt,
                version=1,
                body=body,
                variables_schema={},
                change_note="implementation initial seed",
            )
            prompt.active_version = version
            prompt.save(update_fields=["active_version", "updated_at"])
        else:
            active = prompt.active_version
            if active is not None and active.body == body:
                continue  # 幂等 skip（字节级相等）
            max_v = prompt.versions.aggregate(Max("version"))["version__max"] or 0
            new_version = PromptVersion.objects.create(
                prompt=prompt,
                version=max_v + 1,
                body=body,
                variables_schema={},
                change_note=f"implementation seed sync (body drift from v{max_v})",
            )
            prompt.active_version = new_version
            prompt.save(update_fields=["active_version", "updated_at"])


def reverse(apps: Any, schema_editor: Any) -> None:
    """回滚：限定 is_builtin=True AND slug IN SEED_SLUGS 的系统级条目。

    不删用户创建的项目级覆盖（scope=project）与用户手动创建的同名系统级（is_builtin=False）。
    """
    Prompt = apps.get_model("prompts", "Prompt")
    Prompt.objects.filter(
        slug__in=SEED_SLUGS_ORDER,
        scope="system",
        is_builtin=True,
    ).delete()  # CASCADE 删除 PromptVersion


class Migration(migrations.Migration):
    dependencies = [
        ("prompts", "0001_initial"),
        # 跨 app import 安全：确保 chat/workflows app 表结构稳定
        ("chat", "0008_codingsession_conflict_check_result_and_more"),
        ("workflows", "0022_remove_cancelled_status"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse),
    ]

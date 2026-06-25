"""5 调用点 × 3 态三态回退矩阵（work item 逐条验证）。"""
from __future__ import annotations

from typing import Any

import pytest

from chat.conversation_service import (
    ROLE_PROMPTS,
)
from chat.title_service import TITLE_PROMPT
from prompts.keys import PromptSlugs
from prompts.models import Prompt, PromptScope, PromptVersion
from prompts.services import render_prompt
from workflows.nodes.ai.code_review import REVIEW_SYSTEM_PROMPT
from workflows.nodes.ai.plan_generation import _PLAN_GENERATION_BASE_PROMPT
from workflows.nodes.ai.variable_extractor import EXTRACTION_PROMPT_TEMPLATE

# (slug, fallback, sample_variables, category, title) — 5 个关键调用点
CALL_SITES: list[tuple[str, str, dict[str, str], str, str]] = [
    (
        PromptSlugs.AUX_TITLE_GENERATION,
        TITLE_PROMPT,
        {"user_message": "hi"},
        "aux_model",
        "标题生成",
    ),
    (
        PromptSlugs.AI_NODE_VARIABLE_EXTRACTOR,
        EXTRACTION_PROMPT_TEMPLATE,
        {
            "variable_definitions": "- k (K): d",
            "input_text": "t",
            "additional_prompt": "",
        },
        "ai_node",
        "AI 节点 - 变量提取",
    ),
    (
        PromptSlugs.AI_NODE_CODE_REVIEW,
        REVIEW_SYSTEM_PROMPT,
        {},
        "ai_node",
        "AI 节点 - 代码审查",
    ),
    (
        PromptSlugs.AI_NODE_PLAN_GENERATION,
        _PLAN_GENERATION_BASE_PROMPT,
        {"schema_json": "S"},
        "ai_node",
        "AI 节点 - 方案生成",
    ),
    (
        PromptSlugs.CHAT_SYSTEM_DEVELOPER,
        ROLE_PROMPTS["developer"],
        {},
        "chat_agent",
        "Chat Agent - 开发者角色",
    ),
]


def _ensure_seed(
    slug: str, fallback: str, category: str, title: str
) -> None:
    """确保指定 slug 的 seed 存在（同步版，供 sync fixture）。"""
    if not Prompt.objects.filter(slug=slug, scope=PromptScope.SYSTEM).exists():
        prompt = Prompt.objects.create(
            slug=slug,
            scope=PromptScope.SYSTEM,
            space=None,
            category=category,
            title=title,
            description="implementation test re-seed",
            is_builtin=True,
        )
        version = PromptVersion.objects.create(
            prompt=prompt,
            version=1,
            body=fallback,
            variables_schema={},
            change_note="test re-seed",
        )
        prompt.active_version = version
        prompt.save(update_fields=["active_version", "updated_at"])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug,fallback,variables,category,title",
    CALL_SITES,
    ids=[c[0] for c in CALL_SITES],
)
class TestFeatureFlagMatrix:

    @pytest.fixture(autouse=True)
    def _reseed_all(self, db: Any) -> None:
        """每个测试开始前确保所有 5 个测试 slug 的 seed 存在。"""
        for s, fb, _v, cat, tt in CALL_SITES:
            _ensure_seed(s, fb, cat, tt)

    async def test_db_hit_returns_rendered(
        self,
        slug: str,
        fallback: str,
        variables: dict[str, str],
        category: str,
        title: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DB 命中（seed 已提供）→ render_prompt 成功返回非空字符串。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        result = await render_prompt(
            slug, project_id=None, variables=variables, fallback=fallback
        )
        assert result  # 非空
        assert isinstance(result, str)

    async def test_db_empty_returns_fallback(
        self,
        slug: str,
        fallback: str,
        variables: dict[str, str],
        category: str,
        title: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DB 空 → 走 _render_fallback（regex 替换）→ 变量值被替换。"""
        monkeypatch.delenv("PROMPT_CENTER_DISABLED_KEYS", raising=False)
        await Prompt.objects.filter(slug=slug, scope=PromptScope.SYSTEM).adelete()
        result = await render_prompt(
            slug, project_id=None, variables=variables, fallback=fallback
        )
        assert result
        # 字节级等价：结果等于 fallback 的占位符替换
        expected = fallback
        for k, v in variables.items():
            expected = expected.replace("{{" + k + "}}", str(v))
        assert result == expected

    async def test_flag_disabled_returns_fallback(
        self,
        slug: str,
        fallback: str,
        variables: dict[str, str],
        category: str,
        title: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PROMPT_CENTER_DISABLED_KEYS 命中 → 走 _render_fallback。"""
        monkeypatch.setenv("PROMPT_CENTER_DISABLED_KEYS", slug)
        result = await render_prompt(
            slug, project_id=None, variables=variables, fallback=fallback
        )
        expected = fallback
        for k, v in variables.items():
            expected = expected.replace("{{" + k + "}}", str(v))
        assert result == expected

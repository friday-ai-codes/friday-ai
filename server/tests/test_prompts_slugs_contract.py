"""BUILTIN_SLUGS 契约测试 — 防 v18.1 G3 同型错误。

initial implementation 唯一不可 skip 的 Wave 测试：
- 验证 BUILTIN_SLUGS 从 PromptSlugs 类体派生
- 验证 slug 数量锁死（防漂移）
- 参数化遍历每个 slug，断言 render_prompt 能走 fallback 路径命中
"""

from __future__ import annotations

import pytest

from prompts.keys import BUILTIN_SLUGS, PromptSlugs
from prompts.models import Prompt
from prompts.services import render_prompt


class TestPromptSlugContract:
    """防 v18.1 G3 同型：BUILTIN_SLUGS 契约锁死（参考 server/agents/core/events.py ALL_EVENT_TYPES）。"""

    def test_builtin_slugs_derived_from_class_exactly(self) -> None:
        """BUILTIN_SLUGS 必须 == PromptSlugs 所有字符串类属性的值集合。"""
        expected = {
            v
            for k, v in vars(PromptSlugs).items()
            if not k.startswith("_") and isinstance(v, str)
        }
        assert BUILTIN_SLUGS == frozenset(expected)

    def test_builtin_slugs_exact_count_locked(self) -> None:
        """锁死 16 个 slug — 新增 slug 必须同时更新此断言。

        分类统计：Chat 8 (5 role + 2 strategy + 1 coding) + Aux 2 + AI Node 4
                  + Feishu 1 + Repo 1 = 16。Plan-01 原写 "=15" 系算术笔误
                  (5+2+1+2+4+1+1=16)，Task 4 执行时 Rule 1 自动修正。
        """
        assert len(BUILTIN_SLUGS) == 16, (
            f"BUILTIN_SLUGS count drift: got {len(BUILTIN_SLUGS)}, "
            "expected 16. 若确认新增，请同步更新此断言与 PLAN 文档。"
        )

    def test_every_slug_follows_naming_convention(self) -> None:
        """所有 slug 必须遵循 `{category}.{...}` 小写点分命名。"""
        for slug in BUILTIN_SLUGS:
            assert slug == slug.lower(), f"非小写 slug: {slug}"
            assert "." in slug, f"slug 缺少点分: {slug}"
            assert " " not in slug, f"slug 含空格: {slug}"

    @pytest.mark.parametrize("slug", sorted(BUILTIN_SLUGS))
    @pytest.mark.django_db(transaction=True)
    async def test_every_slug_renderable_via_fallback(self, slug: str) -> None:
        """所有 slug 必须走 fallback 路径可达（DB 先清空，锁死 fallback 链路）。

        这是防 G3 同型的核心契约：Registry 写入但调用点未读取的情况，
        通过遍历 BUILTIN_SLUGS + render_prompt(fallback="STUB") 必然返回 "STUB"。

        initial implementation 更新：0002_seed_system_defaults 现在会在测试 DB 中种下
        12 个系统 slug，若不先清空会走 DB body 渲染路径并触发
        PromptVariableMissingError（因新的 `{{user_message}}` 等占位符）。
        本测试专门验证 fallback **路径**可达性（不是 DB 路径），故先 adelete。
        """
        # 清空测试 DB 中该 slug 的种子记录，强制走 fallback 路径
        await Prompt.objects.filter(slug=slug).adelete()

        result = await render_prompt(
            slug=slug,
            project_id=None,
            variables={},
            fallback="STUB_FALLBACK",
        )
        assert result == "STUB_FALLBACK"

"""BUILTIN_SLUGS 契约测试 — 防 v18.1 G3 同型错误。
Phase 唯一不可 skip 的 Wave 测试：
- 验证 BUILTIN_SLUGS 从 PromptSlugs 类体派生
- 验证 slug 数量锁死（防漂移）
- 参数化遍历每个 slug，断言 render_prompt 能走 fallback 路径命中
"""
from __future__ import annotations
import pytest
from prompts.keys import BUILTIN_SLUGS, PromptSlugs
from prompts.services import render_prompt
class TestPromptSlugContract:
 """防 v18.1 G3 同型：BUILTIN_SLUGS 契约锁死（参考 server/agents/core/events.py ALL_EVENT_TYPES）。"""
 def test_builtin_slugs_derived_from_class_exactly(self) -> None:
 """BUILTIN_SLUGS 必须 == PromptSlugs 所有字符串类属性的值集合。"""
 expected = {
 v
 for k, v in vars(PromptSlugs).items
 if not k.startswith("_") and isinstance(v, str)
 }
 assert BUILTIN_SLUGS == frozenset(expected)
 def test_builtin_slugs_exact_count_locked(self) -> None:
 """锁死 15 个 slug — 新增 slug 必须同时更新此断言。"""
 assert len(BUILTIN_SLUGS) == 15, (
 f"BUILTIN_SLUGS count drift: got {len(BUILTIN_SLUGS)}, "
 "expected 15. 若确认新增，请同步更新此断言与 PLAN 文档。"
 )
 def test_every_slug_follows_naming_convention(self) -> None:
 """所有 slug 必须遵循 `{category}.{...}` 小写点分命名。"""
 for slug in BUILTIN_SLUGS:
 assert slug == slug.lower, f"非小写 slug: {slug}"
 assert "." in slug, f"slug 缺少点分: {slug}"
 assert " " not in slug, f"slug 含空格: {slug}"
 @pytest.mark.parametrize("slug", sorted(BUILTIN_SLUGS))
 @pytest.mark.django_db
 async def test_every_slug_renderable_via_fallback(self, slug: str) -> None:
 """Phase DB 无 seed —— 所有 slug 必须走 fallback 路径可达。
 这是防 G3 同型的核心契约：Registry 写入但调用点未读取的情况，
 通过遍历 BUILTIN_SLUGS + render_prompt(fallback="STUB") 必然返回 "STUB"。
 """
 result = await render_prompt(
 slug=slug,
 project_id=None,
 variables={},
 fallback="STUB_FALLBACK",
 )
 assert result == "STUB_FALLBACK"

"""CssExtractor 单元测试 —— 验证 implementation 落地。

per implementation / work item：class / id selector / @import 双形态 / CSS var 守卫 /
tag selector 守卫 / 复合选择器递归全覆盖。fixture: server/codegraph/tests/fixtures/css_theme.css
"""

from __future__ import annotations

import os

import pytest

from codegraph.extractors.base import FileContext
from codegraph.extractors.css_extractor import CssExtractor


@pytest.fixture
def css_theme_source() -> str:
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(
        os.path.join(fixtures_dir, "css_theme.css"), "r", encoding="utf-8"
    ) as f:
        return f.read()


@pytest.fixture
def css_ctx() -> FileContext:
    return FileContext(
        file_path=".vitepress/theme/style.css",
        language="css",
        repository_id="r1",
    )


class TestCssExtractor:
    """CssExtractor + walker / symbol / imports css 分支端到端。"""

    def test_class_selector_yields_symbol(self, css_theme_source: str, css_ctx) -> None:
        """.foo / .button-primary / .button-secondary → CLASS。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        names = [(s.name, s.symbol_type) for s in bundle.symbols]
        assert ("foo", "CLASS") in names
        assert ("button-primary", "CLASS") in names
        assert ("button-secondary", "CLASS") in names

    def test_id_selector_yields_symbol(self, css_theme_source: str, css_ctx) -> None:
        """#app / #footer → VARIABLE。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        names = [(s.name, s.symbol_type) for s in bundle.symbols]
        assert ("app", "VARIABLE") in names
        assert ("footer", "VARIABLE") in names

    def test_css_var_not_extracted(self, css_theme_source: str, css_ctx) -> None:
        """--vp-c-brand / --vp-c-text 不抽 SymbolData（per work item）。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        names = [s.name for s in bundle.symbols]
        assert "vp-c-brand" not in names
        assert "vp-c-text" not in names
        assert "--vp-c-brand" not in names

    def test_tag_selector_not_extracted(self, css_theme_source: str, css_ctx) -> None:
        """body / * (universal selector) 不抽。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        names = [s.name for s in bundle.symbols]
        assert "body" not in names
        assert "*" not in names

    def test_pseudo_class_not_extracted(self, css_theme_source: str, css_ctx) -> None:
        """:hover / :root pseudo 名不抽（per Pitfall 5）。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        names = [s.name for s in bundle.symbols]
        assert "hover" not in names
        assert "root" not in names

    def test_import_url_yields_import(self, css_theme_source: str, css_ctx) -> None:
        """@import url("./base.css") + @import "./reset.css" 双形态都抽。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        targets = [i.target_module for i in bundle.imports]
        assert "./base.css" in targets
        assert "./reset.css" in targets
        # 双形态都是 relative
        rel_map = {i.target_module: i.is_relative for i in bundle.imports}
        assert rel_map["./base.css"] is True
        assert rel_map["./reset.css"] is True

    def test_compound_selector_recursed(self, css_theme_source: str, css_ctx) -> None:
        """.complex.modifier:hover → 递归拆出 complex + modifier。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        names = [(s.name, s.symbol_type) for s in bundle.symbols]
        assert ("complex", "CLASS") in names
        assert ("modifier", "CLASS") in names

    def test_calls_endpoints_empty(self, css_theme_source: str, css_ctx) -> None:
        """calls / endpoints 显式 [] (per work item / work item)。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        assert bundle.calls == []
        assert bundle.endpoints == []

    def test_dedup_same_selector(self, css_theme_source: str, css_ctx) -> None:
        """同 fixture 中 foo 只出现一次（同 rule_set 去重 + 跨 rule_set 不重复）。"""
        bundle = CssExtractor().extract(
            ".vitepress/theme/style.css", css_theme_source, css_ctx
        )
        foo_count = sum(
            1 for s in bundle.symbols if s.name == "foo" and s.symbol_type == "CLASS"
        )
        assert foo_count == 1

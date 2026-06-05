"""HtmlExtractor 单元测试 —— 验证 implementation 落地。

per implementation / work item：PascalCase tag / custom element / id 属性 / 三类 import /
scheme 守卫 / a href 守卫全覆盖。fixture: server/codegraph/tests/fixtures/html_index.html
"""

from __future__ import annotations

import os

import pytest

from codegraph.extractors.base import FileContext
from codegraph.extractors.html_extractor import HtmlExtractor


@pytest.fixture
def html_index_source() -> str:
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    with open(
        os.path.join(fixtures_dir, "html_index.html"), "r", encoding="utf-8"
    ) as f:
        return f.read()


@pytest.fixture
def html_ctx() -> FileContext:
    return FileContext(
        file_path="apps/test/public/index.html",
        language="html",
        repository_id="r1",
    )


class TestHtmlExtractor:
    """HtmlExtractor + walker / symbol / imports html 分支端到端。"""

    def test_pascalcase_tag_yields_symbol(self, html_index_source: str, html_ctx) -> None:
        """MyComponent → SymbolData(name=MyComponent, symbol_type=CLASS)。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        names = [(s.name, s.symbol_type) for s in bundle.symbols]
        assert ("MyComponent", "CLASS") in names

    def test_custom_element_yields_symbol(self, html_index_source: str, html_ctx) -> None:
        """el-button → SymbolData(name=el-button, symbol_type=CLASS)。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        names = [(s.name, s.symbol_type) for s in bundle.symbols]
        assert ("el-button", "CLASS") in names

    def test_id_attribute_yields_symbol(self, html_index_source: str, html_ctx) -> None:
        """app / footer → SymbolData(name=app|footer, symbol_type=VARIABLE)。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        names = [(s.name, s.symbol_type) for s in bundle.symbols]
        assert ("app", "VARIABLE") in names
        assert ("footer", "VARIABLE") in names

    def test_lowercase_native_tags_not_extracted(
        self, html_index_source: str, html_ctx
    ) -> None:
        """div / body / head / img / a 等小写原生 tag 不抽 SymbolData。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        names = [s.name for s in bundle.symbols]
        for native in ("div", "body", "head", "html", "img", "a", "title", "meta"):
            assert native not in names

    def test_link_href_yields_import(self, html_index_source: str, html_ctx) -> None:
        """3 个 <link href> 都进 imports。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        targets = [i.target_module for i in bundle.imports]
        assert "/css/main.css" in targets
        assert "//cdn.example.com/favicon.ico" in targets
        assert "./fonts/main.woff2" in targets

    def test_script_src_yields_import(self, html_index_source: str, html_ctx) -> None:
        """2 个 <script src> 进 imports。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        targets = [i.target_module for i in bundle.imports]
        assert "./app.js" in targets
        assert "/assets/index.tsx" in targets

    def test_img_src_yields_import(self, html_index_source: str, html_ctx) -> None:
        """<img src="/img/logo.png"> 进 imports。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        targets = [i.target_module for i in bundle.imports]
        assert "/img/logo.png" in targets

    def test_data_scheme_skipped(self, html_index_source: str, html_ctx) -> None:
        """<img src="data:image/..."> 不在 imports（per work item scheme 守卫）。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        for imp in bundle.imports:
            assert not imp.target_module.lower().startswith("data:")

    def test_a_href_not_extracted(self, html_index_source: str, html_ctx) -> None:
        """<a href="https://example.com"> 不在 imports（per work item OUT OF SCOPE）。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        targets = [i.target_module for i in bundle.imports]
        assert "https://example.com" not in targets

    def test_calls_endpoints_empty(self, html_index_source: str, html_ctx) -> None:
        """calls / endpoints 显式 [] (per work item / work item)。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        assert bundle.calls == []
        assert bundle.endpoints == []

    def test_is_relative_field(self, html_index_source: str, html_ctx) -> None:
        """is_relative：./app.js True；/css/main.css False；//cdn... False。"""
        bundle = HtmlExtractor().extract(
            "apps/test/public/index.html", html_index_source, html_ctx
        )
        rel_map = {i.target_module: i.is_relative for i in bundle.imports}
        assert rel_map["./app.js"] is True
        assert rel_map["./fonts/main.woff2"] is True
        assert rel_map["/css/main.css"] is False
        assert rel_map["//cdn.example.com/favicon.ico"] is False
        assert rel_map["/img/logo.png"] is False

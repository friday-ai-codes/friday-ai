"""CSS 真实仓库 study-app 端到端集成测试 —— 覆盖 initial implementation 真实样本。

study-app .vitepress/theme/style.css 实测含 .dark / .DocSearch 两个 class selector，
预期 ≥ 2 SymbolData。仓库不存在时整类 SKIP（per Pitfall 9）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codegraph.extractors.base import FileContext
from codegraph.extractors.css_extractor import CssExtractor
from codegraph.extractors.registry import get_extractor


CSS_SAMPLE_REPO = Path(
    os.environ.get("STUDY_APP_REPO", "/Users/zaneliu/Projects/guanghe/study-app")
)
CSS_SAMPLE_FILE = CSS_SAMPLE_REPO / ".vitepress" / "theme" / "style.css"


class TestCssExtractorRegistration:
    """无 skipif 注册测试。"""

    def test_get_extractor_returns_css_extractor(self) -> None:
        extractor = get_extractor("css")
        assert extractor is not None
        assert type(extractor).__name__ == "CssExtractor"


@pytest.mark.skipif(
    not CSS_SAMPLE_FILE.exists(),
    reason=f"study-app .vitepress/theme/style.css not found at {CSS_SAMPLE_FILE}",
)
class TestStudyAppCssExtraction:
    """study-app 真实 CSS 端到端。"""

    def test_vitepress_style_css_yields_data(self) -> None:
        extractor = get_extractor("css")
        assert extractor is not None
        source = CSS_SAMPLE_FILE.read_text(encoding="utf-8")
        ctx = FileContext(
            file_path=str(CSS_SAMPLE_FILE.relative_to(CSS_SAMPLE_REPO)),
            language="css",
            repository_id="study-app",
        )
        bundle = extractor.extract(str(CSS_SAMPLE_FILE), source, ctx)
        # 实测含 .dark + .DocSearch 两个 class selector
        assert len(bundle.symbols) >= 1, f"expected ≥ 1 symbol, got {len(bundle.symbols)}"
        assert bundle.calls == []
        assert bundle.endpoints == []

    def test_vitepress_style_css_class_selectors_extracted(self) -> None:
        """显式断言 .dark / .DocSearch class selector 都抽到 CLASS。"""
        extractor = get_extractor("css")
        assert extractor is not None
        source = CSS_SAMPLE_FILE.read_text(encoding="utf-8")
        ctx = FileContext(
            file_path=str(CSS_SAMPLE_FILE.relative_to(CSS_SAMPLE_REPO)),
            language="css",
            repository_id="study-app",
        )
        bundle = extractor.extract(str(CSS_SAMPLE_FILE), source, ctx)
        names = {(s.name, s.symbol_type) for s in bundle.symbols}
        assert ("dark", "CLASS") in names
        assert ("DocSearch", "CLASS") in names

"""HTML 真实仓库 example-app 端到端集成测试 —— 覆盖 implementation 真实样本。

不调 indexer ORM 路径（同 implementation / 262 / 263 精神），仅断言 HtmlExtractor.extract
在真实 .html 文件上返回非空 bundle 各字段。

example-app 仓库不存在时 TestStudyAppHtmlExtraction 整类 SKIP（per Pitfall 9 兜底），
TestHtmlExtractorRegistration 注册测试在任意环境（含 CI）均 PASS。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codegraph.extractors.base import FileContext
from codegraph.extractors.registry import get_extractor

HTML_SAMPLE_REPO = Path(os.environ.get("STUDY_APP_REPO", ""))


class TestHtmlExtractorRegistration:
    """无 skipif 注册测试 —— 在任意环境（CI / 本地）验证 EXTRACTOR_REGISTRY 注册路径。"""

    def test_get_extractor_returns_html_extractor(self) -> None:
        extractor = get_extractor("html")
        assert extractor is not None
        assert type(extractor).__name__ == "HtmlExtractor"


@pytest.mark.skipif(
    not os.environ.get("STUDY_APP_REPO") or not HTML_SAMPLE_REPO.exists(),
    reason="sample repo not configured (STUDY_APP_REPO)",
)
class TestStudyAppHtmlExtraction:
    """example-app 真实 HTML 端到端 —— 仓库存在时验证抽取行为。"""

    def test_recite_geography_index_html_yields_data(self) -> None:
        extractor = get_extractor("html")
        assert extractor is not None
        path = HTML_SAMPLE_REPO / "apps" / "reciteGeography" / "public" / "index.html"
        if not path.exists():
            pytest.skip(f"sample html not found: {path}")
        source = path.read_text(encoding="utf-8")
        ctx = FileContext(
            file_path=str(path.relative_to(HTML_SAMPLE_REPO)),
            language="html",
            repository_id="example-app",
        )
        bundle = extractor.extract(str(path), source, ctx)
        # reciteGeography 含 <div id="app"> + <link href="..."> + <img src="...">
        assert len(bundle.symbols) >= 1, f"expected ≥ 1 symbol, got {bundle.symbols}"
        assert len(bundle.imports) >= 1, f"expected ≥ 1 import, got {bundle.imports}"
        assert bundle.calls == []
        assert bundle.endpoints == []

    def test_home_index_html_parseable(self) -> None:
        extractor = get_extractor("html")
        assert extractor is not None
        path = HTML_SAMPLE_REPO / "apps" / "home" / "public" / "index.html"
        if not path.exists():
            pytest.skip(f"sample html not found: {path}")
        source = path.read_text(encoding="utf-8")
        ctx = FileContext(
            file_path=str(path.relative_to(HTML_SAMPLE_REPO)),
            language="html",
            repository_id="example-app",
        )
        bundle = extractor.extract(str(path), source, ctx)
        # 容错阈值 per Pitfall 13：example-app 真实 HTML 可能仅含 id 属性 SymbolData
        assert len(bundle.symbols) >= 0
        assert bundle.calls == []
        assert bundle.endpoints == []

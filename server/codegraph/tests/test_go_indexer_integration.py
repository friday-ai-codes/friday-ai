"""Go gin 仓库端到端集成测试。

不调 indexer ORM 路径（刻意不扩展到 GraphWriter 全链路），仅断言
GraphExtractor.extract_all 在真实 .go 文件上返回非空 bundle 各字段。

通过环境变量 GO_GIN_SAMPLE_REPO 指定本地样例仓库；不设或路径不存在时整
TestStudyCourseExtraction 类 SKIP。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codegraph.extractors.base import FileContext
from codegraph.services.orchestrator import GraphExtractor

GO_SAMPLE_REPO = Path(os.environ.get("GO_GIN_SAMPLE_REPO", ""))


@pytest.fixture
def go_parser():
    """返回预配置的 tree-sitter Go Parser。"""
    import tree_sitter_go
    from tree_sitter import Language, Parser

    ts_lang = Language(tree_sitter_go.language())
    return Parser(ts_lang)


class TestGoExtractorRegistration:
    """巩固 plan：EXTRACTOR_REGISTRY['go'] 注册端到端验证。"""

    def test_get_extractor_returns_go_extractor(self):
        """get_extractor('go') 在真实运行环境下返回 GoExtractor 实例。"""
        from codegraph.extractors.registry import get_extractor

        extractor = get_extractor("go")
        assert extractor is not None
        assert type(extractor).__name__ == "GoExtractor"


@pytest.mark.skipif(
    not os.environ.get("GO_GIN_SAMPLE_REPO") or not GO_SAMPLE_REPO.exists(),
    reason=f"Go gin sample repo not present at {GO_SAMPLE_REPO}",
)
class TestStudyCourseExtraction:
    """真实 Go gin 仓库 study-course 端到端抽取测试。"""

    def test_handlers_directory_yields_symbols_imports_calls(self, go_parser):
        """遍历 study-course handlers/ 全部 .go 文件，断言三维抽取计数均 > 0。"""
        extractor = GraphExtractor()
        total_symbols, total_imports, total_calls = 0, 0, 0
        files_scanned = 0

        handlers_dir = GO_SAMPLE_REPO / "handlers"
        if not handlers_dir.exists():
            pytest.skip(f"{handlers_dir} not present")

        for go_file in handlers_dir.rglob("*.go"):
            source = go_file.read_text(encoding="utf-8")
            tree = go_parser.parse(source.encode("utf-8"))
            ctx = FileContext(
                file_path=str(go_file),
                language="go",
                repository_id="study-course",
            )
            bundle = extractor.extract_all(tree, source, ctx)
            total_symbols += len(bundle.symbols)
            total_imports += len(bundle.imports)
            total_calls += len(bundle.calls)
            files_scanned += 1

        assert files_scanned > 0, "no .go files found under handlers/"
        assert total_symbols > 0, f"expected symbols, got {total_symbols}"
        assert total_imports > 0, f"expected imports, got {total_imports}"
        assert total_calls > 0, f"expected calls, got {total_calls}"

"""TS / TSX 真实仓库端到端集成测试。

不调 indexer ORM 路径（刻意不扩展到 GraphWriter 全链路），仅断言
GraphExtractor.extract_all 在真实 .ts / .tsx 文件上返回非空 bundle 各字段。

通过环境变量 TS_SAMPLE_REPO 指定本地样例仓库；不设或路径不存在时整
TestStudyAppExtraction 类 SKIP。TestTSExtractorRegistration 不带 skipif，
任意环境必跑。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codegraph.extractors.base import FileContext
from codegraph.services.orchestrator import GraphExtractor

TS_SAMPLE_REPO = Path(os.environ.get("TS_SAMPLE_REPO", ""))


@pytest.fixture
def ts_parser():
    """返回预配置的 tree-sitter TypeScript Parser。"""
    import tree_sitter_typescript
    from tree_sitter import Language, Parser

    return Parser(Language(tree_sitter_typescript.language_typescript()))


@pytest.fixture
def tsx_parser():
    """返回预配置的 tree-sitter TSX Parser。"""
    import tree_sitter_typescript
    from tree_sitter import Language, Parser

    return Parser(Language(tree_sitter_typescript.language_tsx()))


class TestTSExtractorRegistration:
    """巩固 plan：EXTRACTOR_REGISTRY['typescript'] / ['tsx'] 注册端到端验证。"""

    def test_get_extractor_returns_ts_extractor(self):
        """get_extractor('typescript') 在真实运行环境下返回 TSExtractor 实例。"""
        from codegraph.extractors.registry import get_extractor

        extractor = get_extractor("typescript")
        assert extractor is not None
        assert type(extractor).__name__ == "TSExtractor"

    def test_get_extractor_returns_tsx_extractor(self):
        """get_extractor('tsx') 在真实运行环境下返回 TSXExtractor 实例。"""
        from codegraph.extractors.registry import get_extractor

        extractor = get_extractor("tsx")
        assert extractor is not None
        assert type(extractor).__name__ == "TSXExtractor"


@pytest.mark.skipif(
    not os.environ.get("TS_SAMPLE_REPO") or not TS_SAMPLE_REPO.exists(),
    reason=f"TS sample repo not present at {TS_SAMPLE_REPO}",
)
class TestStudyAppExtraction:
    """真实 example-app monorepo 端到端抽取测试（采样 reciteGeography service + utils/plugin）。"""

    def test_recite_geography_service_yields_symbols_imports(self, ts_parser):
        """采样 apps/reciteGeography/src/service/ 全部 .ts 文件，断言 symbols 与 imports 计数 > 0。"""
        extractor = GraphExtractor()
        total_symbols, total_imports, total_calls = 0, 0, 0
        files_scanned = 0

        service_dir = TS_SAMPLE_REPO / "apps" / "reciteGeography" / "src" / "service"
        if not service_dir.exists():
            pytest.skip(f"{service_dir} not present")

        for ts_file in service_dir.rglob("*.ts"):
            source = ts_file.read_text(encoding="utf-8")
            tree = ts_parser.parse(source.encode("utf-8"))
            ctx = FileContext(
                file_path=str(ts_file),
                language="typescript",
                repository_id="example-app",
            )
            bundle = extractor.extract_all(tree, source, ctx)
            total_symbols += len(bundle.symbols)
            total_imports += len(bundle.imports)
            total_calls += len(bundle.calls)
            files_scanned += 1

        assert files_scanned > 0, "no .ts files found under reciteGeography/src/service/"
        assert total_symbols > 0, f"expected symbols, got {total_symbols}"
        assert total_imports > 0, f"expected imports, got {total_imports}"
        # calls 可能 0（纯 interface / type 文件），不强断言（per work item 宽阈值）

    def test_utils_plugin_index_tsx_yields_symbols_imports(self, tsx_parser):
        """采样 utils/plugin/index.tsx（项目唯一 .tsx 文件），断言 symbols + imports 计数 > 0。"""
        extractor = GraphExtractor()
        tsx_file = TS_SAMPLE_REPO / "utils" / "plugin" / "index.tsx"
        if not tsx_file.exists():
            pytest.skip(f"{tsx_file} not present")

        source = tsx_file.read_text(encoding="utf-8")
        tree = tsx_parser.parse(source.encode("utf-8"))
        ctx = FileContext(
            file_path=str(tsx_file),
            language="tsx",
            repository_id="example-app",
        )
        bundle = extractor.extract_all(tree, source, ctx)

        assert len(bundle.symbols) > 0, f"expected symbols, got {len(bundle.symbols)}"
        assert len(bundle.imports) > 0, f"expected imports, got {len(bundle.imports)}"
        # JSX call 可能 0（纯 utility，不渲染 React 树），不强断言

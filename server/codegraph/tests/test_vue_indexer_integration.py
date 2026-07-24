"""Vue 真实仓库端到端集成测试。

不调 indexer ORM 路径，仅断言 VueExtractor.extract 在真实 .vue 文件上
返回非空 bundle 各字段。

环境约束：
- 通过环境变量 `VUE_SAMPLE_REPO` 指定本地样例仓库
- TestVueExtractorRegistration 类不带 skipif（CI 必跑）
- TestStudyAppVueExtraction 类带 skipif，缺样例仓库时整类 SKIP
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from codegraph.extractors.base import FileContext
from codegraph.extractors.registry import get_extractor

VUE_SAMPLE_REPO = Path(os.environ.get("VUE_SAMPLE_REPO", ""))


class TestVueExtractorRegistration:
    """巩固 plan：EXTRACTOR_REGISTRY['vue'] 注册端到端验证。"""

    def test_get_extractor_returns_vue_extractor(self) -> None:
        extractor = get_extractor("vue")
        assert extractor is not None
        assert type(extractor).__name__ == "VueExtractor"


@pytest.mark.skipif(
    not os.environ.get("VUE_SAMPLE_REPO") or not VUE_SAMPLE_REPO.exists(),
    reason=f"Vue sample repo not present at {VUE_SAMPLE_REPO}",
)
class TestStudyAppVueExtraction:
    """真实 example-app monorepo 端到端抽取测试（采样三类典型 SFC 形态）。"""

    def test_options_api_yields_symbols_imports_calls(self) -> None:
        """Vue 2 Options API：utils/task/nps/feedback.vue + main.vue 抽取。"""
        extractor = get_extractor("vue")
        assert extractor is not None
        total_symbols, total_imports = 0, 0

        for path in [
            VUE_SAMPLE_REPO / "utils" / "task" / "nps" / "feedback.vue",
            VUE_SAMPLE_REPO / "utils" / "task" / "nps" / "components" / "main.vue",
        ]:
            if not path.exists():
                pytest.skip(f"{path} not present")
            source = path.read_text(encoding="utf-8")
            ctx = FileContext(
                file_path=str(path),
                language="vue",
                repository_id="example-app",
            )
            bundle = extractor.extract(str(path), source, ctx)
            total_symbols += len(bundle.symbols)
            total_imports += len(bundle.imports)

        assert total_symbols > 0, f"expected > 0 symbols, got {total_symbols}"
        assert total_imports > 0, f"expected > 0 imports, got {total_imports}"

    def test_script_setup_ts_yields_symbols_imports(self) -> None:
        """Vue 2.7 <script setup lang="ts">：.vitepress/components/HomePage.vue 抽取。"""
        extractor = get_extractor("vue")
        assert extractor is not None
        path = VUE_SAMPLE_REPO / ".vitepress" / "components" / "HomePage.vue"
        if not path.exists():
            pytest.skip(f"{path} not present")
        source = path.read_text(encoding="utf-8")
        ctx = FileContext(
            file_path=str(path), language="vue", repository_id="example-app"
        )
        bundle = extractor.extract(str(path), source, ctx)

        assert len(bundle.symbols) > 0
        assert len(bundle.imports) > 0

    def test_custom_typescript_setup_yields_data(self) -> None:
        """项目自定义 `<script typescript setup>`：utils/plugin/index.vue 抽取（容错路径，per Pitfall 6）。"""
        extractor = get_extractor("vue")
        assert extractor is not None
        path = VUE_SAMPLE_REPO / "utils" / "plugin" / "index.vue"
        if not path.exists():
            pytest.skip(f"{path} not present")
        source = path.read_text(encoding="utf-8")
        ctx = FileContext(
            file_path=str(path), language="vue", repository_id="example-app"
        )
        bundle = extractor.extract(str(path), source, ctx)

        assert len(bundle.symbols) >= 1

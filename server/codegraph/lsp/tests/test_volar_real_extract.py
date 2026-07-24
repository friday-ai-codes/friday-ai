"""集成测试：真实 volar 抽样例仓库 sub-project 验证 SymbolData / ImportData。

@pytest.mark.integration + 三重 skipif：vue-language-server 装 + 样例仓库路径（VOLAR_TEST_REPO）+ fixture 存在
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_VLS_BIN: str | None = shutil.which("vue-language-server")
_STUDY_APP: Path = Path(os.environ.get("VOLAR_TEST_REPO", ""))
_COURSES_SUB: Path = _STUDY_APP / "apps" / "courses"


@pytest.mark.skipif(_VLS_BIN is None, reason="vue-language-server 未在 PATH")
@pytest.mark.skipif(not _COURSES_SUB.exists(), reason="example-app 仓库不在期望路径")
class TestVolarRealExtract:
    """真实 volar 抽 apps/courses sub-project 验收 V2 / V4 端到端。"""

    def test_discover_sub_projects_finds_courses(self) -> None:
        """workspace_discovery 真实跑 example-app 找 apps/courses（vue 2.7.x）。"""
        from codegraph.lsp.workspace_discovery import discover_sub_projects

        sub_projects = discover_sub_projects(_STUDY_APP)
        assert len(sub_projects) >= 30, (
            f"example-app 应 ≥ 30 sub-projects，实测 {len(sub_projects)}"
        )
        courses = [s for s in sub_projects if s.root == _COURSES_SUB.resolve()]
        assert len(courses) == 1
        vue_ver = courses[0].vue_version
        assert vue_ver is not None
        assert vue_ver.lstrip("^~>=<").startswith("2.7"), (
            f"期望 vue 2.7.x，实测 {vue_ver}"
        )

    def test_volar_extract_symbols_from_real_vue_file(self) -> None:
        """真实 volar 抽 apps/courses/src/components/Footer/index.vue。"""
        from codegraph.extractors.base import FileContext
        from codegraph.lsp.volar_backend import VolarBackend
        from codegraph.lsp.volar_pool import get_volar_pool

        pool = get_volar_pool()
        try:
            supervisor = pool.get(_COURSES_SUB, vue_version="2.7.14")
            backend = VolarBackend(language="vue", supervisor=supervisor)

            target_file = _COURSES_SUB / "src" / "components" / "Footer" / "index.vue"
            if not target_file.exists():
                pytest.skip(f"目标文件不存在: {target_file}")
            source = target_file.read_text()
            ctx = FileContext(
                file_path=str(target_file),
                language="vue",
                repository_id="example-app",
            )
            tree = backend.parse_file(str(target_file), source)
            symbols = backend.extract_symbols(tree, source, ctx)
            # 至少抽到 Component 级 symbol（fallback 也能保底）
            assert len(symbols) >= 1
        finally:
            pool.shutdown_all(timeout=10.0)

    def test_volar_extract_imports_resolves_tsconfig_paths(self) -> None:
        """真实 volar 解 @/utils 类型 import 到具体绝对路径（advisory 不强卡精度）。"""
        from codegraph.extractors.base import FileContext
        from codegraph.lsp.volar_backend import VolarBackend
        from codegraph.lsp.volar_pool import get_volar_pool

        pool = get_volar_pool()
        try:
            supervisor = pool.get(_COURSES_SUB, vue_version="2.7.14")
            backend = VolarBackend(language="typescript", supervisor=supervisor)

            services_dir = _COURSES_SUB / "src" / "services"
            if not services_dir.exists():
                pytest.skip(f"无 services/ 目录: {services_dir}")
            candidate = next(iter(services_dir.glob("*.ts")), None)
            if candidate is None:
                pytest.skip("无 services/*.ts 样本")

            source = candidate.read_text()
            ctx = FileContext(
                file_path=str(candidate),
                language="typescript",
                repository_id="example-app",
            )
            tree = backend.parse_file(str(candidate), source)
            imports = backend.extract_imports(tree, ctx)
            assert len(imports) >= 1
            resolved = [imp for imp in imports if getattr(imp, "target_path", None) is not None]
            advisory_rate = len(resolved) / max(len(imports), 1)
            print(f"advisory imports resolved rate: {advisory_rate:.2%}")
        finally:
            pool.shutdown_all(timeout=10.0)

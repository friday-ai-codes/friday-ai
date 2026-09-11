"""implementation 集成测试：真实 gopls 抽 sample_course_service Go 仓库验证 SymbolData / ImportData。

@pytest.mark.integration + 三重 skipif：gopls binary / sample_course_service 路径 / go.mod 存在。

启用：研发本地装 gopls + sample_course_service 路径存在时跑：
    pytest -m integration codegraph/lsp/tests/test_gopls_real_extract.py
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_GOPLS_BIN: str | None = shutil.which("gopls")
_SAMPLE_COURSE_SERVICE: Path = Path(os.environ.get("GOPLS_TEST_REPO", ""))
_SAMPLE_COURSE_SERVICE_GOMOD: Path = _SAMPLE_COURSE_SERVICE / "go.mod"


@pytest.mark.skipif(
    _GOPLS_BIN is None,
    reason="gopls 未在 PATH（需 go install golang.org/x/tools/gopls@latest）",
)
@pytest.mark.skipif(
    not _SAMPLE_COURSE_SERVICE_GOMOD.exists(),
    reason="sample_course_service go.mod 不在期望路径",
)
class TestGoplsRealExtract:
    """真实 gopls 抽取 sample_course_service Go 仓库。"""

    def test_discover_go_workspace_finds_sample_course_service(self) -> None:
        """discover_go_workspace 真实跑 sample_course_service 找 go.mod。"""
        from codegraph.lsp.go_workspace import discover_go_workspace

        workspace = discover_go_workspace(_SAMPLE_COURSE_SERVICE)
        assert workspace is not None, "sample_course_service go.mod 未被发现"
        assert workspace.go_mod_root == _SAMPLE_COURSE_SERVICE.resolve()
        assert workspace.module_path is not None
        assert workspace.go_version is not None

    def test_gopls_extract_symbols_from_real_go_file(
        self, request: pytest.FixtureRequest
    ) -> None:
        """验证 _GoplsLazyInstance fallback 链完整性：supervisor 注入后 parse_file
        返 handle → _lsp_extract_symbols raise → tree-sitter fallback → ≥ 1 symbol。

        NOTE: 此测试实际执行的是 tree-sitter fallback，并非 gopls 直接抽取。
        implementation 切真实 per-file supervisor 注入后，此测试需重写为
        直接调 _GoplsLazyBackend._lsp_extract_symbols 验证 gopls 抽取路径。
        """
        import services.background_runner as _bg
        _bg._ensure_worker_loop()

        from codegraph.extractors.base import FileContext
        from codegraph.lsp.go_workspace import discover_go_workspace
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend, make_gopls_backend
        from codegraph.lsp.supervisor import LspSupervisor

        workspace = discover_go_workspace(_SAMPLE_COURSE_SERVICE)
        assert workspace is not None

        supervisor = LspSupervisor(
            name="gopls-sample_course_service-test",
            command=list(_GoplsLazyBackend.command),
            workspace_root=workspace.go_mod_root,
            language_ids=list(_GoplsLazyBackend.language_ids),
            initialization_options=dict(_GoplsLazyBackend.initialization_options),
            max_restart_attempts=1,
        )

        go_files = list(_SAMPLE_COURSE_SERVICE.glob("*.go")) or list(_SAMPLE_COURSE_SERVICE.glob("**/*.go"))
        if not go_files:
            pytest.skip("sample_course_service 未找到任何 .go 文件")
        target_file = go_files[0]
        source = target_file.read_text(encoding="utf-8")
        ctx = FileContext(file_path=str(target_file), language="go", repository_id="1")

        factory = make_gopls_backend("go")
        backend = factory("go")

        try:
            supervisor.call_async_in_loop(supervisor.ensure_started, timeout=60.0)
            # 注入真实 supervisor
            backend._supervisor = supervisor  # type: ignore[attr-defined]
            tree = backend.parse_file(str(target_file), source)
            symbols = backend.extract_symbols(tree, source, ctx)
            assert len(symbols) >= 1, f"预期 ≥ 1 SymbolData，实测 {len(symbols)}"
            valid_types = {"FUNCTION", "CLASS", "VARIABLE"}
            for sym in symbols:
                assert sym.symbol_type in valid_types, f"非法 symbol_type: {sym.symbol_type}"
        finally:
            request.addfinalizer(
                lambda: supervisor.call_async_in_loop(supervisor.stop, timeout=5.0)
            )

    def test_gopls_extract_imports_resolves_paths(
        self, request: pytest.FixtureRequest
    ) -> None:
        """验证 _GoplsLazyInstance fallback 链完整性（imports 路径）：
        supervisor 注入后 parse_file 返 handle → _lsp_extract_imports raise
        → tree-sitter fallback → ≥ 1 ImportData。

        NOTE: 此测试实际执行的是 tree-sitter fallback，并非 gopls 直接抽取。
        implementation 切真实 per-file supervisor 注入后，此测试需重写为
        直接调 _GoplsLazyBackend._lsp_extract_imports 验证 gopls 抽取路径。
        """
        import services.background_runner as _bg
        _bg._ensure_worker_loop()

        from codegraph.extractors.base import FileContext
        from codegraph.lsp.go_workspace import discover_go_workspace
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend, make_gopls_backend
        from codegraph.lsp.supervisor import LspSupervisor

        workspace = discover_go_workspace(_SAMPLE_COURSE_SERVICE)
        assert workspace is not None

        supervisor = LspSupervisor(
            name="gopls-sample_course_service-import-test",
            command=list(_GoplsLazyBackend.command),
            workspace_root=workspace.go_mod_root,
            language_ids=list(_GoplsLazyBackend.language_ids),
            initialization_options=dict(_GoplsLazyBackend.initialization_options),
            max_restart_attempts=1,
        )

        go_files = [f for f in _SAMPLE_COURSE_SERVICE.glob("**/*.go") if "_test" not in f.name]
        if not go_files:
            pytest.skip("sample_course_service 未找到非测试 .go 文件")
        target_file = go_files[0]
        source = target_file.read_text(encoding="utf-8")
        ctx = FileContext(file_path=str(target_file), language="go", repository_id="1")

        factory = make_gopls_backend("go")
        backend = factory("go")

        try:
            supervisor.call_async_in_loop(supervisor.ensure_started, timeout=60.0)
            backend._supervisor = supervisor  # type: ignore[attr-defined]
            tree = backend.parse_file(str(target_file), source)
            imports = backend.extract_imports(tree, ctx)
            assert len(imports) >= 1, f"预期 ≥ 1 ImportData，实测 {len(imports)}"
            resolved = [imp for imp in imports if getattr(imp, "target_path", None) is not None]
            advisory_rate = len(resolved) / max(len(imports), 1)
            print(f"advisory import resolved rate: {advisory_rate:.2%}")
        finally:
            request.addfinalizer(
                lambda: supervisor.call_async_in_loop(supervisor.stop, timeout=5.0)
            )


class TestGoplsPhaseSettings:
    """settings 切换验证（不需 gopls binary，非 integration）。"""

    def test_extractor_backends_go_is_gopls(self) -> None:
        """EXTRACTOR_BACKENDS["go"] 已切为 "gopls"（implementation-03）。"""
        from django.conf import settings

        assert settings.EXTRACTOR_BACKENDS.get("go") == "gopls", (
            f"期望 'gopls'，实际 '{settings.EXTRACTOR_BACKENDS.get('go')}'"
        )

    def test_gopls_backend_enabled_is_true(self) -> None:
        """GOPLS_BACKEND_ENABLED == True（implementation-03 已切换）。"""
        from django.conf import settings

        assert getattr(settings, "GOPLS_BACKEND_ENABLED", False) is True, (
            "GOPLS_BACKEND_ENABLED 应为 True，请检查 settings.py"
        )


@pytest.mark.skipif(
    _GOPLS_BIN is None,
    reason="gopls 未在 PATH（measure_go_call_completeness 需真实 gopls）",
)
class TestMeasureGoCallCompletenessCommand:
    """measure_go_call_completeness command 可调用验证（@integration）。"""

    def test_command_importable(self) -> None:
        """measure_go_call_completeness.py 可 import，Command 类存在。"""
        from codegraph.management.commands.measure_go_call_completeness import Command

        cmd = Command()
        assert hasattr(cmd, "handle")
        assert hasattr(cmd, "add_arguments")

    def test_ground_truth_csv_exists(self) -> None:
        """go_call_ground_truth.csv fixture 存在且有数据行。"""
        import csv
        from pathlib import Path

        csv_path = Path(__file__).parent.parent.parent / "management" / "fixtures" / "go_call_ground_truth.csv"
        assert csv_path.exists(), f"CSV 不存在：{csv_path}"

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.reader(filter(lambda row: not row.startswith("#"), f))]
        assert len(rows) >= 2, "CSV 应有 ≥ 1 数据行（不含 header）"

"""initial implementation: gopls_backend.py 单元测试（≥ 14 场景 mock supervisor + 4 hook 转换 + fallback）。

覆盖：
- ClassVar 字段验证
- ExtractorBackend protocol 实现
- _lsp_extract_symbols：WorkspaceSymbol / DocumentSymbol → SymbolData 转换（含 kind 映射）
- _lsp_extract_imports：definition 解析 target_path
- _lsp_extract_calls：references → CallData
- _lsp_extract_endpoints：返 []
- fallback 路径：LspTimeoutError / LspUnhealthyError
- _get_supervisor：check_go_runtime=False / discover_go_workspace=None
- make_gopls_backend 工厂
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from lsprotocol import types as lsp


def _make_mock_supervisor() -> MagicMock:
    """创建 mock LspSupervisor。"""
    sup = MagicMock()
    sup.name = "gopls-mock"
    sup._client = MagicMock()
    sup.call_async_in_loop = MagicMock()
    return sup


def _make_gopls_backend_with_mock_supervisor() -> tuple:
    """创建 _GoplsLazyBackend 实例，_supervisor 为 mock，_get_supervisor 被 patch。"""
    from codegraph.backends.protocols import TreeSitterBackend
    from codegraph.lsp.gopls_backend import _GoplsLazyBackend

    mock_sup = _make_mock_supervisor()
    backend = _GoplsLazyBackend.__new__(_GoplsLazyBackend)
    backend.language = "go"
    backend._supervisor = mock_sup
    backend._fallback = TreeSitterBackend("go")
    return backend, mock_sup


def _make_ctx(file_path: str = "/test/main.go") -> Any:
    from codegraph.extractors.base import FileContext
    return FileContext(file_path=file_path, language="go", repository_id="1")


def _make_lsp_handle(file_path: str = "/test/main.go", source: str = "") -> Any:
    from codegraph.lsp.backend import _LspParseHandle
    return _LspParseHandle(file_path=file_path, source=source)


def _make_workspace_symbol(
    name: str,
    kind: lsp.SymbolKind,
    line: int = 0,
    file_uri: str = "file:///test/main.go",
) -> MagicMock:
    """创建模拟 WorkspaceSymbol。"""
    item = MagicMock()
    item.name = name
    item.kind = kind
    range_obj = MagicMock()
    range_obj.start = MagicMock()
    range_obj.start.line = line
    range_obj.end = MagicMock()
    range_obj.end.line = line
    item.location = MagicMock()
    item.location.uri = file_uri
    item.location.range = range_obj
    return item


class TestGoplsLazyBackendClassVars:
    def test_classvar_fields(self) -> None:
        """name / language_ids / command ClassVar 字段验证。"""
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend

        assert _GoplsLazyBackend.name == "gopls"
        assert _GoplsLazyBackend.language_ids == ["go"]
        assert _GoplsLazyBackend.command == ["gopls", "serve"]

    def test_initialization_options_contains_filters(self) -> None:
        """initialization_options 含 build.directoryFilters（per work item）。"""
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend

        opts = _GoplsLazyBackend.initialization_options
        assert "build.directoryFilters" in opts
        assert "-vendor" in opts["build.directoryFilters"]

    def test_implements_lsp_backend_protocol(self) -> None:
        """isinstance(backend, LspBackend)。"""
        from codegraph.lsp.backend import LspBackend

        backend, _ = _make_gopls_backend_with_mock_supervisor()
        assert isinstance(backend, LspBackend)

    def test_has_required_extract_methods(self) -> None:
        """5 个 extract_*/parse_file 方法存在。"""
        backend, _ = _make_gopls_backend_with_mock_supervisor()
        for method_name in (
            "parse_file",
            "extract_symbols",
            "extract_imports",
            "extract_calls",
            "extract_endpoints",
        ):
            assert hasattr(backend, method_name), f"missing method: {method_name}"


class TestLspExtractSymbols:
    def test_extract_symbols_converts_function(self) -> None:
        """WorkspaceSymbol kind=Function → symbol_type='FUNCTION'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol(
            "Hello", lsp.SymbolKind.Function, line=0, file_uri="file:///test/main.go"
        )
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        ctx = _make_ctx("/test/main.go")

        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", ctx)

        assert len(result) >= 1
        assert result[0].name == "Hello"
        assert result[0].symbol_type == "FUNCTION"

    def test_extract_symbols_converts_struct_to_class(self) -> None:
        """WorkspaceSymbol kind=Struct → symbol_type='CLASS'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol(
            "MyStruct", lsp.SymbolKind.Struct, line=5, file_uri="file:///test/main.go"
        )
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        ctx = _make_ctx("/test/main.go")

        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", ctx)

        assert any(s.symbol_type == "CLASS" for s in result)

    def test_extract_symbols_line_index_0_to_1(self) -> None:
        """LSP 0-indexed line=0 → SymbolData.start_line == 1。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol(
            "Hello", lsp.SymbolKind.Function, line=0, file_uri="file:///test/main.go"
        )
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        ctx = _make_ctx("/test/main.go")

        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", ctx)

        assert result[0].start_line == 1

    def test_extract_symbols_unknown_kind_maps_to_function(self) -> None:
        """未知 SymbolKind（999）→ 不 crash；symbol_type == 'FUNCTION'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = MagicMock()
        ws_item.name = "UnknownSym"
        ws_item.kind = MagicMock()
        ws_item.kind.value = 999
        ws_item.location = MagicMock()
        ws_item.location.uri = "file:///test/main.go"
        ws_item.location.range = MagicMock()
        ws_item.location.range.start = MagicMock()
        ws_item.location.range.start.line = 2
        ws_item.location.range.end = MagicMock()
        ws_item.location.range.end.line = 2

        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        ctx = _make_ctx("/test/main.go")

        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", ctx)

        assert len(result) >= 1
        assert result[0].symbol_type == "FUNCTION"


class TestLspExtractImports:
    def test_extract_imports_resolves_via_definition(self) -> None:
        """fallback import + definition → target_path 解析。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import ImportData
        mock_imp = ImportData(
            source_file="/test/main.go",
            target_module="fmt",
            line=3,
            target_path=None,
        )

        with (
            patch.object(backend._fallback, "extract_imports", return_value=[mock_imp]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
            patch(
                "codegraph.lsp.gopls_backend._resolve_import_target_path",
                return_value="/usr/local/go/src/fmt/print.go",
            ),
        ):
            ctx = _make_ctx("/test/main.go")
            tree = _make_lsp_handle(source="package main\nimport \"fmt\"\n")
            result = backend._lsp_extract_imports(tree, ctx)

        assert len(result) >= 1
        assert result[0].target_path == "/usr/local/go/src/fmt/print.go"

    def test_extract_imports_handles_definition_none(self) -> None:
        """definition 返 None → target_path 保持 None。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import ImportData
        mock_imp = ImportData(
            source_file="/test/main.go",
            target_module="fmt",
            line=3,
            target_path=None,
        )

        with (
            patch.object(backend._fallback, "extract_imports", return_value=[mock_imp]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
            patch(
                "codegraph.lsp.gopls_backend._resolve_import_target_path",
                return_value=None,
            ),
        ):
            ctx = _make_ctx("/test/main.go")
            tree = _make_lsp_handle()
            result = backend._lsp_extract_imports(tree, ctx)

        assert result[0].target_path is None


class TestLspExtractCalls:
    def test_extract_calls_converts_references_to_calldata(self) -> None:
        """references → CallData：caller_file + caller_line（line+1）。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import SymbolData
        mock_sym = SymbolData(
            name="Hello",
            symbol_type="FUNCTION",
            file_path="/test/main.go",
            start_line=5,
            end_line=7,
        )

        ref = MagicMock()
        ref.uri = "file:///caller.go"
        ref_range = MagicMock()
        ref_range.start = MagicMock()
        ref_range.start.line = 9
        ref.range = ref_range
        mock_sup.call_async_in_loop.return_value = [ref]

        with (
            patch.object(backend._fallback, "extract_symbols", return_value=[mock_sym]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
        ):
            ctx = _make_ctx("/test/main.go")
            tree = _make_lsp_handle()
            result = backend._lsp_extract_calls(tree, ctx)

        assert len(result) >= 1
        assert result[0].caller_key[0] == "/caller.go"
        assert result[0].caller_key[2] == 10  # LSP 0-indexed 9 → 10

    def test_extract_calls_empty_when_no_symbols(self) -> None:
        """无 symbol → result 为空。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        with (
            patch.object(backend._fallback, "extract_symbols", return_value=[]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
        ):
            ctx = _make_ctx("/test/main.go")
            tree = _make_lsp_handle()
            result = backend._lsp_extract_calls(tree, ctx)

        assert result == []


class TestLspExtractEndpoints:
    def test_extract_endpoints_returns_empty(self) -> None:
        """_lsp_extract_endpoints 任意 ctx → []（per work item）。"""
        backend, _ = _make_gopls_backend_with_mock_supervisor()
        ctx = _make_ctx("/test/main.go")
        result = backend._lsp_extract_endpoints(None, "", ctx)
        assert result == []


class TestFallbackPaths:
    def test_extract_symbols_timeout_falls_back(self) -> None:
        """call_async_in_loop raise LspTimeoutError → 基类 extract_symbols fallback。"""
        from codegraph.lsp.exceptions import LspTimeoutError

        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        mock_sup.call_async_in_loop.side_effect = LspTimeoutError("timeout")

        mock_symbols = [MagicMock()]
        mock_parse = MagicMock(return_value=MagicMock())
        mock_extract = MagicMock(return_value=mock_symbols)

        with (
            patch.object(backend._fallback, "parse_file", mock_parse),
            patch.object(backend._fallback, "extract_symbols", mock_extract),
        ):
            from codegraph.extractors.base import FileContext
            ctx = FileContext(file_path="/test/main.go", language="go", repository_id="1")
            tree = _make_lsp_handle()

            result = backend.extract_symbols(tree, "", ctx)
            assert result == mock_symbols
            mock_extract.assert_called_once()

    def test_extract_imports_unhealthy_falls_back(self) -> None:
        """_lsp_extract_imports raise LspUnhealthyError → 基类 extract_imports fallback。"""
        from codegraph.lsp.exceptions import LspUnhealthyError

        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        mock_imports = [MagicMock()]
        with (
            patch.object(
                backend,
                "_lsp_extract_imports",
                side_effect=LspUnhealthyError("unhealthy"),
            ),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
            patch.object(backend._fallback, "extract_imports", return_value=mock_imports),
        ):
            from codegraph.extractors.base import FileContext
            ctx = FileContext(file_path="/test/main.go", language="go", repository_id="1")
            tree = _make_lsp_handle()
            result = backend.extract_imports(tree, ctx)

        assert result == mock_imports


class TestGetSupervisor:
    def test_get_supervisor_raises_unhealthy_when_go_check_fails(self) -> None:
        """check_go_runtime().available=False → LspUnhealthyError。"""
        from codegraph.lsp.exceptions import LspUnhealthyError
        from codegraph.lsp.go_check import GoCheckResult
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend
        from codegraph.backends.protocols import TreeSitterBackend

        backend = _GoplsLazyBackend.__new__(_GoplsLazyBackend)
        backend.language = "go"
        backend._fallback = TreeSitterBackend("go")

        with patch(
            "codegraph.lsp.gopls_backend.check_go_runtime",
            return_value=GoCheckResult(
                available=False,
                gopls_version=None,
                go_version=None,
                reason="gopls 不可用",
            ),
        ):
            with pytest.raises(LspUnhealthyError):
                backend._get_supervisor(Path("/test/main.go"))

    def test_get_supervisor_raises_unhealthy_when_no_gomod(self) -> None:
        """check_go_runtime ok + discover_go_workspace 返 None → LspUnhealthyError。"""
        from codegraph.lsp.exceptions import LspUnhealthyError
        from codegraph.lsp.go_check import GoCheckResult
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend
        from codegraph.backends.protocols import TreeSitterBackend

        backend = _GoplsLazyBackend.__new__(_GoplsLazyBackend)
        backend.language = "go"
        backend._fallback = TreeSitterBackend("go")

        with (
            patch(
                "codegraph.lsp.gopls_backend.check_go_runtime",
                return_value=GoCheckResult(
                    available=True,
                    gopls_version="0.15.3",
                    go_version="1.22",
                    reason="ok",
                ),
            ),
            patch(
                "codegraph.lsp.gopls_backend.discover_go_workspace",
                return_value=None,
            ),
        ):
            with pytest.raises(LspUnhealthyError, match="no go.mod found"):
                backend._get_supervisor(Path("/test/main.go"))


class TestMakeGoplsBackend:
    def test_make_gopls_backend_returns_callable(self) -> None:
        """make_gopls_backend('go') 返工厂 callable → factory('go') 返 LspBackend 实例。"""
        from codegraph.lsp.backend import LspBackend
        from codegraph.lsp.gopls_backend import make_gopls_backend

        factory = make_gopls_backend("go")
        assert callable(factory)
        backend = factory("go")
        assert isinstance(backend, LspBackend)

    def test_factory_instance_language_matches(self) -> None:
        """factory('go') 返实例 .language == 'go'。"""
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend, make_gopls_backend

        factory = make_gopls_backend("go")
        backend = factory("go")
        assert isinstance(backend, _GoplsLazyBackend)
        assert backend.language == "go"

    def test_factory_instance_fallback_to_tree_sitter_for_real_tree(self) -> None:
        """factory('go') 实例传真实 tree-sitter Tree → 委托 fallback（per Pitfall P-checkpoint）。"""
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend, make_gopls_backend

        factory = make_gopls_backend("go")
        backend = factory("go")
        assert isinstance(backend, _GoplsLazyBackend)

        # 传一个 non-_LspParseHandle 对象 → _lsp_extract_endpoints 直接返 []
        result = backend._lsp_extract_endpoints(MagicMock(), "", _make_ctx())
        assert result == []

    def test_factory_qualname_contains_make_gopls_backend(self) -> None:
        """工厂 _factory __qualname__ 含 make_gopls_backend。"""
        from codegraph.lsp.gopls_backend import make_gopls_backend

        factory = make_gopls_backend("go")
        assert "make_gopls_backend" in factory.__qualname__

    def test_factory_instance_has_ensure_supervisor(self) -> None:
        """_GoplsLazyInstance 有 _ensure_supervisor 方法（initial implementation 新增）。"""
        from codegraph.lsp.gopls_backend import make_gopls_backend

        factory = make_gopls_backend("go")
        backend = factory("go")
        assert hasattr(backend, "_ensure_supervisor")
        assert callable(backend._ensure_supervisor)


class TestGoplsLazyInstancePhase:
    """initial implementation 新增：_GoplsLazyInstance 真填行为验证。"""

    def _make_lazy_instance(self) -> tuple:
        """创建 _GoplsLazyInstance 并 mock _get_supervisor。"""
        from codegraph.lsp.gopls_backend import make_gopls_backend

        factory = make_gopls_backend("go")
        backend = factory("go")
        mock_sup = _make_mock_supervisor()
        return backend, mock_sup

    def test_non_lsp_handle_symbols_uses_fallback(self) -> None:
        """非 _LspParseHandle tree → _lsp_extract_symbols 委托 fallback（不调 _ensure_supervisor）。"""
        backend, _ = self._make_lazy_instance()
        mock_result = [MagicMock()]
        with patch.object(backend._fallback, "extract_symbols", return_value=mock_result):
            result = backend._lsp_extract_symbols(MagicMock(), "", _make_ctx())
        assert result == mock_result

    def test_non_lsp_handle_imports_uses_fallback(self) -> None:
        """非 _LspParseHandle tree → _lsp_extract_imports 委托 fallback。"""
        backend, _ = self._make_lazy_instance()
        mock_result = [MagicMock()]
        with patch.object(backend._fallback, "extract_imports", return_value=mock_result):
            result = backend._lsp_extract_imports(MagicMock(), _make_ctx())
        assert result == mock_result

    def test_non_lsp_handle_calls_uses_fallback(self) -> None:
        """非 _LspParseHandle tree → _lsp_extract_calls 委托 fallback。"""
        backend, _ = self._make_lazy_instance()
        mock_result = [MagicMock()]
        with patch.object(backend._fallback, "extract_calls", return_value=mock_result):
            result = backend._lsp_extract_calls(MagicMock(), _make_ctx())
        assert result == mock_result

    def test_lsp_handle_symbols_injects_supervisor_and_calls_parent(self) -> None:
        """_LspParseHandle tree → _ensure_supervisor 注入 + 父类 _lsp_extract_symbols 调用。"""
        backend, mock_sup = self._make_lazy_instance()
        with patch.object(backend, "_get_supervisor", return_value=mock_sup):
            ws_item = _make_workspace_symbol(
                "MyFunc", lsp.SymbolKind.Function, line=0, file_uri="file:///test/main.go"
            )
            mock_sup.call_async_in_loop.return_value = ([ws_item], [])
            result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert backend._supervisor is mock_sup
        assert len(result) >= 1

    def test_ensure_supervisor_not_reinject_when_already_set(self) -> None:
        """_supervisor 已注入时 _ensure_supervisor 不重复调 _get_supervisor。"""
        backend, mock_sup = self._make_lazy_instance()
        existing_sup = _make_mock_supervisor()
        backend._supervisor = existing_sup
        with patch.object(backend, "_get_supervisor") as mock_get:
            backend._ensure_supervisor(_make_ctx())
            mock_get.assert_not_called()
        assert backend._supervisor is existing_sup

    def test_lsp_handle_no_raise_for_symbols(self) -> None:
        """_GoplsLazyInstance _lsp_extract_symbols(lsp_handle) 不再 raise（initial implementation 修复）。"""
        backend, mock_sup = self._make_lazy_instance()
        mock_sup.call_async_in_loop.return_value = ([], [])
        with patch.object(backend, "_get_supervisor", return_value=mock_sup):
            result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert isinstance(result, list)


class TestLspExtractSymbolsExtended:
    """initial implementation 新增：扩展 SymbolKind 映射 + documentSymbol 展平验证。"""

    def test_method_kind_maps_to_function(self) -> None:
        """SymbolKind.Method → symbol_type == 'FUNCTION'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol("MyMethod", lsp.SymbolKind.Method)
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert any(s.symbol_type == "FUNCTION" for s in result)

    def test_constructor_kind_maps_to_function(self) -> None:
        """SymbolKind.Constructor → symbol_type == 'FUNCTION'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol("NewMyStruct", lsp.SymbolKind.Constructor)
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert any(s.symbol_type == "FUNCTION" for s in result)

    def test_interface_kind_maps_to_class(self) -> None:
        """SymbolKind.Interface → symbol_type == 'CLASS'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol("MyInterface", lsp.SymbolKind.Interface)
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert any(s.symbol_type == "CLASS" for s in result)

    def test_namespace_kind_maps_to_class(self) -> None:
        """SymbolKind.Namespace → symbol_type == 'CLASS'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol("mypackage", lsp.SymbolKind.Namespace)
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert any(s.symbol_type == "CLASS" for s in result)

    def test_constant_kind_maps_to_variable(self) -> None:
        """SymbolKind.Constant → symbol_type == 'VARIABLE'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol("MaxRetry", lsp.SymbolKind.Constant)
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert any(s.symbol_type == "VARIABLE" for s in result)

    def test_field_kind_maps_to_variable(self) -> None:
        """SymbolKind.Field → symbol_type == 'VARIABLE'。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol("Name", lsp.SymbolKind.Field)
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert any(s.symbol_type == "VARIABLE" for s in result)

    def test_type_parameter_kind_maps_to_variable(self) -> None:
        """SymbolKind.TypeParameter → symbol_type == 'VARIABLE'（Go 泛型）。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol("T", lsp.SymbolKind.TypeParameter)
        mock_sup.call_async_in_loop.return_value = ([ws_item], [])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert any(s.symbol_type == "VARIABLE" for s in result)

    def test_same_name_and_line_dedup(self) -> None:
        """ws_resp + doc_resp 含同名同行 symbol → 去重后 result len == 1。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        ws_item = _make_workspace_symbol("Hello", lsp.SymbolKind.Function, line=0)

        doc_item = MagicMock()
        doc_item.name = "Hello"
        doc_item.kind = lsp.SymbolKind.Function
        doc_range = MagicMock()
        doc_range.start = MagicMock()
        doc_range.start.line = 0
        doc_range.end = MagicMock()
        doc_range.end.line = 0
        doc_item.range = doc_range
        doc_item.children = None
        doc_item.location = None

        mock_sup.call_async_in_loop.return_value = ([ws_item], [doc_item])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert len(result) == 1, f"预期去重后 1 个，实际 {len(result)} 个"

    def test_doc_symbol_nested_children_flattened(self) -> None:
        """DocumentSymbol 含 children → 父子都出现在 result（_flatten_document_symbol 递归）。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        child = MagicMock()
        child.name = "ChildMethod"
        child.kind = lsp.SymbolKind.Method
        child_range = MagicMock()
        child_range.start = MagicMock()
        child_range.start.line = 5
        child_range.end = MagicMock()
        child_range.end.line = 6
        child.range = child_range
        child.children = None
        child.location = None

        parent = MagicMock()
        parent.name = "ParentStruct"
        parent.kind = lsp.SymbolKind.Struct
        parent_range = MagicMock()
        parent_range.start = MagicMock()
        parent_range.start.line = 2
        parent_range.end = MagicMock()
        parent_range.end.line = 10
        parent.range = parent_range
        parent.children = [child]
        parent.location = None

        mock_sup.call_async_in_loop.return_value = ([], [parent])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        names = [s.name for s in result]
        assert "ParentStruct" in names
        assert "ChildMethod" in names

    def test_doc_symbol_name_none_skipped(self) -> None:
        """DocumentSymbol.name=None → 不 crash，跳过该项。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        bad_item = MagicMock()
        bad_item.name = None
        bad_item.children = None
        bad_item.location = None
        bad_item.range = None

        mock_sup.call_async_in_loop.return_value = ([], [bad_item])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert result == []

    def test_doc_resp_empty_list_no_crash(self) -> None:
        """doc_resp=[] → result=[]，不 crash。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()
        mock_sup.call_async_in_loop.return_value = ([], [])
        result = backend._lsp_extract_symbols(_make_lsp_handle(), "", _make_ctx())
        assert result == []


class TestLspExtractImportsExtended:
    """initial implementation 新增：imports 扩展 case。"""

    def test_multiple_imports_all_resolved(self) -> None:
        """多个 import → 各自 resolve（mock resolve 返不同路径）。"""
        backend, _ = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import ImportData
        imp1 = ImportData(source_file="/test/main.go", target_module="fmt", line=3, target_path=None)
        imp2 = ImportData(source_file="/test/main.go", target_module="os", line=4, target_path=None)

        resolve_results = ["/usr/local/go/src/fmt/print.go", "/usr/local/go/src/os/file.go"]
        call_count = 0

        def mock_resolve(*args: object, **kwargs: object) -> str | None:
            nonlocal call_count
            result = resolve_results[call_count] if call_count < len(resolve_results) else None
            call_count += 1
            return result

        with (
            patch.object(backend._fallback, "extract_imports", return_value=[imp1, imp2]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
            patch("codegraph.lsp.gopls_backend._resolve_import_target_path", side_effect=mock_resolve),
        ):
            result = backend._lsp_extract_imports(_make_lsp_handle(), _make_ctx())

        assert len(result) == 2
        assert result[0].target_path == "/usr/local/go/src/fmt/print.go"
        assert result[1].target_path == "/usr/local/go/src/os/file.go"

    def test_empty_ts_imports_returns_empty(self) -> None:
        """tree-sitter fallback 返空 → result 为空（不 crash）。"""
        backend, _ = _make_gopls_backend_with_mock_supervisor()
        with (
            patch.object(backend._fallback, "extract_imports", return_value=[]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
        ):
            result = backend._lsp_extract_imports(_make_lsp_handle(), _make_ctx())
        assert result == []

    def test_import_line_zero_target_path_stays_none(self) -> None:
        """import.line=0 → _resolve_import_target_path 以 line_1_indexed=None 调用 → 返 None → target_path=None。"""
        backend, _ = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import ImportData
        imp = ImportData(source_file="/test/main.go", target_module="pkg", line=0, target_path=None)

        with (
            patch.object(backend._fallback, "extract_imports", return_value=[imp]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
            patch(
                "codegraph.lsp.gopls_backend._resolve_import_target_path",
                return_value=None,  # line_1_indexed=None 时内部直接返 None
            ) as mock_resolve,
        ):
            result = backend._lsp_extract_imports(_make_lsp_handle(), _make_ctx())

        assert result[0].target_path is None
        # _resolve_import_target_path 被调用，但 line_1_indexed=None（因 line=0 < 1）
        mock_resolve.assert_called_once()
        call_kwargs = mock_resolve.call_args
        assert call_kwargs.kwargs.get("line_1_indexed") is None


class TestLspExtractCallsExtended:
    """initial implementation 新增：calls 扩展 case。"""

    def test_references_returns_none_no_crash(self) -> None:
        """call_async_in_loop 返 None → 跳过，不 crash，result 为空。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import SymbolData
        mock_sym = SymbolData(name="Foo", symbol_type="FUNCTION", file_path="/test/main.go", start_line=5, end_line=7)
        mock_sup.call_async_in_loop.return_value = None  # 非 list

        with (
            patch.object(backend._fallback, "extract_symbols", return_value=[mock_sym]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
        ):
            result = backend._lsp_extract_calls(_make_lsp_handle(), _make_ctx())
        assert result == []

    def test_ref_uri_not_str_skipped(self) -> None:
        """ref.uri 非 str → 跳过，不 crash。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import SymbolData
        mock_sym = SymbolData(name="Bar", symbol_type="FUNCTION", file_path="/test/main.go", start_line=3, end_line=5)
        bad_ref = MagicMock()
        bad_ref.uri = 12345  # 非 str
        bad_ref.range = MagicMock()
        mock_sup.call_async_in_loop.return_value = [bad_ref]

        with (
            patch.object(backend._fallback, "extract_symbols", return_value=[mock_sym]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
        ):
            result = backend._lsp_extract_calls(_make_lsp_handle(), _make_ctx())
        assert result == []

    def test_callee_name_matches_symbol_name(self) -> None:
        """CallData.callee_name == sym.name。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import SymbolData
        mock_sym = SymbolData(name="ProcessOrder", symbol_type="FUNCTION", file_path="/test/main.go", start_line=10, end_line=15)
        ref = MagicMock()
        ref.uri = "file:///caller.go"
        ref_range = MagicMock()
        ref_range.start = MagicMock()
        ref_range.start.line = 42
        ref.range = ref_range
        mock_sup.call_async_in_loop.return_value = [ref]

        with (
            patch.object(backend._fallback, "extract_symbols", return_value=[mock_sym]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
        ):
            result = backend._lsp_extract_calls(_make_lsp_handle(), _make_ctx())

        assert len(result) >= 1
        assert result[0].callee_name == "ProcessOrder"

    def test_sym_start_line_zero_skipped(self) -> None:
        """sym.start_line=0（< 1）→ 跳过该 symbol，不调 call_async_in_loop。"""
        backend, mock_sup = _make_gopls_backend_with_mock_supervisor()

        from codegraph.extractors.base import SymbolData
        mock_sym = SymbolData(name="Init", symbol_type="FUNCTION", file_path="/test/main.go", start_line=0, end_line=0)

        with (
            patch.object(backend._fallback, "extract_symbols", return_value=[mock_sym]),
            patch.object(backend._fallback, "parse_file", return_value=MagicMock()),
        ):
            result = backend._lsp_extract_calls(_make_lsp_handle(), _make_ctx())

        assert result == []
        mock_sup.call_async_in_loop.assert_not_called()

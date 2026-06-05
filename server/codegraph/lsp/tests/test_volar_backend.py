"""initial implementation: VolarBackend + helper 单元测试（≥ 12 测试覆盖 V1/V2/V3/V4 契约）。

per implementation plan Task 3 acceptance：
- ClassVar 5 字段值 + ExtractorBackend Protocol 契约（V1）
- 4 hook 转换：symbols / imports / calls / endpoints
- helper：_convert_to_symbol_data / _convert_workspace_symbol /
  _flatten_document_symbol / _resolve_import_target_path /
  _extract_first_location_path / _convert_references_to_call_data
- LspTimeoutError 走基类 fallback（per initial implementation 模板方法）
- make_volar_backend 闭包返 callable
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from lsprotocol import types as lsp

from codegraph.backends.protocols import ExtractorBackend, TreeSitterBackend
from codegraph.extractors.base import (
    CallData,
    FileContext,
    ImportData,
    SymbolData,
)
from codegraph.lsp.exceptions import LspTimeoutError
from codegraph.lsp.protocol import path_to_uri
from codegraph.lsp.supervisor import LspSupervisor
from codegraph.lsp.volar_backend import (
    VolarBackend,
    _convert_references_to_call_data,
    _convert_to_symbol_data,
    _extract_first_location_path,
    _resolve_import_target_path,
    make_volar_backend,
)


@pytest.fixture
def file_ctx(tmp_path: Path) -> FileContext:
    f = tmp_path / "App.vue"
    f.write_text("<script setup lang='ts'>\n</script>\n")
    return FileContext(file_path=str(f), language="vue", repository_id="r1")


@pytest.fixture
def mock_supervisor() -> MagicMock:
    sup = MagicMock(spec=LspSupervisor)
    sup.name = "volar:test"
    return sup


def test_volar_backend_classvar_fields() -> None:
    """V1：5 ClassVar 字段值。"""
    assert VolarBackend.name == "volar"
    assert VolarBackend.language_ids == [
        "vue",
        "typescript",
        "typescriptreact",
        "javascript",
        "javascriptreact",
    ]
    assert VolarBackend.command == ["vue-language-server", "--stdio"]
    assert VolarBackend.initialization_options is not None
    assert VolarBackend.initialization_options["typescript"]["tsdk"] is None
    assert VolarBackend.initialization_options["vue"]["hybridMode"] is False


def test_volar_backend_implements_extractor_backend_protocol(
    mock_supervisor: MagicMock,
) -> None:
    """V1：VolarBackend 实例 isinstance ExtractorBackend Protocol。"""
    backend = VolarBackend(language="vue", supervisor=mock_supervisor)
    assert isinstance(backend, ExtractorBackend)


def test_lsp_extract_endpoints_always_returns_empty(
    mock_supervisor: MagicMock, file_ctx: FileContext
) -> None:
    """前端无 endpoint：直接返 [] 不调 LSP。"""
    backend = VolarBackend(language="vue", supervisor=mock_supervisor)
    result = backend._lsp_extract_endpoints(None, "<source>", file_ctx)
    assert result == []
    mock_supervisor.call_async_in_loop.assert_not_called()


def test_lsp_extract_symbols_calls_workspace_and_document(
    mock_supervisor: MagicMock, file_ctx: FileContext
) -> None:
    """V2：_lsp_extract_symbols 调 supervisor.call_async_in_loop 一次拿 (ws, doc)。"""
    target_uri = path_to_uri(Path(file_ctx.file_path).resolve())
    ws_resp = [
        lsp.SymbolInformation(
            name="OIButton",
            kind=lsp.SymbolKind.Class,
            location=lsp.Location(
                uri=target_uri,
                range=lsp.Range(
                    start=lsp.Position(line=10, character=0),
                    end=lsp.Position(line=20, character=0),
                ),
            ),
        )
    ]
    doc_resp: list[Any] = []
    mock_supervisor.call_async_in_loop.return_value = (ws_resp, doc_resp)

    backend = VolarBackend(language="vue", supervisor=mock_supervisor)
    result = backend._lsp_extract_symbols(None, "<source>", file_ctx)
    assert mock_supervisor.call_async_in_loop.call_count == 1
    assert len(result) == 1
    assert result[0].name == "OIButton"
    assert result[0].symbol_type == "CLASS"
    assert result[0].start_line == 11  # LSP 0-indexed → 1-indexed


def test_convert_workspace_symbol_to_symbol_data(file_ctx: FileContext) -> None:
    """V2：WorkspaceSymbol（kind=Class）→ SymbolData(symbol_type="CLASS")。"""
    target_uri = path_to_uri(Path(file_ctx.file_path).resolve())
    ws = [
        lsp.SymbolInformation(
            name="MyClass",
            kind=lsp.SymbolKind.Class,
            location=lsp.Location(
                uri=target_uri,
                range=lsp.Range(
                    start=lsp.Position(line=4, character=0),
                    end=lsp.Position(line=8, character=0),
                ),
            ),
        )
    ]
    result = _convert_to_symbol_data(ws, [], file_ctx)
    assert len(result) == 1
    assert result[0].name == "MyClass"
    assert result[0].symbol_type == "CLASS"
    assert result[0].start_line == 5
    assert result[0].end_line == 9


def test_convert_workspace_symbol_filters_other_files(file_ctx: FileContext) -> None:
    """V2：location.uri 不属于 ctx.file_path 的 ws_symbol 应被过滤。"""
    other_uri = "file:///some/other/file.ts"
    ws = [
        lsp.SymbolInformation(
            name="External",
            kind=lsp.SymbolKind.Function,
            location=lsp.Location(
                uri=other_uri,
                range=lsp.Range(
                    start=lsp.Position(line=0, character=0),
                    end=lsp.Position(line=0, character=0),
                ),
            ),
        )
    ]
    result = _convert_to_symbol_data(ws, [], file_ctx)
    assert result == []


def test_convert_document_symbol_nested_flattened(file_ctx: FileContext) -> None:
    """V2：DocumentSymbol(name=parent, children=[child]) → 2 SymbolData 展平。"""
    child = lsp.DocumentSymbol(
        name="child",
        kind=lsp.SymbolKind.Method,
        range=lsp.Range(
            start=lsp.Position(line=2, character=0),
            end=lsp.Position(line=4, character=0),
        ),
        selection_range=lsp.Range(
            start=lsp.Position(line=2, character=0),
            end=lsp.Position(line=2, character=5),
        ),
    )
    parent = lsp.DocumentSymbol(
        name="parent",
        kind=lsp.SymbolKind.Class,
        range=lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=10, character=0),
        ),
        selection_range=lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=6),
        ),
        children=[child],
    )
    result = _convert_to_symbol_data([], [parent], file_ctx)
    names = [s.name for s in result]
    assert "parent" in names
    assert "child" in names


def test_lsp_position_to_tree_sitter_line_offset(file_ctx: FileContext) -> None:
    """V2 转换契约：LSP line=12（0-indexed）→ SymbolData.start_line=13（1-indexed）。"""
    sym = lsp.DocumentSymbol(
        name="foo",
        kind=lsp.SymbolKind.Function,
        range=lsp.Range(
            start=lsp.Position(line=12, character=0),
            end=lsp.Position(line=15, character=0),
        ),
        selection_range=lsp.Range(
            start=lsp.Position(line=12, character=0),
            end=lsp.Position(line=12, character=3),
        ),
    )
    result = _convert_to_symbol_data([], [sym], file_ctx)
    assert result[0].start_line == 13
    assert result[0].end_line == 16


def test_lsp_extract_imports_double_layer(
    mock_supervisor: MagicMock, monkeypatch: pytest.MonkeyPatch, file_ctx: FileContext
) -> None:
    """V4：tree-sitter raw + LSP definition → ImportData.target_path 填值。"""
    fake_fallback = MagicMock(spec=ExtractorBackend)
    fake_fallback.parse_file.return_value = "fake_tree"
    fake_fallback.extract_imports.return_value = [
        ImportData(
            source_file=file_ctx.file_path,
            target_module="@/utils",
            imported_names=["sayHello"],
            line=2,
        )
    ]

    backend = VolarBackend(
        language="vue",
        supervisor=mock_supervisor,
        fallback=fake_fallback,
    )

    target_uri = "file:///x/utils.ts"
    location = lsp.Location(
        uri=target_uri,
        range=lsp.Range(
            start=lsp.Position(line=0, character=0),
            end=lsp.Position(line=0, character=10),
        ),
    )
    mock_supervisor.call_async_in_loop.return_value = location

    tree = backend.parse_file(file_ctx.file_path, "import { sayHello } from '@/utils'\n")
    result = backend._lsp_extract_imports(tree, file_ctx)
    assert len(result) == 1
    assert result[0].target_path == "/x/utils.ts"


def test_resolve_import_target_path_returns_none_on_lsp_error(
    mock_supervisor: MagicMock,
) -> None:
    """V4：LSP definition raise → _resolve_import_target_path 返 None。"""
    mock_supervisor.call_async_in_loop.side_effect = LspTimeoutError("boom")
    result = _resolve_import_target_path(
        supervisor=mock_supervisor,
        uri="file:///x/App.vue",
        line_1_indexed=5,
        timeout=2.0,
    )
    assert result is None


def test_resolve_import_target_path_handles_invalid_line() -> None:
    """V4：line<1 / None → 直接返 None 不调 LSP。"""
    mock_sup = MagicMock(spec=LspSupervisor)
    assert _resolve_import_target_path(
        supervisor=mock_sup, uri="file:///x", line_1_indexed=None, timeout=1.0
    ) is None
    assert _resolve_import_target_path(
        supervisor=mock_sup, uri="file:///x", line_1_indexed=0, timeout=1.0
    ) is None
    mock_sup.call_async_in_loop.assert_not_called()


@pytest.mark.parametrize(
    "def_resp, expected",
    [
        (
            lsp.Location(
                uri="file:///x/utils.ts",
                range=lsp.Range(
                    start=lsp.Position(line=0, character=0),
                    end=lsp.Position(line=0, character=10),
                ),
            ),
            "/x/utils.ts",
        ),
        (
            [
                lsp.Location(
                    uri="file:///y/a.ts",
                    range=lsp.Range(
                        start=lsp.Position(line=0, character=0),
                        end=lsp.Position(line=0, character=5),
                    ),
                )
            ],
            "/y/a.ts",
        ),
        ([], None),
        (None, None),
    ],
)
def test_extract_first_location_path_handles_three_shapes(
    def_resp: object, expected: str | None
) -> None:
    """V4：Location single / Location list / 空 list / None 四形态。"""
    assert _extract_first_location_path(def_resp) == expected


def test_convert_references_filters_callee_self(tmp_path: Path) -> None:
    """V3 + Pitfall P-checkpoint：refs 含 callee 自身 location 应被过滤。"""
    callee_file = tmp_path / "callee.ts"
    callee_file.write_text("export function foo() {}\n")
    callee_uri = path_to_uri(callee_file.resolve())

    caller_file = tmp_path / "caller.ts"
    caller_file.write_text("import { foo } from './callee'; foo();\n")
    caller_uri = path_to_uri(caller_file.resolve())

    refs = [
        lsp.Location(  # callee 自身（应过滤）
            uri=callee_uri,
            range=lsp.Range(
                start=lsp.Position(line=4, character=0),
                end=lsp.Position(line=4, character=3),
            ),
        ),
        lsp.Location(  # 跨文件 caller（保留）
            uri=caller_uri,
            range=lsp.Range(
                start=lsp.Position(line=0, character=0),
                end=lsp.Position(line=0, character=3),
            ),
        ),
    ]
    result = _convert_references_to_call_data(
        refs,
        callee_symbol="foo",
        callee_file_path=str(callee_file),
        callee_line=5,  # 1-indexed line=5 → LSP line=4
    )
    assert len(result) == 1
    assert result[0].callee_name == "foo"
    assert result[0].caller_key[0] == str(caller_file.resolve())


def test_lsp_timeout_falls_through_to_fallback(
    mock_supervisor: MagicMock, file_ctx: FileContext
) -> None:
    """LspTimeoutError 在 _lsp_extract_symbols 未 try/except → 基类 extract_symbols 捕获 → 调 fallback.extract_symbols。"""
    fake_fallback = MagicMock(spec=ExtractorBackend)
    fake_fallback.parse_file.return_value = "fake_tree"
    fake_fallback.extract_symbols.return_value = [
        SymbolData(
            name="FallbackSymbol",
            symbol_type="FUNCTION",
            file_path=file_ctx.file_path,
            start_line=1,
            end_line=2,
        )
    ]

    backend = VolarBackend(
        language="vue", supervisor=mock_supervisor, fallback=fake_fallback
    )
    mock_supervisor.call_async_in_loop.side_effect = LspTimeoutError("symbol timeout")

    handle = backend.parse_file(file_ctx.file_path, "<source>")
    result = backend.extract_symbols(handle, "<source>", file_ctx)
    assert len(result) == 1
    assert result[0].name == "FallbackSymbol"


def test_make_volar_backend_returns_callable() -> None:
    """make_volar_backend('vue') 返 callable + 调用返 ExtractorBackend 实例（lazy 占位）。"""
    factory = make_volar_backend("vue")
    assert callable(factory)
    backend = factory("vue")
    assert isinstance(backend, ExtractorBackend)
    assert hasattr(backend, "extract_symbols")
    # lazy 实例：parse_file 走基类返 _LspParseHandle；extract_symbols 因 raise → fallback
    handle = backend.parse_file("/tmp/dummy.vue", "<source>")
    ctx = FileContext(file_path="/tmp/dummy.vue", language="vue", repository_id="r1")
    # 应该不抛异常（基类 try/except + TreeSitterBackend fallback）
    result = backend.extract_endpoints(handle, "<source>", ctx)
    assert result == []  # endpoint 直接 return []


def test_make_volar_backend_factory_qualname_contains_marker() -> None:
    """factory.__qualname__ 含 make_volar_backend 字面便于运维 grep。"""
    factory = make_volar_backend("vue")
    assert "make_volar_backend" in factory.__qualname__


def test_volar_backend_construct_with_default_fallback(
    mock_supervisor: MagicMock,
) -> None:
    """无 fallback 入参时默认创建 TreeSitterBackend(language)。"""
    backend = VolarBackend(language="vue", supervisor=mock_supervisor)
    assert isinstance(backend._fallback, TreeSitterBackend)
    assert backend._fallback.language == "vue"

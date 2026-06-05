"""implementation: gopls_interface.py 单元测试。

覆盖：
- InterfaceImplementationData frozen dataclass
- extract_interface_implementations：mock supervisor + LSP Location → InterfaceImplementationData
- 边界条件：空输入、非 CLASS symbol、supervisor 不可用、LspTimeoutError
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from codegraph.extractors.base import SymbolData


def _make_symbol(
    name: str = "MyInterface",
    symbol_type: str = "CLASS",
    file_path: str = "/test/main.go",
    start_line: int = 10,
) -> "SymbolData":
    from codegraph.extractors.base import SymbolData

    return SymbolData(
        name=name,
        symbol_type=symbol_type,
        file_path=file_path,
        start_line=start_line,
        end_line=start_line + 5,
    )


def _make_location(
    uri: str = "file:///impl/service.go",
    line: int = 5,
) -> MagicMock:
    """创建模拟 LSP Location。"""
    loc = MagicMock()
    loc.uri = uri
    range_obj = MagicMock()
    range_obj.start = MagicMock()
    range_obj.start.line = line
    loc.range = range_obj
    return loc


class TestInterfaceImplementationData:
    def test_frozen_dataclass_immutable(self) -> None:
        """frozen=True → 不可变（赋值 raise FrozenInstanceError）。"""
        from codegraph.lsp.gopls_interface import InterfaceImplementationData

        data = InterfaceImplementationData(
            interface_symbol_name="MyIface",
            interface_file="/test/main.go",
            impl_symbol_name="impl@service.go:10",
            impl_file="/impl/service.go",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            data.interface_symbol_name = "Other"  # type: ignore[misc]

    def test_has_four_fields(self) -> None:
        """4 字段均存在。"""
        from codegraph.lsp.gopls_interface import InterfaceImplementationData

        fields = {f.name for f in dataclasses.fields(InterfaceImplementationData)}
        assert "interface_symbol_name" in fields
        assert "interface_file" in fields
        assert "impl_symbol_name" in fields
        assert "impl_file" in fields

    def test_equality_by_value(self) -> None:
        """同值 dataclass 相等。"""
        from codegraph.lsp.gopls_interface import InterfaceImplementationData

        a = InterfaceImplementationData("A", "/a.go", "impl@b.go:1", "/b.go")
        b = InterfaceImplementationData("A", "/a.go", "impl@b.go:1", "/b.go")
        assert a == b


class TestExtractInterfaceImplementations:
    def _patch_supervisor(self, return_value: object) -> MagicMock:
        """创建 mock supervisor，call_async_in_loop 返 return_value。"""
        mock_sup = MagicMock()
        mock_sup.call_async_in_loop.return_value = return_value
        mock_sup._client = MagicMock()
        return mock_sup

    def test_empty_symbols_returns_empty(self) -> None:
        """空 interface_symbols → []，不调 supervisor。"""
        from codegraph.lsp.gopls_interface import extract_interface_implementations

        with patch("codegraph.lsp.gopls_interface.get_or_create_supervisor") as mock_factory:
            result = extract_interface_implementations(Path("/workspace"), [])

        assert result == []
        mock_factory.assert_not_called()

    def test_non_class_symbol_skipped(self) -> None:
        """symbol_type != 'CLASS' → 跳过，不调 supervisor。"""
        from codegraph.lsp.gopls_interface import extract_interface_implementations

        func_sym = _make_symbol(name="myFunc", symbol_type="FUNCTION")
        with patch("codegraph.lsp.gopls_interface.get_or_create_supervisor") as mock_factory:
            result = extract_interface_implementations(Path("/workspace"), [func_sym])

        assert result == []
        mock_factory.assert_not_called()

    def test_location_to_impl_data(self) -> None:
        """mock supervisor Location → InterfaceImplementationData 字段正确。"""
        from codegraph.lsp.gopls_interface import InterfaceImplementationData, extract_interface_implementations

        loc = _make_location(uri="file:///impl/service.go", line=9)  # 0-indexed 9 → line 10
        mock_sup = self._patch_supervisor([loc])

        with patch("codegraph.lsp.gopls_interface.get_or_create_supervisor", return_value=mock_sup):
            sym = _make_symbol(name="CourseService", symbol_type="CLASS", file_path="/test/main.go")
            result = extract_interface_implementations(Path("/workspace"), [sym])

        assert len(result) == 1
        assert isinstance(result[0], InterfaceImplementationData)
        assert result[0].interface_symbol_name == "CourseService"
        assert result[0].interface_file == "/test/main.go"
        assert "service.go" in result[0].impl_symbol_name
        assert "/impl/service.go" == result[0].impl_file

    def test_supervisor_returns_empty_list(self) -> None:
        """supervisor 返 [] → result 为空。"""
        from codegraph.lsp.gopls_interface import extract_interface_implementations

        mock_sup = self._patch_supervisor([])

        with patch("codegraph.lsp.gopls_interface.get_or_create_supervisor", return_value=mock_sup):
            sym = _make_symbol(symbol_type="CLASS")
            result = extract_interface_implementations(Path("/workspace"), [sym])

        assert result == []

    def test_supervisor_timeout_error_skipped(self) -> None:
        """supervisor raise LspTimeoutError → 跳过该 symbol，不 crash，result 为空。"""
        from codegraph.lsp.exceptions import LspTimeoutError
        from codegraph.lsp.gopls_interface import extract_interface_implementations

        mock_sup = MagicMock()
        mock_sup.call_async_in_loop.side_effect = LspTimeoutError("timeout")
        mock_sup._client = MagicMock()

        with patch("codegraph.lsp.gopls_interface.get_or_create_supervisor", return_value=mock_sup):
            sym = _make_symbol(symbol_type="CLASS")
            result = extract_interface_implementations(Path("/workspace"), [sym])

        assert result == []

    def test_invalid_uri_location_skipped(self) -> None:
        """Location.uri 无效（非 file:// URI）→ 跳过，不 crash。"""
        from codegraph.lsp.gopls_interface import extract_interface_implementations

        bad_loc = MagicMock()
        bad_loc.uri = "invalid://not-a-path"
        mock_sup = self._patch_supervisor([bad_loc])

        with patch("codegraph.lsp.gopls_interface.get_or_create_supervisor", return_value=mock_sup):
            sym = _make_symbol(symbol_type="CLASS")
            result = extract_interface_implementations(Path("/workspace"), [sym])

        assert result == []

    def test_multiple_symbols_multiple_results(self) -> None:
        """多个 CLASS symbol → 各自调 supervisor → 结果多项。"""
        from codegraph.lsp.gopls_interface import extract_interface_implementations

        loc1 = _make_location(uri="file:///impl/svc1.go", line=1)
        loc2 = _make_location(uri="file:///impl/svc2.go", line=2)

        call_count = 0
        responses = [[loc1], [loc2]]

        def side_effect(coro: object, timeout: float = 10.0) -> object:
            nonlocal call_count
            result = responses[call_count] if call_count < len(responses) else []
            call_count += 1
            return result

        mock_sup = MagicMock()
        mock_sup.call_async_in_loop.side_effect = side_effect
        mock_sup._client = MagicMock()

        with patch("codegraph.lsp.gopls_interface.get_or_create_supervisor", return_value=mock_sup):
            sym1 = _make_symbol(name="Iface1", symbol_type="CLASS", file_path="/test/a.go")
            sym2 = _make_symbol(name="Iface2", symbol_type="CLASS", file_path="/test/b.go")
            result = extract_interface_implementations(Path("/workspace"), [sym1, sym2])

        assert len(result) == 2
        names = {r.interface_symbol_name for r in result}
        assert "Iface1" in names
        assert "Iface2" in names

    def test_structlog_event_emitted(self) -> None:
        """gopls_interface_extracted structlog event 被 emit（info 级别）。"""
        from codegraph.lsp.gopls_interface import extract_interface_implementations

        mock_sup = self._patch_supervisor([])

        with (
            patch("codegraph.lsp.gopls_interface.get_or_create_supervisor", return_value=mock_sup),
            patch("codegraph.lsp.gopls_interface.logger") as mock_logger,
        ):
            sym = _make_symbol(symbol_type="CLASS")
            extract_interface_implementations(Path("/workspace"), [sym])

        mock_logger.info.assert_called()
        call_args = mock_logger.info.call_args
        assert "gopls_interface_extracted" in call_args[0]

    def test_supervisor_unavailable_returns_empty(self) -> None:
        """get_or_create_supervisor raise KeyError → result 为空，不 crash。"""
        from codegraph.lsp.gopls_interface import extract_interface_implementations

        with patch(
            "codegraph.lsp.gopls_interface.get_or_create_supervisor",
            side_effect=KeyError("no gopls config"),
        ):
            sym = _make_symbol(symbol_type="CLASS")
            result = extract_interface_implementations(Path("/workspace"), [sym])

        assert result == []

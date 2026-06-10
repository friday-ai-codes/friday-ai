"""Step 2 volar references 单元测试 —— mock LspSupervisor。

验证 resolve_call_sites_for_wrapper 在各种 volar 响应下的行为。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BASIC_TS = str(FIXTURES_DIR / "api_resolver_basic.ts")


def _make_lsp_location(file_path: str, line: int, col: int = 0) -> Any:
    """构造模拟的 LSP Location 对象。"""
    from lsprotocol import types as lsp

    uri = f"file://{file_path}"
    return lsp.Location(
        uri=uri,
        range=lsp.Range(
            start=lsp.Position(line=line, character=col),
            end=lsp.Position(line=line, character=col + 10),
        ),
    )


def _make_mock_supervisor(refs: list) -> MagicMock:
    """构造返回给定 refs 的 mock supervisor。"""
    supervisor = MagicMock()
    supervisor._client = MagicMock()
    # call_async_in_loop 同步调用，直接返回 refs
    supervisor.call_async_in_loop.return_value = refs
    return supervisor


class TestFindSymbolPosition:
    """_find_symbol_position 单元测试。"""

    def test_finds_export_function_position(self):
        """export function 名的 line/col 被正确定位（0-indexed）。"""
        from codegraph.extractors.api_resolver.detector import (
            _find_symbol_position,
            parse_ts_or_vue_for_api,
        )

        result = parse_ts_or_vue_for_api(BASIC_TS)
        assert result is not None
        tree, _ = result

        pos = _find_symbol_position(tree, "getUserInfo")
        assert pos is not None, "应找到 getUserInfo 的位置"
        line, col = pos
        assert line >= 0
        assert col >= 0

    def test_returns_none_for_nonexistent_symbol(self):
        """不存在的函数名返回 None（不 crash）。"""
        from codegraph.extractors.api_resolver.detector import (
            _find_symbol_position,
            parse_ts_or_vue_for_api,
        )

        result = parse_ts_or_vue_for_api(BASIC_TS)
        assert result is not None
        tree, _ = result

        pos = _find_symbol_position(tree, "nonExistentFunction")
        assert pos is None


class TestFindEnclosingFunction:
    """_find_enclosing_function 单元测试。"""

    def test_finds_function_at_line(self):
        """能找到包含指定行的函数名。"""
        from codegraph.extractors.api_resolver.detector import (
            _find_enclosing_function,
            _find_symbol_position,
            parse_ts_or_vue_for_api,
        )

        result = parse_ts_or_vue_for_api(BASIC_TS)
        assert result is not None
        tree, _ = result

        # 找 getUserInfo 的位置（行号），再查包含它的函数
        pos = _find_symbol_position(tree, "getUserInfo")
        assert pos is not None
        line_0indexed = pos[0]

        func_name = _find_enclosing_function(tree, line_0indexed)
        assert func_name == "getUserInfo", f"期望 getUserInfo，实际 {func_name}"

    def test_returns_none_for_module_level(self):
        """模块级代码（行 0）返回 None 或顶层函数名。"""
        from codegraph.extractors.api_resolver.detector import (
            _find_enclosing_function,
            parse_ts_or_vue_for_api,
        )

        result = parse_ts_or_vue_for_api(BASIC_TS)
        assert result is not None
        tree, _ = result

        # 行 0 可能是 import 语句（模块级），应返回 None
        func_name = _find_enclosing_function(tree, 0)
        # 第 0 行是 import axios，不在任何函数内
        assert func_name is None


class TestResolveCallSitesForWrapper:
    """resolve_call_sites_for_wrapper 单元测试（mock volar supervisor）。"""

    def _make_wrapper(self) -> Any:
        from codegraph.extractors.api_resolver.base import ApiWrapperData

        return ApiWrapperData(
            file_path=BASIC_TS,
            function_symbol="getUserInfo",
            http_method="GET",
            url_path_raw="/api/user/info",
            url_path_pattern="/api/user/info",
        )

    def test_happy_path_2_refs(self):
        """mock volar 返回 2 个 references → 生成 2 个 ApiCallSiteData。"""
        from codegraph.extractors.api_resolver.detector import resolve_call_sites_for_wrapper

        wrapper = self._make_wrapper()
        refs = [
            _make_lsp_location(BASIC_TS, 15),
            _make_lsp_location(BASIC_TS, 20),
        ]
        supervisor = _make_mock_supervisor(refs)

        with patch("codegraph.lsp.protocol.path_to_uri", return_value=f"file://{BASIC_TS}"):
            with patch("codegraph.lsp.protocol.uri_to_path", return_value=BASIC_TS):
                sites = resolve_call_sites_for_wrapper(wrapper, supervisor, timeout=5.0)

        assert len(sites) == 2
        for site in sites:
            assert site.api_wrapper_file == BASIC_TS
            assert site.api_wrapper_symbol == "getUserInfo"
            assert site.caller_file == BASIC_TS
            assert site.line_number >= 1

    def test_volar_timeout_returns_empty(self):
        """volar 超时时返回空列表（不 raise），非阻塞。"""
        from codegraph.extractors.api_resolver.detector import resolve_call_sites_for_wrapper

        wrapper = self._make_wrapper()
        supervisor = MagicMock()
        supervisor._client = MagicMock()
        supervisor.call_async_in_loop.side_effect = TimeoutError("volar timeout")

        with patch("codegraph.lsp.protocol.path_to_uri", return_value=f"file://{BASIC_TS}"):
            sites = resolve_call_sites_for_wrapper(wrapper, supervisor, timeout=1.0)

        assert sites == [], f"超时应返回空列表，实际 {sites}"

    def test_volar_returns_empty_refs(self):
        """volar 返回空列表 → 返回空列表（不 crash）。"""
        from codegraph.extractors.api_resolver.detector import resolve_call_sites_for_wrapper

        wrapper = self._make_wrapper()
        supervisor = _make_mock_supervisor([])

        with patch("codegraph.lsp.protocol.path_to_uri", return_value=f"file://{BASIC_TS}"):
            sites = resolve_call_sites_for_wrapper(wrapper, supervisor)

        assert sites == []

    def test_nonexistent_file_returns_empty(self):
        """ApiWrapper 文件不存在时返回空列表（不 crash）。"""
        from codegraph.extractors.api_resolver.base import ApiWrapperData
        from codegraph.extractors.api_resolver.detector import resolve_call_sites_for_wrapper

        wrapper = ApiWrapperData(
            file_path="/nonexistent/file.ts",
            function_symbol="someFunc",
            http_method="GET",
            url_path_raw="/api/test",
            url_path_pattern="/api/test",
        )
        supervisor = _make_mock_supervisor([])

        sites = resolve_call_sites_for_wrapper(wrapper, supervisor)
        assert sites == []

    def test_symbol_not_found_returns_empty(self):
        """函数名在 AST 中找不到时返回空列表（不 crash）。"""
        from codegraph.extractors.api_resolver.base import ApiWrapperData
        from codegraph.extractors.api_resolver.detector import resolve_call_sites_for_wrapper

        wrapper = ApiWrapperData(
            file_path=BASIC_TS,
            function_symbol="nonExistentFunction",
            http_method="GET",
            url_path_raw="/api/test",
            url_path_pattern="/api/test",
        )
        supervisor = _make_mock_supervisor([])

        with patch("codegraph.lsp.protocol.path_to_uri", return_value=f"file://{BASIC_TS}"):
            sites = resolve_call_sites_for_wrapper(wrapper, supervisor)

        assert sites == []

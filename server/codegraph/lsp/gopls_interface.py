"""initial implementation: GoplsInterfaceExtractor —— Go interface 实现关系抽取模块。

本模块提供 Go interface 实现关系的 LSP 抽取能力（textDocument/implementation）；
独立于 ExtractorBackend Protocol（per initial implementation），可由 indexer 选择性消费。

per work item 理由：
    1. ExtractorBackend Protocol 5 abstract method 不含 implementation；新增破坏既有契约
    2. interface 实现关系是 Go 独有强类型语义，volar / tree-sitter backend 无对应
    3. 独立模块让 indexer 可选择性消费，不依赖 backend 切换
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Final

import structlog
from lsprotocol import types as lsp

from codegraph.extractors.base import SymbolData
from codegraph.lsp import get_or_create_supervisor
from codegraph.lsp.exceptions import LspError, LspTimeoutError, LspUnhealthyError
from codegraph.lsp.protocol import path_to_uri, uri_to_path

logger = structlog.get_logger(__name__)

_DEFAULT_IMPLEMENTATION_TIMEOUT: Final[float] = 10.0


@dataclasses.dataclass(frozen=True)
class InterfaceImplementationData:
    """Go interface 实现关系数据（per initial implementation / work item：frozen=True）。

    Fields:
        interface_symbol_name: interface 的 Go 符号名（如 "CourseService"）
        interface_file: interface 定义所在文件绝对路径
        impl_symbol_name: 实现者的简化名（"impl@{file}:{line}" 格式）
        impl_file: 实现者所在文件绝对路径
    """

    interface_symbol_name: str
    interface_file: str
    impl_symbol_name: str
    impl_file: str


def extract_interface_implementations(
    workspace_root: Path,
    interface_symbols: list[SymbolData],
    *,
    timeout: float = _DEFAULT_IMPLEMENTATION_TIMEOUT,
) -> list[InterfaceImplementationData]:
    """抽取 Go interface 实现关系（textDocument/implementation per symbol）。

    per initial implementation：仅处理 symbol_type == "CLASS" 的 symbol（Go interface/struct
    在 initial implementation SymbolKind 映射中均为 "CLASS"）；per-symbol 调 gopls 的
    textDocument/implementation，收集所有实现该 interface 的位置。

    Args:
        workspace_root: Go 仓库根目录（含 go.mod），用于初始化 gopls supervisor。
        interface_symbols: 候选 interface symbol 列表（通常来自 extract_symbols 结果）。
        timeout: 单次 LSP 请求超时（秒），默认 10s。

    Returns:
        InterfaceImplementationData 列表；失败项跳过（不 raise）。

    Note:
        本函数复用 initial implementation get_or_create_supervisor("gopls", ...) 单例缓存；
        与 _GoplsLazyBackend._get_supervisor 使用同一 supervisor 实例（per work item）。
    """
    if not interface_symbols:
        return []

    # 仅处理 CLASS 类型（Go interface 和 struct 的 gopls SymbolKind 映射）
    candidates = [s for s in interface_symbols if s.symbol_type == "CLASS"]
    if not candidates:
        logger.debug(
            "gopls_interface_no_candidates",
            workspace_root=str(workspace_root),
            total_symbols=len(interface_symbols),
        )
        return []

    try:
        supervisor = get_or_create_supervisor("gopls", workspace_root=workspace_root)
    except (KeyError, LspUnhealthyError) as exc:
        logger.warning(
            "gopls_interface_supervisor_unavailable",
            workspace_root=str(workspace_root),
            error=str(exc),
        )
        return []

    results: list[InterfaceImplementationData] = []

    for symbol in candidates:
        try:
            uri = path_to_uri(Path(symbol.file_path).resolve())
        except (ValueError, OSError) as exc:
            logger.debug(
                "gopls_interface_uri_error",
                file_path=symbol.file_path,
                error=str(exc),
            )
            continue

        # LSP 0-indexed position（symbol.start_line 1-indexed → line - 1）
        line_0 = max(symbol.start_line - 1, 0)
        position = lsp.Position(line=line_0, character=0)

        async def _coro(
            u: str = uri,
            pos: lsp.Position = position,
            t: float = timeout,
        ) -> Any:
            client = supervisor._client
            if client is None:
                return []
            return await client.request_implementation(u, pos, timeout=t)

        try:
            impl_resp = supervisor.call_async_in_loop(_coro, timeout=timeout * 1.5)
        except (LspError, LspTimeoutError, LspUnhealthyError, Exception) as exc:  # noqa: BLE001
            logger.debug(
                "gopls_interface_request_failed",
                symbol=symbol.name,
                file_path=symbol.file_path,
                error_class=type(exc).__name__,
                error=str(exc),
            )
            continue

        if not isinstance(impl_resp, list):
            continue

        for loc in impl_resp:
            impl_data = _location_to_impl_data(symbol, loc)
            if impl_data is not None:
                results.append(impl_data)

    logger.info(
        "gopls_interface_extracted",
        workspace_root=str(workspace_root),
        interface_count=len(candidates),
        impl_count=len(results),
    )
    return results


def _location_to_impl_data(
    symbol: SymbolData,
    location: Any,
) -> InterfaceImplementationData | None:
    """LSP Location → InterfaceImplementationData（失败返 None）。"""
    uri_val = getattr(location, "uri", None) or getattr(location, "target_uri", None)
    if not isinstance(uri_val, str):
        return None

    try:
        impl_path = str(uri_to_path(uri_val))
    except ValueError:
        return None

    range_obj = getattr(location, "range", None)
    start = getattr(range_obj, "start", None)
    impl_line = int(getattr(start, "line", -1)) + 1 if start is not None else 0
    impl_line = max(impl_line, 0)

    # 实现者简化名：使用文件名 + 行号（不依赖额外 LSP 调用）
    impl_name = f"impl@{Path(impl_path).name}:{impl_line}"

    return InterfaceImplementationData(
        interface_symbol_name=symbol.name,
        interface_file=symbol.file_path,
        impl_symbol_name=impl_name,
        impl_file=impl_path,
    )


__all__ = [
    "InterfaceImplementationData",
    "extract_interface_implementations",
]

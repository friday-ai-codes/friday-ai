"""initial implementation: LspBackend 抽象基类 —— 5 模板方法 + 5 abstract hook + tree-sitter fallback。

设计要点（per work item / work item / Pitfall P14 / work item / work item）：

- **隐式遵循 ExtractorBackend Protocol**（``@runtime_checkable``）：5 个方法签名
  完全兼容 ``codegraph/backends/protocols.py::ExtractorBackend``；
  ``isinstance(LspBackendSubclass(...), ExtractorBackend) is True``。
- **模板方法模式**：4 个 ``extract_*`` 方法在基类统一 try/except 4 类 ``LspError`` 子类，
  失败时走 ``self._fallback.extract_*``（默认 ``TreeSitterBackend(language)``）。
- **5 个 abstract hook** (``_lsp_extract_symbols`` / ``_lsp_extract_imports`` /
  ``_lsp_extract_calls`` / ``_lsp_extract_endpoints`` + ``parse_file``)：
  本 phase 全部 raise ``NotImplementedError`` 含 phase 编号引导
  （266 = volar / 267 = gopls 子类落地）；这是 Phase Boundary 严格约束。
- **工厂闭包** ``make_lsp_backend(name)``：解决 ``BACKEND_REGISTRY`` 类型
  ``Callable[[str], ExtractorBackend]`` 与 ``LspBackend.__init__`` 签名差异
  （per Pitfall P14）。本 phase 工厂仅占位 raise NotImplementedError；
  initial implementation / 267 各自定义具体子类的工厂闭包。

本 phase **不**在任何模块内调 ``register_backend`` 注册 ``lsp_*`` backend；
默认全 tree_sitter，per Phase Boundary。
"""

from __future__ import annotations

import abc
import dataclasses
from collections.abc import Callable
from typing import Any, ClassVar

import structlog

from codegraph.backends.protocols import ExtractorBackend, TreeSitterBackend
from codegraph.extractors.base import (
    CallData,
    EndpointData,
    FileContext,
    ImportData,
    SymbolData,
)
from codegraph.lsp.exceptions import (
    LspDisabledError,
    LspError,
    LspTimeoutError,
    LspUnhealthyError,
)
from codegraph.lsp.supervisor import LspSupervisor

logger = structlog.get_logger(__name__)

# 4 个 fallback 事件名（与 supervisor.py 一致，per work item / V5）
_EVENT_EXTRACT_SYMBOLS_FALLBACK = "lsp_extract_symbols_fallback"
_EVENT_EXTRACT_IMPORTS_FALLBACK = "lsp_extract_imports_fallback"
_EVENT_EXTRACT_CALLS_FALLBACK = "lsp_extract_calls_fallback"
_EVENT_EXTRACT_ENDPOINTS_FALLBACK = "lsp_extract_endpoints_fallback"


@dataclasses.dataclass(frozen=True)
class _LspParseHandle:
    """LspBackend.parse_file 返回的轻量占位 handle。

    LSP backend 不需要本地 AST tree（capability 直接走 LSP server），
    但 ``ExtractorBackend`` Protocol 强制 ``parse_file`` 返一个 tree-like 对象。
    本 handle 携带 ``file_path`` + ``source`` 让 fallback 路径可重建 tree-sitter parse。
    """

    file_path: str
    source: str


class LspBackend(abc.ABC):
    """LSP 后端抽象基类（隐式遵循 ExtractorBackend Protocol）。

    子类（如 initial implementation ``VolarBackend`` / initial implementation ``GoplsBackend``）需覆写：
    - ClassVar 字段：``name`` / ``language_ids`` / ``command`` /
      ``initialization_options``（per work item）
    - 4 个 abstract hook：``_lsp_extract_*``（实装 LSP capability →
      SymbolData/ImportData/CallData/EndpointData 转换）

    基类负责：
    - 5 个 ``extract_*`` 模板方法（try/except → fallback 链）
    - parse_file 返 ``_LspParseHandle`` 占位
    - structlog fallback 4 事件触发
    """

    name: ClassVar[str]
    language_ids: ClassVar[list[str]]
    command: ClassVar[list[str]]
    initialization_options: ClassVar[dict[str, Any] | None] = None

    def __init__(
        self,
        language: str,
        supervisor: LspSupervisor,
        fallback: ExtractorBackend | None = None,
    ) -> None:
        self.language = language
        self._supervisor = supervisor
        self._fallback: ExtractorBackend = (
            fallback if fallback is not None else TreeSitterBackend(language)
        )

    # =========================================================================
    # parse_file —— 占位 handle（LSP backend 不依赖本地 AST tree）
    # =========================================================================

    def parse_file(self, file_path: str, source: str) -> Any:
        """返 ``_LspParseHandle`` 占位，兼容 ExtractorBackend Protocol。

        实际 LSP capability 走 ``supervisor.call_async_in_loop`` 在
        ``_lsp_extract_*`` 子类实现内调用；不需要本地 AST tree。
        """
        return _LspParseHandle(file_path=file_path, source=source)

    # =========================================================================
    # 4 个 extract_* 模板方法（统一 try/except + fallback）
    # =========================================================================

    def extract_symbols(
        self, tree: Any, source: str, ctx: FileContext
    ) -> list[SymbolData]:
        """从 LSP capability 抽取 symbol；失败走 tree-sitter fallback。"""
        try:
            return self._lsp_extract_symbols(tree, source, ctx)
        except (LspError, LspTimeoutError, LspUnhealthyError, LspDisabledError) as exc:
            logger.warning(
                _EVENT_EXTRACT_SYMBOLS_FALLBACK,
                language=ctx.language,
                file_path=ctx.file_path,
                error_class=type(exc).__name__,
                error=str(exc),
            )
            ts_tree = self._fallback.parse_file(ctx.file_path, source)
            return self._fallback.extract_symbols(ts_tree, source, ctx)

    def extract_imports(self, tree: Any, ctx: FileContext) -> list[ImportData]:
        """从 LSP capability 抽取 import；失败走 tree-sitter fallback。

        Imports 维度 fallback 时无 source 入参；用 ``""`` 作为占位
        （tree-sitter 在 ``parse_file`` 时本可接受空 source）。
        """
        try:
            return self._lsp_extract_imports(tree, ctx)
        except (LspError, LspTimeoutError, LspUnhealthyError, LspDisabledError) as exc:
            logger.warning(
                _EVENT_EXTRACT_IMPORTS_FALLBACK,
                language=ctx.language,
                file_path=ctx.file_path,
                error_class=type(exc).__name__,
                error=str(exc),
            )
            ts_source = self._extract_source_from_handle(tree)
            ts_tree = self._fallback.parse_file(ctx.file_path, ts_source)
            return self._fallback.extract_imports(ts_tree, ctx)

    def extract_calls(self, tree: Any, ctx: FileContext) -> list[CallData]:
        """从 LSP capability 抽取 call；失败走 tree-sitter fallback。"""
        try:
            return self._lsp_extract_calls(tree, ctx)
        except (LspError, LspTimeoutError, LspUnhealthyError, LspDisabledError) as exc:
            logger.warning(
                _EVENT_EXTRACT_CALLS_FALLBACK,
                language=ctx.language,
                file_path=ctx.file_path,
                error_class=type(exc).__name__,
                error=str(exc),
            )
            ts_source = self._extract_source_from_handle(tree)
            ts_tree = self._fallback.parse_file(ctx.file_path, ts_source)
            return self._fallback.extract_calls(ts_tree, ctx)

    def extract_endpoints(
        self, tree: Any, source: str, ctx: FileContext
    ) -> list[EndpointData]:
        """从 LSP capability 抽取 endpoint；失败走 tree-sitter fallback。"""
        try:
            return self._lsp_extract_endpoints(tree, source, ctx)
        except (LspError, LspTimeoutError, LspUnhealthyError, LspDisabledError) as exc:
            logger.warning(
                _EVENT_EXTRACT_ENDPOINTS_FALLBACK,
                language=ctx.language,
                file_path=ctx.file_path,
                error_class=type(exc).__name__,
                error=str(exc),
            )
            ts_tree = self._fallback.parse_file(ctx.file_path, source)
            return self._fallback.extract_endpoints(ts_tree, source, ctx)

    @staticmethod
    def _extract_source_from_handle(tree: Any) -> str:
        """从 ``_LspParseHandle`` 占位读 source 字段（fallback parse 用）。"""
        if isinstance(tree, _LspParseHandle):
            return tree.source
        return ""

    # =========================================================================
    # 5 个 abstract hook（本 phase 全部 NotImplementedError 含 phase 编号）
    # =========================================================================

    @abc.abstractmethod
    def _lsp_extract_symbols(
        self, tree: Any, source: str, ctx: FileContext
    ) -> list[SymbolData]:
        """子类覆写：调 textDocument/documentSymbol + workspace/symbol 转 SymbolData。

        initial implementation (volar) / initial implementation (gopls) 子类实装。
        """
        raise NotImplementedError(
            "LspBackend._lsp_extract_symbols 须由子类覆写："
            "建议走 textDocument/documentSymbol + workspace/symbol 转 SymbolData；"
            "落地 phase: 266 (volar) / 267 (gopls)"
        )

    @abc.abstractmethod
    def _lsp_extract_imports(
        self, tree: Any, ctx: FileContext
    ) -> list[ImportData]:
        """子类覆写：LSP server-specific import 解析（无标准 LSP method）。

        initial implementation (volar) / initial implementation (gopls) 子类实装。
        """
        raise NotImplementedError(
            "LspBackend._lsp_extract_imports 须由子类覆写："
            "建议走 LSP server-specific import resolution（无标准 LSP method）；"
            "落地 phase: 266 (volar) / 267 (gopls)"
        )

    @abc.abstractmethod
    def _lsp_extract_calls(
        self, tree: Any, ctx: FileContext
    ) -> list[CallData]:
        """子类覆写：调 textDocument/references + textDocument/definition 转 CallData。

        initial implementation (volar) / initial implementation (gopls) 子类实装。
        """
        raise NotImplementedError(
            "LspBackend._lsp_extract_calls 须由子类覆写："
            "建议走 textDocument/references + textDocument/definition 转 CallData；"
            "落地 phase: 266 (volar) / 267 (gopls)"
        )

    @abc.abstractmethod
    def _lsp_extract_endpoints(
        self, tree: Any, source: str, ctx: FileContext
    ) -> list[EndpointData]:
        """子类覆写：LSP server-specific endpoint 抽取（无标准 LSP method）。

        initial implementation (volar) / initial implementation (gopls) 子类实装。
        """
        raise NotImplementedError(
            "LspBackend._lsp_extract_endpoints 须由子类覆写："
            "建议结合 documentSymbol + LSP server-specific routing detection；"
            "落地 phase: 266 (volar) / 267 (gopls)"
        )


def make_lsp_backend(name: str) -> Callable[[str], LspBackend]:
    """LspBackend 工厂闭包入口（per Pitfall P14）。

    解决 ``BACKEND_REGISTRY`` 类型 ``Callable[[str], ExtractorBackend]`` 与
    ``LspBackend.__init__(language, supervisor, fallback)`` 签名差异。

    本 phase 基类工厂仅占位 raise NotImplementedError；具体子类（VolarBackend /
    GoplsBackend）在 initial implementation / 267 各自定义 ``make_volar_backend`` /
    ``make_gopls_backend`` 闭包注入 supervisor 与 backend 子类。
    """

    def _factory(language: str) -> LspBackend:
        raise NotImplementedError(
            f"make_lsp_backend('{name}') factory 须由子类自己实现（本基类工厂仅占位）；"
            f"建议在 codegraph/lsp/volar.py 或 codegraph/lsp/gopls.py 内定义 "
            f"make_volar_backend / make_gopls_backend；落地 phase: 266 / 267"
        )

    return _factory


__all__ = ["LspBackend", "_LspParseHandle", "make_lsp_backend"]

"""initial implementation: GoplsBackend —— LspBackend 子类实装（4 hook + ClassVar 覆写）+ 工厂闭包。

继承 initial implementation ``LspBackend`` 的 4 extract_* 模板方法（try/except + tree-sitter
fallback）；本模块仅实装 4 个 ``_lsp_extract_*`` abstract hook + 4 ClassVar 字段
+ ``make_gopls_backend(language)`` 工厂闭包。

per work item 4 hook 实装映射
=========================

============================  ==============================================
hook                          实装策略
============================  ==============================================
_lsp_extract_symbols          workspace/symbol(query="") + per-file
                              documentSymbol 混合 → SymbolData[]
_lsp_extract_imports          tree-sitter raw（fallback）+ textDocument/
                              definition 解 target_path → ImportData[]
_lsp_extract_calls            tree-sitter raw symbols + per-symbol references
                              全部入 CallData（per work item：initial implementation 精化）
_lsp_extract_endpoints        return []（Go 端点 initial implementation gin tree-sitter；per work item）
============================  ==============================================

per work item：gopls 复用 initial implementation ``_SUPERVISORS["gopls"]`` module-level 单例缓存
——与 initial implementation VolarPool 多实例选择**正好对称**，体现 initial implementation 双路径设计意图。

per work item：``make_gopls_backend(language)`` 工厂闭包替换 initial implementation 占位
``make_lsp_backend``；闭包内推断 go_mod_root + 从 ``get_or_create_supervisor``
（module-level 单实例）拿 supervisor + 实例化 _GoplsLazyBackend。
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Final

import structlog
from django.conf import settings
from lsprotocol import types as lsp

from codegraph.backends.protocols import ExtractorBackend, TreeSitterBackend
from codegraph.extractors.base import (
    CallData,
    EndpointData,
    FileContext,
    ImportData,
    SymbolData,
)
from codegraph.lsp.backend import LspBackend, _LspParseHandle
from codegraph.lsp.exceptions import LspError, LspTimeoutError, LspUnhealthyError
from codegraph.lsp.go_check import check_go_runtime
from codegraph.lsp.go_workspace import discover_go_workspace
from codegraph.lsp.protocol import path_to_uri, uri_to_path
from codegraph.lsp.supervisor import LspSupervisor

logger = structlog.get_logger(__name__)

# LSP SymbolKind → Friday SymbolData.symbol_type 映射（per V2 转换契约 / Pitfall P-checkpoint）
_SYMBOL_KIND_MAP: Final[dict[int, str]] = {
    # Function-like
    lsp.SymbolKind.Function.value: "FUNCTION",
    lsp.SymbolKind.Method.value: "FUNCTION",
    lsp.SymbolKind.Constructor.value: "FUNCTION",
    # Class-like（Go Struct / Interface / Module）
    lsp.SymbolKind.Class.value: "CLASS",
    lsp.SymbolKind.Interface.value: "CLASS",
    lsp.SymbolKind.Struct.value: "CLASS",
    lsp.SymbolKind.Module.value: "CLASS",
    lsp.SymbolKind.Namespace.value: "CLASS",
    # Variable-like
    lsp.SymbolKind.Variable.value: "VARIABLE",
    lsp.SymbolKind.Constant.value: "VARIABLE",
    lsp.SymbolKind.Field.value: "VARIABLE",
    lsp.SymbolKind.TypeParameter.value: "VARIABLE",  # Go 泛型（per Pitfall P-checkpoint）
    lsp.SymbolKind.Property.value: "VARIABLE",
}


class _GoplsLazyBackend(LspBackend):
    """gopls LSP backend；继承 initial implementation LspBackend + 4 hook 实装。

    initial implementation 实装 _GoplsLazyBackend 模式：闭包内 lazy 推断 go_mod_root +
    通过 get_or_create_supervisor（module-level 单例）拿 supervisor。

    per work item：gopls 单实例策略（与 initial implementation VolarPool 多实例对称）。
    """

    name: ClassVar[str] = "gopls"
    language_ids: ClassVar[list[str]] = ["go"]
    command: ClassVar[list[str]] = ["gopls", "serve"]
    initialization_options: ClassVar[dict[str, Any]] = {
        # gopls 点号格式 key（per Pitfall P-checkpoint）
        "build.directoryFilters": ["-vendor", "-node_modules"],
        "ui.diagnostic.diagnosticsDelay": "1s",
    }

    def _get_supervisor(self, file_path: Path) -> LspSupervisor:
        """获取 gopls supervisor（从 get_or_create_supervisor 拿 module-level 单例）。

        策略（per work item）：
            1. check_go_runtime() → available=False → LspUnhealthyError
            2. discover_go_workspace(repo_root) → None → LspUnhealthyError
            3. get_or_create_supervisor("gopls", workspace_root=workspace.go_mod_root)

        Args:
            file_path: 当前处理文件路径（用于推断 repo_root）。

        Raises:
            LspUnhealthyError: gopls/go 不可用，或无 go.mod。
        """
        from codegraph.lsp import get_or_create_supervisor

        check_result = check_go_runtime()
        if not check_result.available:
            raise LspUnhealthyError(
                f"gopls runtime 检测失败：{check_result.reason}"
            )

        repo_root = _find_repo_root(file_path)
        workspace = discover_go_workspace(repo_root)
        if workspace is None:
            raise LspUnhealthyError(
                f"no go.mod found starting from {repo_root}；"
                "gopls supervisor 无法初始化"
            )

        return get_or_create_supervisor(
            "gopls",
            workspace_root=workspace.go_mod_root,
        )

    def _lsp_extract_symbols(
        self, tree: Any, source: str, ctx: FileContext  # noqa: ARG002
    ) -> list[SymbolData]:
        """workspace/symbol + documentSymbol 混合策略（per work item / V2）。

        异常路径不 try/except；让 initial implementation LspBackend.extract_symbols 基类捕获 +
        fallback tree-sitter（per work item）。
        """
        timeout = float(getattr(settings, "LSP_REQUEST_TIMEOUT_SECONDS", 10))
        uri = path_to_uri(Path(ctx.file_path).resolve())
        supervisor = self._supervisor

        async def _coro() -> tuple[Any, Any]:
            client = supervisor._client
            if client is None:
                raise LspUnhealthyError(
                    f"gopls supervisor '{supervisor.name}' client 未启动"
                )
            ws_resp = await client.request_workspace_symbol("", timeout=timeout)
            doc_resp = await client.request_document_symbol(uri, timeout=timeout)
            return ws_resp, doc_resp

        ws_resp, doc_resp = supervisor.call_async_in_loop(_coro, timeout=timeout * 2)
        return _convert_to_symbol_data(ws_resp, doc_resp, ctx)

    def _lsp_extract_imports(
        self, tree: Any, ctx: FileContext
    ) -> list[ImportData]:
        """tree-sitter raw + textDocument/definition 双层（per work item）。

        策略：
            1. 复用 self._fallback.extract_imports 抽 raw ImportData[]
            2. per import 调 textDocument/definition 解 target_path 绝对路径
            3. 失败时 target_path=None 让上层走 raw specifier
        """
        source = self._extract_source_from_handle(tree)
        ts_tree = self._fallback.parse_file(ctx.file_path, source)
        ts_imports = self._fallback.extract_imports(ts_tree, ctx)

        timeout = float(getattr(settings, "LSP_REQUEST_TIMEOUT_SECONDS", 10))
        uri = path_to_uri(Path(ctx.file_path).resolve())
        resolved: list[ImportData] = []
        for imp in ts_imports:
            line_val = getattr(imp, "line", 0) or 0
            target_path = _resolve_import_target_path(
                supervisor=self._supervisor,
                uri=uri,
                line_1_indexed=line_val if line_val >= 1 else None,
                timeout=timeout,
            )
            if target_path is not None:
                resolved.append(dataclasses.replace(imp, target_path=target_path))
            else:
                resolved.append(imp)
        return resolved

    def _lsp_extract_calls(
        self, tree: Any, ctx: FileContext
    ) -> list[CallData]:
        """per-symbol textDocument/references 反向追踪（per work item / work item）。

        per work item：initial implementation 简化——全部 reference 入 CallData；
        initial implementation 精化 cross-file caller 解析。
        策略：
            1. 从 tree-sitter fallback 抽 raw symbols（省 LSP 调用轮次）
            2. per symbol 调 textDocument/references 拿 caller 列表
            3. 转 CallData（不区分 type reference，全入 calls）
        """
        source = self._extract_source_from_handle(tree)
        ts_tree = self._fallback.parse_file(ctx.file_path, source)
        ts_symbols = self._fallback.extract_symbols(ts_tree, source, ctx)

        timeout = float(getattr(settings, "LSP_REQUEST_TIMEOUT_SECONDS", 10))
        uri = path_to_uri(Path(ctx.file_path).resolve())
        supervisor = self._supervisor
        result: list[CallData] = []

        for sym in ts_symbols:
            sym_line = getattr(sym, "start_line", 0) or 0
            if sym_line < 1:
                continue
            position = lsp.Position(line=sym_line - 1, character=0)

            async def _coro(pos: lsp.Position = position) -> Any:
                client = supervisor._client
                if client is None:
                    return []
                return await client.request_references(
                    uri, pos, include_declaration=False, timeout=timeout
                )

            try:
                refs = supervisor.call_async_in_loop(_coro, timeout=timeout * 1.5)
            except (LspError, LspTimeoutError, LspUnhealthyError):
                continue

            if not isinstance(refs, list):
                continue
            for ref in refs:
                ref_uri = getattr(ref, "uri", None) or getattr(ref, "target_uri", None)
                if not isinstance(ref_uri, str):
                    continue
                try:
                    caller_path = str(uri_to_path(ref_uri))
                except ValueError:
                    continue
                range_obj = getattr(ref, "range", None)
                caller_line = (
                    int(getattr(getattr(range_obj, "start", None), "line", -1)) + 1
                    if range_obj is not None
                    else 0
                )
                result.append(
                    CallData(
                        caller_key=(caller_path, "", max(caller_line, 0)),
                        callee_name=getattr(sym, "name", ""),
                        call_type="DIRECT",
                        line_number=max(caller_line, 0),
                    )
                )
        return result

    def _lsp_extract_endpoints(
        self, tree: Any, source: str, ctx: FileContext  # noqa: ARG002
    ) -> list[EndpointData]:
        """Go 端点 initial implementation gin tree-sitter 处理；本 phase 直接 return []（per work item）。"""
        return []


# =============================================================================
# 转换 helper（per V2 / V3 契约 —— 镜像 volar_backend.py）
# =============================================================================


def _convert_to_symbol_data(
    ws_resp: Any, doc_resp: Any, ctx: FileContext
) -> list[SymbolData]:
    """LSP WorkspaceSymbol[] + DocumentSymbol[] → SymbolData[]（per V2 契约）。

    - workspace_symbol：过滤 location.uri 不属于 ctx.file_path 的项
    - documentSymbol：递归展平 nested children
    - position.line LSP 0-indexed → SymbolData.start_line / end_line 1-indexed
    - kind → SymbolData.symbol_type via _SYMBOL_KIND_MAP，未知映射默认 "FUNCTION"
    - 同名 + 同行去重
    """
    file_path = ctx.file_path
    target_uri: str | None = None
    try:
        target_uri = path_to_uri(Path(file_path).resolve())
    except (ValueError, OSError):
        target_uri = None

    seen: set[tuple[str, int]] = set()
    result: list[SymbolData] = []

    if isinstance(ws_resp, list):
        for item in ws_resp:
            sd = _convert_workspace_symbol(item, file_path, target_uri)
            if sd is None:
                continue
            key = (sd.name, sd.start_line)
            if key in seen:
                continue
            seen.add(key)
            result.append(sd)

    if isinstance(doc_resp, list):
        for item in doc_resp:
            for sd in _flatten_document_symbol(item, file_path):
                key = (sd.name, sd.start_line)
                if key in seen:
                    continue
                seen.add(key)
                result.append(sd)

    return result


def _convert_workspace_symbol(
    item: Any, file_path: str, target_uri: str | None
) -> SymbolData | None:
    """``WorkspaceSymbol | SymbolInformation`` → ``SymbolData``。"""
    location: Any = getattr(item, "location", None)
    if location is None:
        return None
    item_uri = getattr(location, "uri", None) or getattr(location, "target_uri", None)
    if isinstance(item_uri, str) and target_uri and item_uri != target_uri:
        return None

    name = getattr(item, "name", None)
    if not isinstance(name, str):
        return None

    kind = getattr(item, "kind", None)
    kind_value = getattr(kind, "value", kind) if kind is not None else None
    # 未知 kind → 默认 "FUNCTION"（per Pitfall P-checkpoint）
    symbol_type = (
        _SYMBOL_KIND_MAP.get(int(kind_value), "FUNCTION") if kind_value is not None else "FUNCTION"
    )

    range_obj = getattr(location, "range", None)
    start_line, end_line = _read_range_lines(range_obj)
    return SymbolData(
        name=name,
        symbol_type=symbol_type,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
    )


def _flatten_document_symbol(
    item: Any, file_path: str
) -> list[SymbolData]:
    """递归展平 ``DocumentSymbol`` nested children。"""
    result: list[SymbolData] = []
    name = getattr(item, "name", None)
    if not isinstance(name, str):
        return result

    kind = getattr(item, "kind", None)
    kind_value = getattr(kind, "value", kind) if kind is not None else None
    symbol_type = (
        _SYMBOL_KIND_MAP.get(int(kind_value), "FUNCTION")
        if kind_value is not None
        else "FUNCTION"
    )

    range_obj = getattr(item, "range", None) or getattr(
        getattr(item, "location", None), "range", None
    )
    start_line, end_line = _read_range_lines(range_obj)

    result.append(
        SymbolData(
            name=name,
            symbol_type=symbol_type,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        )
    )

    children = getattr(item, "children", None)
    if isinstance(children, list):
        for child in children:
            result.extend(_flatten_document_symbol(child, file_path))
    return result


def _read_range_lines(range_obj: Any) -> tuple[int, int]:
    """LSP ``Range`` → ``(start_line, end_line)`` 1-indexed（缺失返 (0, 0)）。"""
    if range_obj is None:
        return 0, 0
    start = getattr(range_obj, "start", None)
    end = getattr(range_obj, "end", None)
    s_line = int(getattr(start, "line", -1)) + 1 if start is not None else 0
    e_line = int(getattr(end, "line", -1)) + 1 if end is not None else 0
    return max(s_line, 0), max(e_line, 0)


def _resolve_import_target_path(
    supervisor: LspSupervisor,
    uri: str,
    line_1_indexed: int | None,
    timeout: float,
) -> str | None:
    """tree-sitter ImportData.line → ``textDocument/definition`` → 绝对路径。

    per Pitfall P-checkpoint / P-267 Go 版本：character=0 在多数 import 行有效。
    """
    if line_1_indexed is None or line_1_indexed < 1:
        return None
    position = lsp.Position(line=line_1_indexed - 1, character=0)

    async def _coro() -> Any:
        client = supervisor._client
        if client is None:
            return None
        return await client.request_definition(uri, position, timeout=timeout)

    try:
        def_resp = supervisor.call_async_in_loop(_coro, timeout=timeout * 1.5)
    except (LspError, LspTimeoutError, LspUnhealthyError):
        return None
    return _extract_first_location_path(def_resp)


def _extract_first_location_path(def_resp: Any) -> str | None:
    """``Location | Location[] | LocationLink[]`` → 首项 fsPath 字符串。"""
    if def_resp is None:
        return None
    if isinstance(def_resp, list):
        if not def_resp:
            return None
        first = def_resp[0]
    else:
        first = def_resp
    uri_val = getattr(first, "uri", None) or getattr(first, "target_uri", None)
    if not isinstance(uri_val, str):
        return None
    try:
        return str(uri_to_path(uri_val))
    except ValueError:
        return None


def _find_repo_root(file_path: Path) -> Path:
    """从文件路径 walk up 找含 go.mod 的最近父目录，或返回文件所在目录。

    过滤 vendor/ / node_modules/ 路径；找不到 go.mod 则返 file_path.parent（
    让 discover_go_workspace 走一级扫描）。
    """
    try:
        candidate = file_path.resolve().parent
    except (ValueError, OSError):
        return Path.cwd()
    for ancestor in (candidate, *candidate.parents):
        if "vendor" in ancestor.parts or "node_modules" in ancestor.parts:
            continue
        if (ancestor / "go.mod").exists() or (ancestor / "go.work").exists():
            return ancestor
    return candidate


# =============================================================================
# 工厂闭包（per work item / work item）
# =============================================================================


def make_gopls_backend(language: str = "go") -> Callable[[str], ExtractorBackend]:
    """工厂闭包 —— 替换 initial implementation 占位 ``make_lsp_backend``（gopls 版本）。

    返回的工厂签名 ``Callable[[str], ExtractorBackend]`` 与 ``BACKEND_REGISTRY`` 类型
    严格对齐；闭包内 lazy 推断 go_mod_root + 通过 ``get_or_create_supervisor``
    （module-level 单例）拿 supervisor + 实例化 _GoplsLazyBackend。

    per work item：gopls 单实例策略——与 initial implementation VolarPool 多实例选择正好对称；
    用尽了 initial implementation 双路径设计意图。

    Args:
        language: BACKEND_REGISTRY key 期望的语言（"go"）

    Returns:
        ``_factory(actual_language: str)``：实际语言由调用方传

    Note:
        per Pitfall P-checkpoint：闭包内 _GoplsLazyBackend 沿用 initial implementation VolarLazyBackend
        同模式处理 handle 入参检测（_LspParseHandle vs 真实 tree-sitter Tree）。
    """
    captured_language = language

    def _factory(actual_language: str) -> ExtractorBackend:
        from codegraph.lsp.exceptions import LspUnhealthyError as _LspUE

        class _GoplsLazyInstance(_GoplsLazyBackend):
            """工厂路径 gopls lazy backend：首次 LSP 调用时延迟注入 supervisor。

            per initial implementation：4 hook 真实调用（去占位 raise）；
            per Pitfall P-checkpoint：非 LSP handle 入参时直接委托 fallback。

            策略：_ensure_supervisor(ctx) 在首次 LSP 调用时延迟调 _get_supervisor，
            注入后父类 _lsp_extract_* 可直接使用 self._supervisor。
            """

            def __init__(self, lang: str) -> None:
                # 故意不调 super().__init__()：LspBackend.__init__ 要求 supervisor 立即注入，
                # 但此 lazy 实例通过 _get_supervisor() 在首次 extract_* 时延迟决定 supervisor。
                # per Pitfall P-checkpoint：与 initial implementation _VolarLazyBackend 同模式。
                self.language = lang
                self._supervisor: LspSupervisor = None  # type: ignore[assignment]
                self._fallback: ExtractorBackend = TreeSitterBackend(lang)
                self._supervisor_lock = threading.Lock()  # W-01 线程安全

            @staticmethod
            def _is_lsp_handle(tree: Any) -> bool:
                return isinstance(tree, _LspParseHandle)

            def _ensure_supervisor(self, ctx: FileContext) -> None:
                """首次 LSP 调用时延迟注入 supervisor（initial implementation 真填策略）。

                若 _supervisor 已注入则跳过；否则调 _get_supervisor(file_path)。
                使用 _supervisor_lock 确保多线程安全（per Review W-01）。
                失败时 raise LspUnhealthyError → 上层基类 fallback。
                """
                if self._supervisor is not None:
                    return
                with self._supervisor_lock:
                    if self._supervisor is None:
                        self._supervisor = self._get_supervisor(Path(ctx.file_path))
                        logger.debug(
                            "go_backend_supervisor_injected",
                            file_path=ctx.file_path,
                            supervisor_name=getattr(self._supervisor, "name", "unknown"),
                        )

            def _lsp_extract_symbols(
                self, tree: Any, source: str, ctx: FileContext
            ) -> list[SymbolData]:
                if not self._is_lsp_handle(tree):
                    return self._fallback.extract_symbols(tree, source, ctx)
                self._ensure_supervisor(ctx)
                return super()._lsp_extract_symbols(tree, source, ctx)

            def _lsp_extract_imports(
                self, tree: Any, ctx: FileContext
            ) -> list[ImportData]:
                if not self._is_lsp_handle(tree):
                    return self._fallback.extract_imports(tree, ctx)
                self._ensure_supervisor(ctx)
                return super()._lsp_extract_imports(tree, ctx)

            def _lsp_extract_calls(
                self, tree: Any, ctx: FileContext
            ) -> list[CallData]:
                if not self._is_lsp_handle(tree):
                    return self._fallback.extract_calls(tree, ctx)
                self._ensure_supervisor(ctx)
                return super()._lsp_extract_calls(tree, ctx)

            def _lsp_extract_endpoints(
                self, tree: Any, source: str, ctx: FileContext  # noqa: ARG002
            ) -> list[EndpointData]:
                return []

        target_language = actual_language or captured_language
        return _GoplsLazyInstance(target_language)

    _factory.__qualname__ = f"make_gopls_backend.<locals>._factory[{language}]"
    return _factory


__all__ = [
    "_GoplsLazyBackend",
    "make_gopls_backend",
    "_convert_to_symbol_data",
    "_resolve_import_target_path",
    "_extract_first_location_path",
    "_find_repo_root",
]

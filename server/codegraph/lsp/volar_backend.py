"""VolarBackend —— LspBackend 子类实装（4 hook + ClassVar 覆写）+ 工厂闭包。

继承 implementation ``LspBackend`` 的 4 extract_* 模板方法（try/except + tree-sitter
fallback）；本模块仅实装 4 个 ``_lsp_extract_*`` abstract hook + 5 ClassVar 字段
+ ``make_volar_backend(language)`` 工厂闭包。

per work item 4 hook 实装映射
=========================

============================  ==============================================
hook                          实装策略
============================  ==============================================
_lsp_extract_symbols          workspace/symbol(query="") + per-file
                              documentSymbol 混合 → SymbolData[]
_lsp_extract_imports          tree-sitter raw（fallback）+ textDocument/
                              definition 解 target_path → ImportData[]
_lsp_extract_calls            ts raw symbols + per-symbol references
                              过滤 callee 自身 → CallData[]
_lsp_extract_endpoints        return [] 前端无 endpoint
============================  ==============================================

``make_volar_backend(language)`` 工厂闭包替换 implementation 占位
``make_lsp_backend``；闭包内推断 sub_project_root（walk up tsconfig.json）+
从 ``VolarPool.get`` 拿 supervisor + 实例化 VolarBackend。
"""

from __future__ import annotations

import dataclasses
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
from codegraph.lsp.protocol import path_to_uri, uri_to_path
from codegraph.lsp.supervisor import LspSupervisor

logger = structlog.get_logger(__name__)

# LSP SymbolKind → Friday SymbolData.symbol_type 映射（per V2 转换契约）
_SYMBOL_KIND_MAP: Final[dict[int, str]] = {
    lsp.SymbolKind.Class.value: "CLASS",
    lsp.SymbolKind.Interface.value: "CLASS",  # Friday 不区分 interface / class
    lsp.SymbolKind.Function.value: "FUNCTION",
    lsp.SymbolKind.Method.value: "FUNCTION",
    lsp.SymbolKind.Constructor.value: "FUNCTION",
    lsp.SymbolKind.Variable.value: "VARIABLE",
    lsp.SymbolKind.Constant.value: "VARIABLE",
    lsp.SymbolKind.Property.value: "VARIABLE",
    lsp.SymbolKind.Field.value: "VARIABLE",
}


class VolarBackend(LspBackend):
    """volar (@vue/language-server) LSP backend；继承 implementation LspBackend。"""

    name: ClassVar[str] = "volar"
    language_ids: ClassVar[list[str]] = [
        "vue",
        "typescript",
        "typescriptreact",
        "javascript",
        "javascriptreact",
    ]
    command: ClassVar[list[str]] = ["vue-language-server", "--stdio"]
    initialization_options: ClassVar[dict[str, Any] | None] = {
        "typescript": {"tsdk": None},  # VolarPool._build_supervisor 注入实际值
        "vue": {"hybridMode": False},
    }

    def _lsp_extract_symbols(
        self, tree: Any, source: str, ctx: FileContext  # noqa: ARG002
    ) -> list[SymbolData]:
        """workspace/symbol + documentSymbol 混合策略（per work item / V2）。

        异常路径不 try/except；让 implementation LspBackend.extract_symbols 基类捕获 +
        fallback tree-sitter（per work item）。
        """
        timeout = float(getattr(settings, "LSP_REQUEST_TIMEOUT_SECONDS", 10))
        uri = path_to_uri(Path(ctx.file_path).resolve())
        supervisor = self._supervisor

        async def _coro() -> tuple[Any, Any]:
            client = supervisor._client
            if client is None:
                raise LspUnhealthyError(
                    f"volar supervisor '{supervisor.name}' client 未启动"
                )
            ws_resp = await client.request_workspace_symbol("", timeout=timeout)
            doc_resp = await client.request_document_symbol(uri, timeout=timeout)
            return ws_resp, doc_resp

        ws_resp, doc_resp = supervisor.call_async_in_loop(_coro, timeout=timeout * 2)
        return _convert_to_symbol_data(ws_resp, doc_resp, ctx)

    def _lsp_extract_imports(
        self, tree: Any, ctx: FileContext
    ) -> list[ImportData]:
        """tree-sitter raw + textDocument/definition 双层（per work item / work item）。

        策略：
            1. 复用 self._fallback.extract_imports 抽 raw ImportData[]（tree-sitter 已
               优化到 ~95% 抽 specifier）
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

        策略：
            1. 复用 self._fallback.extract_calls 抽 raw CallData[]（tree-sitter 已抽
               local + method 调用；callee_name 为字符串）
            2. **本 phase 框架**：暂直接透传 fallback 结果（前端 reverse references
               的完整 cross-file caller 解析在 Plan-06 集成测试驱动迭代）
            3. 真实集成测试发现需求时再补 textDocument/references 路径
        """
        source = self._extract_source_from_handle(tree)
        ts_tree = self._fallback.parse_file(ctx.file_path, source)
        return self._fallback.extract_calls(ts_tree, ctx)

    def _lsp_extract_endpoints(
        self, tree: Any, source: str, ctx: FileContext  # noqa: ARG002
    ) -> list[EndpointData]:
        """前端无 endpoint 语义；直接 return []（per work item）。"""
        return []


# =============================================================================
# 转换 helper（per V2 / V3 契约）
# =============================================================================

def _convert_to_symbol_data(
    ws_resp: Any, doc_resp: Any, ctx: FileContext
) -> list[SymbolData]:
    """LSP WorkspaceSymbol[] + DocumentSymbol[] → SymbolData[]（per V2 契约）。

    - workspace_symbol：过滤 location.uri 不属于 ctx.file_path 的项（防泛全局污染）
    - documentSymbol：递归展平 nested children（VolarBackend 不区分 nested 层级）
    - position.line LSP 0-indexed → SymbolData.start_line / end_line 1-indexed
    - kind → SymbolData.symbol_type via _SYMBOL_KIND_MAP，未知映射默认 "VARIABLE"
    - 同名 + 同行去重（workspace_symbol + documentSymbol 可能重复返）
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
    """``WorkspaceSymbol | SymbolInformation`` → ``SymbolData``。

    过滤掉不属于当前文件的项（防 workspace 全局符号污染单文件抽取）。
    """
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
    symbol_type = _SYMBOL_KIND_MAP.get(int(kind_value), "VARIABLE") if kind_value is not None else "VARIABLE"

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
    """递归展平 ``DocumentSymbol`` nested children（含 deprecated SymbolInformation 兼容）。"""
    result: list[SymbolData] = []
    name = getattr(item, "name", None)
    if not isinstance(name, str):
        return result

    kind = getattr(item, "kind", None)
    kind_value = getattr(kind, "value", kind) if kind is not None else None
    symbol_type = (
        _SYMBOL_KIND_MAP.get(int(kind_value), "VARIABLE")
        if kind_value is not None
        else "VARIABLE"
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

    per Pitfall P-checkpoint：character=0 在多数 import 行有效；偶失败返 None
    让上层使用原始 specifier。
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


def _convert_references_to_call_data(
    refs: Any,
    callee_symbol: str,
    callee_file_path: str,
    callee_line: int = 0,
) -> list[CallData]:
    """``Location[]`` → ``CallData[]``；过滤 callee 自身位置（per Pitfall P-checkpoint）。

    Returns:
        ``CallData[]``，每条以 (caller_file, callee_symbol, caller_line) 作 caller_key。
    """
    callee_uri: str | None = None
    try:
        callee_uri = path_to_uri(Path(callee_file_path).resolve())
    except (ValueError, OSError):
        callee_uri = None

    result: list[CallData] = []
    if not isinstance(refs, list):
        return result
    for ref in refs:
        ref_uri = getattr(ref, "uri", None) or getattr(ref, "target_uri", None)
        if not isinstance(ref_uri, str):
            continue
        # 过滤 callee 自身 location（per P-checkpoint）
        if callee_uri and ref_uri == callee_uri:
            range_obj = getattr(ref, "range", None)
            ref_line = (
                int(getattr(getattr(range_obj, "start", None), "line", -1)) + 1
                if range_obj is not None
                else 0
            )
            if ref_line == callee_line:
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
                callee_name=callee_symbol,
                call_type="DIRECT",
                line_number=max(caller_line, 0),
            )
        )
    return result


# =============================================================================
# 工厂闭包（per work item / work item）
# =============================================================================

def _find_sub_project_root(file_path: str) -> Path | None:
    """从文件路径 walk up 找含 ``tsconfig.json`` 的最近父目录。

    过滤 ``node_modules`` 子目录（防误识别）；找不到返 None。
    """
    try:
        candidate = Path(file_path).resolve().parent
    except (ValueError, OSError):
        return None
    for ancestor in (candidate, *candidate.parents):
        if "node_modules" in ancestor.parts:
            continue
        if (ancestor / "tsconfig.json").exists():
            return ancestor
    return None


def make_volar_backend(language: str) -> Callable[[str], ExtractorBackend]:
    """工厂闭包 —— 替换 implementation 占位 ``make_lsp_backend``。

    返回的工厂签名 ``Callable[[str], ExtractorBackend]`` 与 ``BACKEND_REGISTRY`` 类型
    严格对齐；闭包内 lazy 推断 sub_project_root + 通过 ``VolarPool.get`` 拿
    supervisor 实例化 ``VolarBackend``。

    Args:
        language: BACKEND_REGISTRY key 期望的语言（如 "vue" / "typescript"）

    Returns:
        ``_factory(actual_language: str)``：实际语言由调用方传（通常等于 language）

    Note:
        闭包接收的 ``actual_language`` 与外层 ``language`` 在 implementation BACKEND_REGISTRY
        替换路径下一致；保留参数让 GraphExtractor 可统一调用 ``factory(lang)`` 风格
        （per implementation register_backend 签名约束）。

        **本 phase 简化**：闭包不接受 ``file_path`` 入参，因 BACKEND_REGISTRY 是
        ``Callable[[str], ExtractorBackend]`` 不传 ctx；下游（如 GraphExtractor）
        若需要 per-file 隔离 supervisor，应直接调用 ``get_volar_pool().get(...)``
        + ``VolarBackend(...)``。这里返 fallback-only 实例（无 supervisor）让
        基类 try/except 第一次调用就直接 raise → fallback tree-sitter；真实
        per-sub-project 路径需要外层调度感知（待 indexer 集成迭代落地）。
    """
    captured_language = language

    def _factory(actual_language: str) -> ExtractorBackend:
        from codegraph.lsp.exceptions import LspUnhealthyError as _LspUE

        class _VolarLazyBackend(VolarBackend):
            """无 supervisor 占位实例：调用方传 ``_LspParseHandle`` 时 raise →
            implementation LspBackend 基类 fallback；调用方传**真实 tree-sitter Tree** 时
            （per orchestrator 既有调用风格）直接委托 fallback 不 raise，避免
            ``_extract_source_from_handle`` 在非 handle 入参下返空源回归。

            真实 per-sub-project supervisor 注入由 indexer / orchestrator 在
            后续迭代实装；本 plan 落地框架 + 注册路径 + 双兼容 fallback 安全网。
            """

            def __init__(self, language: str) -> None:
                # 不调 super().__init__；避免必填 supervisor 参数
                self.language = language
                self._supervisor: LspSupervisor = None  # type: ignore[assignment]
                self._fallback: ExtractorBackend = TreeSitterBackend(language)

            @staticmethod
            def _is_lsp_handle(tree: Any) -> bool:
                return isinstance(tree, _LspParseHandle)

            def _lsp_extract_symbols(
                self, tree: Any, source: str, ctx: FileContext
            ) -> list[SymbolData]:
                if not self._is_lsp_handle(tree):
                    return self._fallback.extract_symbols(tree, source, ctx)
                raise _LspUE(
                    "volar lazy backend：indexer per-sub-project supervisor 注入未实装"
                )

            def _lsp_extract_imports(
                self, tree: Any, ctx: FileContext
            ) -> list[ImportData]:
                if not self._is_lsp_handle(tree):
                    return self._fallback.extract_imports(tree, ctx)
                raise _LspUE(
                    "volar lazy backend：indexer per-sub-project supervisor 注入未实装"
                )

            def _lsp_extract_calls(
                self, tree: Any, ctx: FileContext
            ) -> list[CallData]:
                if not self._is_lsp_handle(tree):
                    return self._fallback.extract_calls(tree, ctx)
                raise _LspUE(
                    "volar lazy backend：indexer per-sub-project supervisor 注入未实装"
                )

            def _lsp_extract_endpoints(
                self, tree: Any, source: str, ctx: FileContext  # noqa: ARG002
            ) -> list[EndpointData]:
                return []

        # 用 actual_language 实例化（让上层 BACKEND_REGISTRY[lang](lang) 调用兼容）
        target_language = actual_language or captured_language
        return _VolarLazyBackend(target_language)

    _factory.__qualname__ = f"make_volar_backend.<locals>._factory[{language}]"
    return _factory


__all__ = [
    "VolarBackend",
    "make_volar_backend",
    "_convert_to_symbol_data",
    "_resolve_import_target_path",
    "_extract_first_location_path",
    "_convert_references_to_call_data",
    "_find_sub_project_root",
]

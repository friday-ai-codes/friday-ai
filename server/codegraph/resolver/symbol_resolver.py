"""work item —— 语言无关 SymbolResolver 编排层。

本模块串起 ``SymbolIndex`` 与语言专属 ``ImportResolver``：

1. 同文件裸名优先解析到当前文件内 Symbol；
2. 经 ``ImportEdge`` + 语言 resolver 解析跨文件 import；
3. JSX / TEMPLATE_REF 组件分支仅保留接口，具体实现留 implementation；
4. 解析不到时返回空结果，绝不靠 fuzzy 同名兜底乱连。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import structlog

from codegraph.resolver.base import ImportResolver, ResolveResult
from codegraph.resolver.go_import import GoImportResolver
from codegraph.resolver.symbol_index import IndexedSymbol, SymbolIndex

if TYPE_CHECKING:
    from codegraph.models import CallEdge, ImportEdge

__all__ = ["SymbolResolver"]

logger = structlog.get_logger(__name__)


_FRONTEND_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".vue")
_COMPONENT_CALL_TYPES = ("JSX", "TEMPLATE_REF")


def _lang_of(caller_file: str) -> str | None:
    """按 caller 文件扩展名选择语言 resolver；未知扩展走留空分支。"""
    if caller_file.endswith(".py"):
        return "python"
    if caller_file.endswith(".go"):
        return "go"
    if caller_file.endswith(_FRONTEND_EXTENSIONS):
        return "frontend"
    return None


def _dir_of(file_path: str) -> str:
    """取文件所在目录（仓根文件返回空串）。"""
    return file_path.rsplit("/", 1)[0] if "/" in file_path else ""


def _go_local_name(import_edge: ImportEdge) -> str:
    """求 Go import 的本地包名：alias（`"alias as path"`）优先，否则取 path 末段。

    Go ``imported_names`` 格式为 ``["alias as path"]``（alias 在前，与 Python 相反）
    或裸 ``["path"]``。无 alias 时本地名按约定取 import path 最后一段。
    """
    names = list(import_edge.imported_names or [])
    if names:
        first = names[0]
        alias, separator, _path = first.partition(" as ")
        if separator:
            return alias
    return import_edge.target_module.rsplit("/", 1)[-1]


def _match_imported_name(callee_name: str, imported_names: Sequence[str]) -> str | None:
    """用本地名匹配 ``imported_names``，返回目标文件内应查找的原始名。

    ``ImportEdge.imported_names`` 的条目格式为 ``"foo"`` 或 ``"foo as bar"``。
    调用点使用本地名（alias 优先），但目标文件内 Symbol 仍使用原始定义名。
    """
    for item in imported_names:
        original, separator, alias = item.partition(" as ")
        local_name = alias if separator else original
        if callee_name == local_name:
            return original
    return None


def _pick(candidates: list[IndexedSymbol]) -> IndexedSymbol:
    """从同文件同名候选中裁定一个 Symbol。

    裸名调用通常指向 top-level ``FUNCTION`` / ``CLASS``，优先于 ``METHOD`` /
    ``VARIABLE``；同优先级保持索引构建顺序稳定。
    """
    priority = {"FUNCTION": 0, "CLASS": 0, "METHOD": 1, "VARIABLE": 2}
    return min(candidates, key=lambda symbol: priority.get(symbol.symbol_type, 99))


def _best_candidates(candidates: list[IndexedSymbol]) -> list[IndexedSymbol]:
    """只保留最高优先级候选；同级多项必须交给调用方标 ambiguous。"""
    if not candidates:
        return []
    priority = {"FUNCTION": 0, "CLASS": 0, "METHOD": 1, "VARIABLE": 2}
    best = min(priority.get(symbol.symbol_type, 99) for symbol in candidates)
    return [symbol for symbol in candidates if priority.get(symbol.symbol_type, 99) == best]


def _language_name(caller_file: str) -> str:
    if caller_file.endswith((".js", ".jsx")):
        return "javascript"
    if caller_file.endswith((".ts", ".tsx", ".vue")):
        return "typescript"
    return _lang_of(caller_file) or "unknown"


def _candidate_dict(symbol: IndexedSymbol) -> dict[str, str]:
    return {
        "symbol_id": symbol.id,
        "file_path": symbol.file_path,
        "name": symbol.name,
        "symbol_type": symbol.symbol_type,
    }


def _resolved(
    symbol: IndexedSymbol,
    *,
    caller_file: str,
    language: str,
    call_shape: str,
    strategy: str,
    evidence: list[dict[str, str]],
) -> ResolveResult:
    return ResolveResult(
        symbol.id,
        symbol.file_path,
        symbol.file_path != caller_file,
        status="resolved",
        language=language,
        call_shape=call_shape,
        strategy=strategy,
        candidates=[_candidate_dict(symbol)],
        evidence=evidence,
    )


def _not_resolved(
    candidates: list[IndexedSymbol],
    *,
    language: str,
    call_shape: str,
    strategy: str,
    evidence: list[dict[str, str]] | None = None,
) -> ResolveResult:
    return ResolveResult(
        None,
        None,
        False,
        status="ambiguous" if candidates else "unresolved",
        language=language,
        call_shape=call_shape,
        strategy=strategy,
        candidates=[_candidate_dict(candidate) for candidate in candidates],
        evidence=evidence or [],
    )


class SymbolResolver:
    """跨文件静态符号解析编排器，供 288/289/290/291 复用。"""

    def __init__(
        self,
        symbol_index: SymbolIndex,
        import_by_source: Mapping[str, Sequence[ImportEdge]],
        resolver_by_lang: Mapping[str, ImportResolver],
    ) -> None:
        self._idx = symbol_index
        self._imports = import_by_source
        self._resolvers = resolver_by_lang

    def resolve_call(self, edge: CallEdge) -> ResolveResult:
        """解析单条 ``CallEdge``，产出可回填的 callee 三元组。"""
        caller_file = edge.caller_file
        callee_name = edge.callee_name
        language_name = _language_name(caller_file)
        call_shape = "member" if edge.call_type in {"METHOD", "ATTRIBUTE"} else "direct"

        local_hits = self._idx.exact(caller_file, callee_name)
        if local_hits:
            best = _best_candidates(local_hits)
            if len(best) == 1:
                return _resolved(
                    best[0],
                    caller_file=caller_file,
                    language=language_name,
                    call_shape=call_shape,
                    strategy="same_file_exact",
                    evidence=[{"kind": "same_file", "file_path": caller_file}],
                )
            return _not_resolved(
                best,
                language=language_name,
                call_shape=call_shape,
                strategy="same_file_exact",
            )

        language = _lang_of(caller_file)
        resolver = self._resolvers.get(language) if language is not None else None
        if resolver is not None:
            for import_edge in self._imports.get(caller_file, []):
                original_name = _match_imported_name(
                    callee_name,
                    import_edge.imported_names,
                )
                if original_name is None:
                    continue

                target_file = resolver.resolve_module(
                    import_edge.target_module,
                    import_edge.is_relative,
                    caller_file,
                )
                if target_file is None:
                    continue

                target_hits = self._idx.exact(target_file, original_name)
                if target_hits:
                    best = _best_candidates(target_hits)
                    if len(best) != 1:
                        return _not_resolved(
                            best,
                            language=language_name,
                            call_shape="import_alias",
                            strategy="import_exact",
                        )
                    return _resolved(
                        best[0],
                        caller_file=caller_file,
                        language=language_name,
                        call_shape="import_alias",
                        strategy="import_exact",
                        evidence=[
                            {
                                "kind": "import",
                                "source_file": caller_file,
                                "target_file": target_file,
                                "target_module": import_edge.target_module,
                            }
                        ],
                    )

                if language == "frontend":
                    chained = self._resolve_frontend_reexport(
                        target_file,
                        original_name,
                        resolver,
                        caller_file=caller_file,
                        initial_evidence=[
                            {
                                "kind": "import",
                                "source_file": caller_file,
                                "target_file": target_file,
                                "target_module": import_edge.target_module,
                            }
                        ],
                    )
                    if chained is not None:
                        return chained

        # Go selector 解析（work item）：`pkg.Func()` 的 callee_name 是裸函数名、包限定符
        # 在 287→checkpoint 捕获的 callee_qualifier 里。用 qualifier 匹配 import 本地名（alias 或
        # path 末段）→ 解析包目录 → 在该目录范围内按 callee_name 取目标 Symbol。标准库/第三方
        # （resolve_package_dir 返回 None）或 qualifier 是 receiver 变量（不匹配 import）→ 留 NULL。
        if (
            language == "go"
            and edge.callee_qualifier
            and isinstance(resolver, GoImportResolver)
        ):
            for import_edge in self._imports.get(caller_file, []):
                if _go_local_name(import_edge) != edge.callee_qualifier:
                    continue

                package_dir = resolver.resolve_package_dir(import_edge.target_module)
                if package_dir is None:
                    continue

                candidates = [
                    symbol
                    for symbol in self._idx.fuzzy(callee_name)
                    if _dir_of(symbol.file_path) == package_dir
                ]
                if candidates:
                    symbol = _pick(candidates)
                    return _resolved(
                        symbol,
                        caller_file=caller_file,
                        language=language_name,
                        call_shape="receiver",
                        strategy="go_import_qualifier",
                        evidence=[{"kind": "import_qualifier", "qualifier": edge.callee_qualifier}],
                    )

        if language == "frontend" and edge.callee_qualifier and resolver is not None:
            receiver = self._resolve_frontend_receiver(
                edge,
                resolver,
                caller_file=caller_file,
                language=language_name,
            )
            if receiver is not None:
                return receiver

        # 路径③组件引用解析（work item）：JSX / TEMPLATE_REF 边的 callee_name 是组件名，
        # 经 import 找到组件文件后连组件 Symbol。仅当 path② 未命中（名字未对齐，如重命名
        # default import）时才进入此兜底；无 import 的全局/auto 注册组件落空留 NULL。
        if edge.call_type in _COMPONENT_CALL_TYPES and resolver is not None:
            for import_edge in self._imports.get(caller_file, []):
                original_name = _match_imported_name(
                    callee_name,
                    import_edge.imported_names,
                )
                if original_name is None:
                    continue

                target_file = resolver.resolve_module(
                    import_edge.target_module,
                    import_edge.is_relative,
                    caller_file,
                )
                if target_file is None:
                    continue

                # 名字对齐优先（原名 / callee 本地名），否则取目标文件的组件 CLASS Symbol。
                hits = self._idx.exact(target_file, original_name) or self._idx.exact(
                    target_file, callee_name
                )
                if not hits:
                    hits = [
                        symbol
                        for symbol in self._idx.symbols_in_file(target_file)
                        if symbol.symbol_type == "CLASS"
                    ]
                if hits:
                    symbol = _pick(hits)
                    return _resolved(
                        symbol,
                        caller_file=caller_file,
                        language=language_name,
                        call_shape="component",
                        strategy="component_import",
                        evidence=[{"kind": "component_import", "target_file": target_file}],
                    )

        # 路径④：解析不到留空，绝不靠 fuzzy 同名兜底乱连。
        return _not_resolved(
            [],
            language=language_name,
            call_shape=call_shape,
            strategy="no_static_evidence",
        )

    def _resolve_frontend_reexport(
        self,
        start_file: str,
        symbol_name: str,
        resolver: ImportResolver,
        *,
        caller_file: str,
        initial_evidence: list[dict[str, str]],
    ) -> ResolveResult | None:
        """沿 ImportEdge 做有界、循环安全的 TS/JS re-export 解析。"""
        frontier: list[tuple[str, str, list[dict[str, str]]]] = [
            (start_file, symbol_name, initial_evidence)
        ]
        visited: set[tuple[str, str]] = set()
        found: list[tuple[IndexedSymbol, list[dict[str, str]]]] = []
        while frontier and len(visited) < 32:
            current_file, current_name, evidence = frontier.pop(0)
            key = (current_file, current_name)
            if key in visited:
                continue
            visited.add(key)
            for import_edge in self._imports.get(current_file, []):
                original_name = _match_imported_name(
                    current_name, import_edge.imported_names
                )
                if original_name is None:
                    continue
                target_file = resolver.resolve_module(
                    import_edge.target_module,
                    import_edge.is_relative,
                    current_file,
                )
                if target_file is None:
                    continue
                next_evidence = [
                    *evidence,
                    {
                        "kind": "re_export",
                        "source_file": current_file,
                        "target_file": target_file,
                        "target_module": import_edge.target_module,
                    },
                ]
                hits = _best_candidates(self._idx.exact(target_file, original_name))
                found.extend((hit, next_evidence) for hit in hits)
                if not hits:
                    frontier.append((target_file, original_name, next_evidence))

        unique = {symbol.id: (symbol, evidence) for symbol, evidence in found}
        if len(unique) == 1:
            symbol, evidence = next(iter(unique.values()))
            return _resolved(
                symbol,
                caller_file=caller_file,
                language=_language_name(caller_file),
                call_shape="re_export",
                strategy="frontend_reexport_chain",
                evidence=evidence,
            )
        if len(unique) > 1:
            return _not_resolved(
                [symbol for symbol, _ in unique.values()],
                language=_language_name(caller_file),
                call_shape="re_export",
                strategy="frontend_reexport_chain",
            )
        return None

    def _resolve_frontend_receiver(
        self,
        edge: CallEdge,
        resolver: ImportResolver,
        *,
        caller_file: str,
        language: str,
    ) -> ResolveResult | None:
        """解析 ``import * as ns`` 形成的静态 receiver binding。"""
        qualifier = str(edge.callee_qualifier or "")
        for import_edge in self._imports.get(caller_file, []):
            if f"* as {qualifier}" not in list(import_edge.imported_names or []):
                continue
            target_file = resolver.resolve_module(
                import_edge.target_module,
                import_edge.is_relative,
                caller_file,
            )
            if target_file is None:
                continue
            candidates = _best_candidates(
                self._idx.exact(target_file, edge.callee_name)
            )
            evidence = [
                {
                    "kind": "namespace_import",
                    "qualifier": qualifier,
                    "target_file": target_file,
                }
            ]
            if len(candidates) == 1:
                return _resolved(
                    candidates[0],
                    caller_file=caller_file,
                    language=language,
                    call_shape="receiver",
                    strategy="frontend_namespace_binding",
                    evidence=evidence,
                )
            return _not_resolved(
                candidates,
                language=language,
                call_shape="receiver",
                strategy="frontend_namespace_binding",
                evidence=evidence,
            )
        return None

    def backfill(self, repository_id: str) -> dict[str, int]:
        """批量回填该仓尚未解析的 ``CallEdge``。

        整库接入索引/重建流程留到 implementation；本入口仅供单测驱动与后续流程调用。
        单条边解析失败只记 warning，不阻断整批回填。
        """
        from codegraph.models import CallEdge

        edges = list(
            CallEdge.objects.filter(
                repository_id=repository_id,
                callee_symbol__isnull=True,
            )
        )
        resolved = 0

        for edge in edges:
            try:
                result = self.resolve_call(edge)
            except Exception as exc:  # noqa: BLE001 - 单边异常必须隔离，不能中断整批回填。
                logger.warning(
                    "resolve_call_failed",
                    edge_id=str(edge.id),
                    error=str(exc),
                )
                continue

            if result.callee_symbol_id is None:
                continue

            edge.callee_symbol_id = result.callee_symbol_id
            edge.callee_file = result.callee_file
            edge.is_cross_file = result.is_cross_file
            resolved += 1

        if edges:
            CallEdge.objects.bulk_update(
                edges,
                ["callee_symbol", "callee_file", "is_cross_file"],
                batch_size=500,
            )

        logger.info(
            "symbol_resolve_backfill_complete",
            repository_id=repository_id,
            total=len(edges),
            resolved=resolved,
        )
        return {"total": len(edges), "resolved": resolved}

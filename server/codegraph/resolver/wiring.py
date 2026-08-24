"""work item —— 整库符号解析回填编排。

把 work-item 的解析层接到索引/重建流程：整库 raw（Symbol/Import/raw Call）写完后，
对整库构建解析上下文并跑 ``SymbolResolver.backfill`` 回填 287 留 NULL 的
``CallEdge.callee_symbol / callee_file / is_cross_file``。

解析上下文 = ``SymbolIndex`` + 按 ``source_file`` 分组的 ``ImportEdge`` + 三语言
``ImportResolver``（python / frontend / go）。前端 alias_map 来自仓内 ``tsconfig.json``、
Go module_path 来自 ``go.mod``；缺失则对应 resolver 用空配置（Python 边照常解析）。

创建索引与手动重建均经 indexer ``_extract_and_write_graph``，本服务一处接入两路径覆盖。
"""

from __future__ import annotations

import os

import structlog

from codegraph.resolver.base import ImportResolver
from codegraph.resolver.frontend_import import FrontendImportResolver, load_alias_map
from codegraph.resolver.go_import import GoImportResolver, parse_go_module
from codegraph.resolver.python_import import PythonImportResolver
from codegraph.resolver.symbol_index import SymbolIndex
from codegraph.resolver.symbol_resolver import SymbolResolver

__all__ = ["backfill_symbol_resolution"]

logger = structlog.get_logger(__name__)


def _discover_alias_map(repo_path: str) -> dict[str, str]:
    """从仓内 tsconfig 解析前端 alias_map；候选取首个存在的文件，无则 ``{}``。"""
    candidates = [
        os.path.join(repo_path, "tsconfig.json"),
        os.path.join(repo_path, "web", "tsconfig.json"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            alias_map = load_alias_map(candidate)
            if alias_map:
                return alias_map
    return {}


def _discover_go_module(repo_path: str) -> str:
    """从仓内 ``go.mod`` 读取 module path；不存在/读失败返回空串。"""
    go_mod_path = os.path.join(repo_path, "go.mod")
    try:
        with open(go_mod_path, encoding="utf-8") as fh:
            module_path = parse_go_module(fh.read())
            return module_path or ""
    except OSError:
        return ""


def backfill_symbol_resolution(
    repository_id: str,
    repo_path: str,
    *,
    branch_name: str = "",
    dry_run: bool = False,
    initiated_by_user_id: str = "system",
) -> dict[str, int]:
    """对整库构建解析上下文并回填 ``CallEdge`` 的 callee 侧字段。

    Args:
        repository_id: 仓库 UUID 字符串。
        repo_path: 克隆仓库的本地路径（用于发现 tsconfig / go.mod）。

    Returns:
        ``{"total": N, "resolved": M}``——本次待解析边总数与成功回填数。
    """
    from codegraph.models import ImportEdge

    branch_filter = ["", branch_name] if branch_name else [""]
    index = SymbolIndex.build(repository_id, branch_name)

    import_by_source: dict[str, list[ImportEdge]] = {}
    for import_edge in ImportEdge.objects.filter(
        repository_id=repository_id,
        branch_name__in=branch_filter,
    ):
        import_by_source.setdefault(import_edge.source_file, []).append(import_edge)

    alias_map = _discover_alias_map(repo_path)
    module_path = _discover_go_module(repo_path)

    resolver_by_lang: dict[str, ImportResolver] = {
        "python": PythonImportResolver(index),
        "frontend": FrontendImportResolver(index, alias_map),
        "go": GoImportResolver(index, module_path),
    }

    resolver = SymbolResolver(index, import_by_source, resolver_by_lang)
    stats = resolver.backfill(
        repository_id,
        branch_name=branch_name,
        dry_run=dry_run,
        initiated_by_user_id=initiated_by_user_id,
    )

    if stats["changed"] and not dry_run:
        from codegraph.models import ProcessTrace, SymbolCommunity
        from services.code_graph import invalidate_repository

        # resolved edge 是两个投影的输入；目标分支变更后必须删除旧投影，等待既有重建流程
        # 以当前水位再生。缓存失效 best-effort 由公开入口内部保证。
        SymbolCommunity.objects.filter(
            repository_id=repository_id,
            branch_name=branch_name,
        ).delete()
        ProcessTrace.objects.filter(
            repository_id=repository_id,
            branch_name=branch_name,
        ).delete()
        invalidate_repository(repository_id)

    try:
        logger.info(
            "code_graph_symbol_resolution_wired",
            repository_id=repository_id,
            branch_name=branch_name,
            dry_run=dry_run,
            total=stats["total"],
            resolved=stats["resolved"],
            ambiguous=stats["ambiguous"],
            unresolved=stats["unresolved"],
            changed=stats["changed"],
            has_tsconfig=bool(alias_map),
            has_go_module=bool(module_path),
            initiated_by_user_id=initiated_by_user_id,
            category="caller",
            component="codegraph",
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort
        pass
    return stats

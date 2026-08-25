"""work item 单测 —— SymbolResolver 4 路径编排、alias 映射与回填入口。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import pytest
from asgiref.sync import sync_to_async

from codegraph.resolver import ImportResolver, ResolveResult, SymbolIndex
from codegraph.resolver.frontend_import import FrontendImportResolver
from codegraph.resolver.go_import import GoImportResolver
from codegraph.resolver.python_import import PythonImportResolver
from codegraph.resolver.symbol_resolver import SymbolResolver, _lang_of
from codegraph.resolver.tests.conftest import (
    CallSpec,
    ImportSpec,
    SymbolSpec,
    acreate_calls,
    acreate_imports,
    acreate_symbols,
)

if TYPE_CHECKING:
    from codegraph.models import CallEdge, ImportEdge


async def _build_index(repo_id: str) -> SymbolIndex:
    """在 async 测试里安全构建同步 ORM 驱动的 ``SymbolIndex``。"""
    return await sync_to_async(SymbolIndex.build)(repo_id)


def _resolver(
    index: SymbolIndex,
    imports: Sequence[ImportEdge],
    *,
    include_python: bool = True,
) -> SymbolResolver:
    """按 ``source_file`` 聚合 ImportEdge，构造被测 resolver。"""
    import_by_source: dict[str, list[ImportEdge]] = {}
    for edge in imports:
        import_by_source.setdefault(edge.source_file, []).append(edge)

    resolver_by_lang: dict[str, ImportResolver] = (
        {"python": PythonImportResolver(index)} if include_python else {}
    )
    return SymbolResolver(index, import_by_source, resolver_by_lang)


@pytest.mark.django_db(transaction=True)
async def test_resolve_same_file_call(test_repository) -> None:
    """路径①：caller_file 内同名调用解析到本文件 Symbol。"""
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="foo", file_path="pkg/caller.py", start_line=1)],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="pkg/caller.py", callee_name="foo")],
    )
    index = await _build_index(str(test_repository.id))

    result = _resolver(index, []).resolve_call(calls[0])

    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.callee_file == "pkg/caller.py"
    assert result.is_cross_file is False


@pytest.mark.django_db(transaction=True)
async def test_resolve_cross_file_via_python_import(test_repository) -> None:
    """路径②：经 ImportEdge + PythonImportResolver 解析跨文件调用。"""
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="foo", file_path="pkg/target.py", start_line=1)],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="pkg/caller.py",
                target_module="pkg.target",
                imported_names=["foo"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="pkg/caller.py", callee_name="foo")],
    )
    index = await _build_index(str(test_repository.id))

    result = _resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.callee_file == "pkg/target.py"
    assert result.is_cross_file is True


@pytest.mark.django_db(transaction=True)
async def test_alias_import_matches_local_name_but_looks_up_original(test_repository) -> None:
    """alias：callee_name 匹配本地名，目标文件查原始定义名。"""
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="calc", file_path="utils.py", start_line=1)],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="pkg/caller.py",
                target_module="utils",
                imported_names=["calc as c"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="pkg/caller.py", callee_name="c")],
    )
    index = await _build_index(str(test_repository.id))

    result = _resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.callee_file == "utils.py"
    assert result.is_cross_file is True


@pytest.mark.django_db(transaction=True)
async def test_third_party_import_keeps_result_empty_even_with_fuzzy_name(test_repository) -> None:
    """路径④：第三方 import 解析不到时留空，不用 fuzzy 同名乱连。"""
    await acreate_symbols(
        test_repository,
        [SymbolSpec(name="JsonResponse", file_path="local/http.py", start_line=1)],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="views.py",
                target_module="django.http",
                imported_names=["JsonResponse"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="views.py", callee_name="JsonResponse")],
    )
    index = await _build_index(str(test_repository.id))

    result = _resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id is None
    assert result.callee_file is None
    assert result.is_cross_file is False


@pytest.mark.django_db(transaction=True)
async def test_missing_language_resolver_keeps_result_empty(test_repository) -> None:
    """无语言 resolver（或未知扩展）时走留空分支，不报错。"""
    await acreate_symbols(
        test_repository,
        [SymbolSpec(name="foo", file_path="pkg/target.py", start_line=1)],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="pkg/caller.ts",
                target_module="pkg.target",
                imported_names=["foo"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="pkg/caller.ts", callee_name="foo")],
    )
    index = await _build_index(str(test_repository.id))

    result = _resolver(index, imports, include_python=False).resolve_call(calls[0])

    assert result.callee_symbol_id is None
    assert result.callee_file is None
    assert result.is_cross_file is False


@pytest.mark.django_db(transaction=True)
async def test_same_file_ambiguity_prefers_top_level_symbol(test_repository) -> None:
    """同文件同名歧义：FUNCTION / CLASS 优先于 METHOD / VARIABLE。"""
    symbols = await acreate_symbols(
        test_repository,
        [
            SymbolSpec(
                name="foo",
                file_path="pkg/caller.py",
                symbol_type="METHOD",
                start_line=20,
            ),
            SymbolSpec(
                name="foo",
                file_path="pkg/caller.py",
                symbol_type="FUNCTION",
                start_line=1,
            ),
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="pkg/caller.py", callee_name="foo")],
    )
    index = await _build_index(str(test_repository.id))

    result = _resolver(index, []).resolve_call(calls[0])

    assert result.callee_symbol_id == str(symbols[1].id)


@pytest.mark.django_db(transaction=True)
async def test_backfill_updates_resolved_edges_and_leaves_unresolved_empty(
    test_repository,
) -> None:
    """backfill：批量写回可解析边，不可解析第三方边保持 NULL。"""
    symbols = await acreate_symbols(
        test_repository,
        [
            SymbolSpec(name="local_func", file_path="pkg/caller.py", start_line=1),
            SymbolSpec(name="remote_func", file_path="pkg/target.py", start_line=1),
        ],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="pkg/caller.py",
                target_module="pkg.target",
                imported_names=["remote_func"],
            ),
            ImportSpec(
                source_file="pkg/caller.py",
                target_module="django.http",
                imported_names=["JsonResponse"],
            ),
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(caller_file="pkg/caller.py", callee_name="local_func"),
            CallSpec(caller_file="pkg/caller.py", callee_name="remote_func"),
            CallSpec(caller_file="pkg/caller.py", callee_name="JsonResponse"),
        ],
    )
    index = await _build_index(str(test_repository.id))

    stats = await sync_to_async(_resolver(index, imports).backfill)(str(test_repository.id))

    for call in calls:
        await call.arefresh_from_db()
    assert stats == {
        "total": 3,
        "resolved": 2,
        "ambiguous": 0,
        "unresolved": 1,
        "changed": 2,
    }
    assert calls[0].callee_symbol_id == symbols[0].id
    assert calls[0].callee_file == "pkg/caller.py"
    assert calls[0].is_cross_file is False
    assert calls[1].callee_symbol_id == symbols[1].id
    assert calls[1].callee_file == "pkg/target.py"
    assert calls[1].is_cross_file is True
    assert calls[2].callee_symbol_id is None
    assert calls[2].callee_file is None
    assert calls[2].is_cross_file is False


@pytest.mark.django_db(transaction=True)
async def test_backfill_isolates_single_edge_failures(test_repository, monkeypatch) -> None:
    """单条边解析异常不会中断整批；后续边仍可回填。"""
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="ok", file_path="pkg/caller.py", start_line=1)],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(caller_file="pkg/bad.py", callee_name="bad"),
            CallSpec(caller_file="pkg/caller.py", callee_name="ok"),
        ],
    )
    index = await _build_index(str(test_repository.id))
    resolver = _resolver(index, [])

    def flaky_resolve(edge: CallEdge) -> ResolveResult:
        if edge.id == calls[0].id:
            raise RuntimeError("boom")
        return ResolveResult(str(symbols[0].id), "pkg/caller.py", False)

    monkeypatch.setattr(resolver, "resolve_call", flaky_resolve)

    stats = await sync_to_async(resolver.backfill)(str(test_repository.id))

    for call in calls:
        await call.arefresh_from_db()
    assert stats == {
        "total": 2,
        "resolved": 1,
        "ambiguous": 0,
        "unresolved": 1,
        "changed": 1,
    }
    assert calls[0].callee_symbol_id is None
    assert calls[1].callee_symbol_id == symbols[0].id


def _frontend_resolver(
    index: SymbolIndex,
    imports: Sequence[ImportEdge],
    *,
    alias_map: dict[str, str] | None = None,
) -> SymbolResolver:
    """构造注册了 FrontendImportResolver 的 resolver（组件引用解析用）。"""
    import_by_source: dict[str, list[ImportEdge]] = {}
    for edge in imports:
        import_by_source.setdefault(edge.source_file, []).append(edge)

    resolver_by_lang: dict[str, ImportResolver] = {
        "frontend": FrontendImportResolver(index, alias_map or {"~/": "src/"})
    }
    return SymbolResolver(index, import_by_source, resolver_by_lang)


def test_lang_of_frontend_extensions() -> None:
    """``_lang_of`` 前端 5 扩展名归 frontend，.py 仍 python，.go 归 go，未知 None。"""
    for ext in (".ts", ".tsx", ".js", ".jsx", ".vue"):
        assert _lang_of(f"src/views/Page{ext}") == "frontend"
    assert _lang_of("pkg/mod.py") == "python"
    assert _lang_of("cmd/main.go") == "go"
    assert _lang_of("README.md") is None


def _go_resolver(
    index: SymbolIndex,
    imports: Sequence[ImportEdge],
    *,
    module_path: str = "github.com/org/repo",
) -> SymbolResolver:
    """构造注册了 GoImportResolver 的 resolver（Go selector 解析用）。"""
    import_by_source: dict[str, list[ImportEdge]] = {}
    for edge in imports:
        import_by_source.setdefault(edge.source_file, []).append(edge)

    resolver_by_lang: dict[str, ImportResolver] = {
        "go": GoImportResolver(index, module_path)
    }
    return SymbolResolver(index, import_by_source, resolver_by_lang)


@pytest.mark.django_db(transaction=True)
async def test_go_selector_alias_import(test_repository) -> None:
    """Go selector：alias import + qualifier → 包目录内目标 Symbol。"""
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="Handle", file_path="internal/svc/handler.go", start_line=1)],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="cmd/main.go",
                target_module="github.com/org/repo/internal/svc",
                imported_names=["svc as github.com/org/repo/internal/svc"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="cmd/main.go",
                callee_name="Handle",
                call_type="METHOD",
                callee_qualifier="svc",
            )
        ],
    )
    index = await _build_index(str(test_repository.id))

    result = _go_resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.callee_file == "internal/svc/handler.go"
    assert result.is_cross_file is True


@pytest.mark.django_db(transaction=True)
async def test_go_selector_bare_import_last_segment(test_repository) -> None:
    """Go selector：裸 import 本地名=path 末段，qualifier 匹配末段 → 命中。"""
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="New", file_path="internal/svc/svc.go", start_line=1)],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="cmd/main.go",
                target_module="github.com/org/repo/internal/svc",
                imported_names=["github.com/org/repo/internal/svc"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="cmd/main.go",
                callee_name="New",
                call_type="METHOD",
                callee_qualifier="svc",
            )
        ],
    )
    index = await _build_index(str(test_repository.id))

    result = _go_resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.is_cross_file is True


@pytest.mark.django_db(transaction=True)
async def test_go_stdlib_selector_stays_empty(test_repository) -> None:
    """Go selector：标准库 fmt.Sprintf → resolve_package_dir None → 留 NULL。"""
    await acreate_symbols(
        test_repository,
        [SymbolSpec(name="Sprintf", file_path="internal/fake/fmt.go", start_line=1)],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="cmd/main.go",
                target_module="fmt",
                imported_names=["fmt"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="cmd/main.go",
                callee_name="Sprintf",
                call_type="METHOD",
                callee_qualifier="fmt",
            )
        ],
    )
    index = await _build_index(str(test_repository.id))

    result = _go_resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id is None
    assert result.is_cross_file is False


@pytest.mark.django_db(transaction=True)
async def test_go_receiver_variable_qualifier_stays_empty(test_repository) -> None:
    """Go selector：qualifier 是 receiver 变量（不匹配任何 import 本地名）→ 留 NULL。"""
    # JSON 符号放在与 caller 不同的文件，避免路径①同文件命中；本例验证 Go 分支因
    # qualifier="c" 不匹配 gin import 本地名（"gin"）而留空。
    await acreate_symbols(
        test_repository,
        [SymbolSpec(name="JSON", file_path="vendor/gin/context.go", start_line=1)],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="internal/svc/handler.go",
                target_module="github.com/gin-gonic/gin",
                imported_names=["github.com/gin-gonic/gin"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="internal/svc/handler.go",
                callee_name="JSON",
                call_type="METHOD",
                callee_qualifier="c",
            )
        ],
    )
    index = await _build_index(str(test_repository.id))

    result = _go_resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id is None
    assert result.is_cross_file is False


@pytest.mark.django_db(transaction=True)
async def test_symbols_in_file(test_repository) -> None:
    """``symbols_in_file`` 返回文件全部 Symbol；空文件返回 []。"""
    await acreate_symbols(
        test_repository,
        [
            SymbolSpec(name="a", file_path="src/m.ts", start_line=1),
            SymbolSpec(name="b", file_path="src/m.ts", start_line=5),
        ],
    )
    index = await _build_index(str(test_repository.id))

    names = sorted(s.name for s in index.symbols_in_file("src/m.ts"))
    assert names == ["a", "b"]
    assert index.symbols_in_file("src/nonexistent.ts") == []


@pytest.mark.django_db(transaction=True)
async def test_component_reference_aligned_name(test_repository) -> None:
    """success criterion：组件 A 引用组件 B（名字对齐）→ 连到 B 的组件 CLASS Symbol。"""
    symbols = await acreate_symbols(
        test_repository,
        [
            SymbolSpec(
                name="UserCard",
                file_path="src/components/UserCard.vue",
                symbol_type="CLASS",
                start_line=1,
            )
        ],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="src/views/Home.vue",
                target_module="~/components/UserCard.vue",
                imported_names=["UserCard"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="src/views/Home.vue",
                callee_name="UserCard",
                call_type="TEMPLATE_REF",
            )
        ],
    )
    index = await _build_index(str(test_repository.id))

    result = _frontend_resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.callee_file == "src/components/UserCard.vue"
    assert result.is_cross_file is True


@pytest.mark.django_db(transaction=True)
async def test_component_reference_renamed_default(test_repository) -> None:
    """重命名 default：<Card/> 经 import 兜底取目标文件组件 CLASS Symbol。"""
    symbols = await acreate_symbols(
        test_repository,
        [
            SymbolSpec(
                name="UserCard",
                file_path="src/components/UserCard.vue",
                symbol_type="CLASS",
                start_line=1,
            )
        ],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="src/views/Home.vue",
                target_module="~/components/UserCard.vue",
                imported_names=["Card"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="src/views/Home.vue",
                callee_name="Card",
                call_type="TEMPLATE_REF",
            )
        ],
    )
    index = await _build_index(str(test_repository.id))

    result = _frontend_resolver(index, imports).resolve_call(calls[0])

    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.callee_file == "src/components/UserCard.vue"
    assert result.is_cross_file is True


@pytest.mark.django_db(transaction=True)
async def test_global_component_without_import_stays_empty(test_repository) -> None:
    """无 import 的全局/auto 注册组件 → 留 NULL 不误连。"""
    await acreate_symbols(
        test_repository,
        [
            SymbolSpec(
                name="RouterView",
                file_path="src/components/RouterView.vue",
                symbol_type="CLASS",
                start_line=1,
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="src/views/Home.vue",
                callee_name="RouterView",
                call_type="TEMPLATE_REF",
            )
        ],
    )
    index = await _build_index(str(test_repository.id))

    result = _frontend_resolver(index, []).resolve_call(calls[0])

    assert result.callee_symbol_id is None
    assert result.callee_file is None
    assert result.is_cross_file is False


def test_public_exports() -> None:
    """包根导出聚合：下游 phase 可从 ``codegraph.resolver`` 统一引入。"""
    from codegraph.resolver import (  # noqa: PLC0415
        FrontendImportResolver,
        GoImportResolver,
        ImportResolver,
        PythonImportResolver,
        ResolveResult,
        SymbolIndex,
        SymbolResolver,
    )

    assert SymbolIndex is not None
    assert SymbolResolver is not None
    assert PythonImportResolver is not None
    assert FrontendImportResolver is not None
    assert GoImportResolver is not None
    assert ImportResolver is not None
    assert ResolveResult is not None

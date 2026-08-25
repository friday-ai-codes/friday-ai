"""Phase 135：Python module/member/class binding 三态解析。"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from codegraph.resolver.base import ImportResolver
from codegraph.resolver.python_import import PythonImportResolver
from codegraph.resolver.symbol_index import SymbolIndex
from codegraph.resolver.symbol_resolver import SymbolResolver
from codegraph.resolver.tests.conftest import (
    CallSpec,
    ImportSpec,
    SymbolSpec,
    acreate_calls,
    acreate_imports,
    acreate_symbols,
)


async def _resolver(repo_id: str, imports: list) -> SymbolResolver:
    index = await sync_to_async(SymbolIndex.build)(repo_id)
    grouped: dict[str, list] = {}
    for edge in imports:
        grouped.setdefault(edge.source_file, []).append(edge)
    resolvers: dict[str, ImportResolver] = {"python": PythonImportResolver(index)}
    return SymbolResolver(index, grouped, resolvers)


@pytest.mark.django_db(transaction=True)
async def test_module_alias_member_beats_local_same_name(test_repository) -> None:
    symbols = await acreate_symbols(
        test_repository,
        [
            SymbolSpec(name="run", file_path="pkg/api.py"),
            SymbolSpec(name="run", file_path="main.py"),
        ],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="main.py",
                target_module="pkg.api",
                imported_names=["pkg.api as api"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="main.py",
                callee_name="run",
                call_type="METHOD",
                callee_qualifier="api",
            )
        ],
    )

    result = (await _resolver(str(test_repository.id), imports)).resolve_call(calls[0])

    assert result.status == "resolved"
    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.callee_symbol_id != str(symbols[1].id)
    assert result.strategy == "python_module_member"


@pytest.mark.django_db(transaction=True)
async def test_from_import_alias_direct_call(test_repository) -> None:
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="calculate", file_path="pkg/math.py")],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="main.py",
                target_module="pkg.math",
                imported_names=["calculate as calc"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="main.py", callee_name="calc")],
    )

    result = (await _resolver(str(test_repository.id), imports)).resolve_call(calls[0])

    assert result.status == "resolved"
    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.call_shape == "import_alias"


@pytest.mark.django_db(transaction=True)
async def test_imported_class_unique_method_is_resolved(test_repository) -> None:
    symbols = await acreate_symbols(
        test_repository,
        [
            SymbolSpec(name="Client", file_path="pkg/client.py", symbol_type="CLASS"),
            SymbolSpec(name="send", file_path="pkg/client.py", symbol_type="METHOD"),
        ],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="main.py",
                target_module="pkg.client",
                imported_names=["Client as ApiClient"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="main.py",
                callee_name="send",
                call_type="METHOD",
                callee_qualifier="ApiClient",
            )
        ],
    )

    result = (await _resolver(str(test_repository.id), imports)).resolve_call(calls[0])

    assert result.status == "resolved"
    assert result.callee_symbol_id == str(symbols[1].id)
    assert result.strategy == "python_imported_class"


@pytest.mark.django_db(transaction=True)
async def test_dynamic_receiver_without_binding_is_unresolved(test_repository) -> None:
    await acreate_symbols(
        test_repository,
        [SymbolSpec(name="send", file_path="pkg/client.py", symbol_type="METHOD")],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="main.py",
                callee_name="send",
                call_type="METHOD",
                callee_qualifier="client",
            )
        ],
    )

    result = (await _resolver(str(test_repository.id), [])).resolve_call(calls[0])

    assert result.status == "unresolved"
    assert result.callee_symbol_id is None
    assert result.strategy == "no_static_evidence"

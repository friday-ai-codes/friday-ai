"""Phase 134：TS/JS 可审计 resolved/ambiguous/unresolved 解析。"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from asgiref.sync import sync_to_async

from codegraph.resolver.base import ImportResolver
from codegraph.resolver.frontend_import import FrontendImportResolver
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


async def _resolver(repo_id: str, imports: Sequence) -> SymbolResolver:
    index = await sync_to_async(SymbolIndex.build)(repo_id)
    grouped: dict[str, list] = {}
    for edge in imports:
        grouped.setdefault(edge.source_file, []).append(edge)
    front = FrontendImportResolver(index, {"~/": "src/"})
    resolvers: dict[str, ImportResolver] = {"frontend": front}
    return SymbolResolver(index, grouped, resolvers)


@pytest.mark.django_db(transaction=True)
async def test_import_alias_is_resolved_with_audit_evidence(test_repository) -> None:
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="calculate", file_path="src/math.ts")],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="src/main.ts",
                target_module="./math",
                imported_names=["calculate as calc"],
                is_relative=True,
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="src/main.ts", callee_name="calc")],
    )

    result = (await _resolver(str(test_repository.id), imports)).resolve_call(calls[0])

    assert result.status == "resolved"
    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.language == "typescript"
    assert result.call_shape == "import_alias"
    assert result.strategy == "import_exact"
    assert result.evidence[0]["target_file"] == "src/math.ts"


@pytest.mark.django_db(transaction=True)
async def test_reexport_chain_resolves_and_keeps_every_hop(test_repository) -> None:
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="run", file_path="src/impl.ts")],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="src/main.ts",
                target_module="./barrel",
                imported_names=["run"],
                is_relative=True,
            ),
            ImportSpec(
                source_file="src/barrel.ts",
                target_module="./impl",
                imported_names=["run"],
                is_relative=True,
            ),
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="src/main.ts", callee_name="run")],
    )

    result = (await _resolver(str(test_repository.id), imports)).resolve_call(calls[0])

    assert result.status == "resolved"
    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.strategy == "frontend_reexport_chain"
    assert [row["target_file"] for row in result.evidence] == [
        "src/barrel.ts",
        "src/impl.ts",
    ]


@pytest.mark.django_db(transaction=True)
async def test_namespace_receiver_resolves_unique_member(test_repository) -> None:
    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="parse", file_path="src/utils.ts")],
    )
    imports = await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="src/main.js",
                target_module="./utils",
                imported_names=["* as utils"],
                is_relative=True,
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [
            CallSpec(
                caller_file="src/main.js",
                callee_name="parse",
                call_type="METHOD",
                callee_qualifier="utils",
            )
        ],
    )

    result = (await _resolver(str(test_repository.id), imports)).resolve_call(calls[0])

    assert result.status == "resolved"
    assert result.callee_symbol_id == str(symbols[0].id)
    assert result.language == "javascript"
    assert result.call_shape == "receiver"
    assert result.strategy == "frontend_namespace_binding"


@pytest.mark.django_db(transaction=True)
async def test_same_evidence_multiple_candidates_is_ambiguous(test_repository) -> None:
    await acreate_symbols(
        test_repository,
        [
            SymbolSpec(name="run", file_path="src/main.ts", start_line=1),
            SymbolSpec(name="run", file_path="src/main.ts", start_line=20),
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="src/main.ts", callee_name="run")],
    )

    result = (await _resolver(str(test_repository.id), [])).resolve_call(calls[0])

    assert result.status == "ambiguous"
    assert result.callee_symbol_id is None
    assert len(result.candidates) == 2

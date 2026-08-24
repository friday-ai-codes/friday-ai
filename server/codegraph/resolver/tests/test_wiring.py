"""work item 单测 —— backfill_symbol_resolution 整库回填编排。

用 conftest 路线 B 造跨语言可解析 / 第三方不可解析的 CallEdge + ImportEdge + Symbol，
tmp_path 写 go.mod / tsconfig.json，跑 backfill 后断言可解析边写回、第三方留 NULL。
"""

from __future__ import annotations

import json
import os

import pytest
from asgiref.sync import sync_to_async

from codegraph.resolver.tests.conftest import (
    CallSpec,
    ImportSpec,
    SymbolSpec,
    acreate_calls,
    acreate_imports,
    acreate_symbols,
)
from codegraph.resolver.wiring import backfill_symbol_resolution


def _write_repo_config(repo_path: str) -> None:
    """在仓根写 go.mod + tsconfig.json，供 wiring 发现 module_path / alias_map。"""
    with open(os.path.join(repo_path, "go.mod"), "w", encoding="utf-8") as fh:
        fh.write("module github.com/org/repo\n\ngo 1.22\n")
    with open(os.path.join(repo_path, "tsconfig.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {"compilerOptions": {"baseUrl": ".", "paths": {"~/*": ["src/*"]}}},
            fh,
        )


@pytest.mark.django_db(transaction=True)
async def test_backfill_resolves_multi_language(test_repository, tmp_path) -> None:
    """跨语言（py / go selector / 前端组件）可解析边回填，第三方留 NULL。"""
    repo_path = str(tmp_path)
    await sync_to_async(_write_repo_config)(repo_path)

    symbols = await acreate_symbols(
        test_repository,
        [
            # Python 跨文件
            SymbolSpec(name="remote_func", file_path="pkg/target.py", start_line=1),
            # Go 包目录内符号
            SymbolSpec(name="Handle", file_path="internal/svc/handler.go", start_line=1),
            # 前端组件 CLASS
            SymbolSpec(
                name="UserCard",
                file_path="src/components/UserCard.vue",
                symbol_type="CLASS",
                start_line=1,
            ),
        ],
    )
    await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="pkg/caller.py",
                target_module="pkg.target",
                imported_names=["remote_func"],
            ),
            ImportSpec(
                source_file="cmd/main.go",
                target_module="github.com/org/repo/internal/svc",
                imported_names=["github.com/org/repo/internal/svc"],
            ),
            ImportSpec(
                source_file="src/views/Home.vue",
                target_module="~/components/UserCard.vue",
                imported_names=["UserCard"],
            ),
            # 第三方
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
            CallSpec(caller_file="pkg/caller.py", callee_name="remote_func"),
            CallSpec(
                caller_file="cmd/main.go",
                callee_name="Handle",
                call_type="METHOD",
                callee_qualifier="svc",
            ),
            CallSpec(
                caller_file="src/views/Home.vue",
                callee_name="UserCard",
                call_type="TEMPLATE_REF",
            ),
            CallSpec(caller_file="pkg/caller.py", callee_name="JsonResponse"),
        ],
    )

    stats = await sync_to_async(backfill_symbol_resolution)(
        str(test_repository.id), repo_path
    )

    for call in calls:
        await call.arefresh_from_db()

    assert stats == {
        "total": 4,
        "resolved": 3,
        "ambiguous": 0,
        "unresolved": 1,
        "changed": 3,
    }
    assert calls[0].callee_symbol_id == symbols[0].id  # py 跨文件
    assert calls[1].callee_symbol_id == symbols[1].id  # go selector
    assert calls[2].callee_symbol_id == symbols[2].id  # 前端组件
    assert calls[3].callee_symbol_id is None  # 第三方留 NULL


@pytest.mark.django_db(transaction=True)
async def test_backfill_without_config_still_resolves_python(
    test_repository, tmp_path
) -> None:
    """缺 go.mod / tsconfig（空配置）不报错，Python 边照常解析。"""
    repo_path = str(tmp_path)  # 不写任何配置文件

    symbols = await acreate_symbols(
        test_repository,
        [SymbolSpec(name="remote_func", file_path="pkg/target.py", start_line=1)],
    )
    await acreate_imports(
        test_repository,
        [
            ImportSpec(
                source_file="pkg/caller.py",
                target_module="pkg.target",
                imported_names=["remote_func"],
            )
        ],
    )
    calls = await acreate_calls(
        test_repository,
        [CallSpec(caller_file="pkg/caller.py", callee_name="remote_func")],
    )

    stats = await sync_to_async(backfill_symbol_resolution)(
        str(test_repository.id), repo_path
    )

    for call in calls:
        await call.arefresh_from_db()
    assert stats == {
        "total": 1,
        "resolved": 1,
        "ambiguous": 0,
        "unresolved": 0,
        "changed": 1,
    }
    assert calls[0].callee_symbol_id == symbols[0].id


@pytest.mark.django_db(transaction=True)
async def test_branch_dry_run_reports_without_writing_other_branches(
    test_repository, tmp_path
) -> None:
    """dry-run 只量测目标 branch，且目标/其他分支都不写。"""
    from codegraph.models import CallEdge, ImportEdge, Symbol

    target = await Symbol.objects.acreate(
        repository=test_repository,
        branch_name="feature/a",
        name="run",
        symbol_type="FUNCTION",
        file_path="src/target.ts",
        start_line=1,
        end_line=2,
    )
    await ImportEdge.objects.acreate(
        repository=test_repository,
        branch_name="feature/a",
        source_file="src/main.ts",
        target_module="./target",
        imported_names=["run"],
        is_relative=True,
    )
    feature_call = await CallEdge.objects.acreate(
        repository=test_repository,
        branch_name="feature/a",
        caller_file="src/main.ts",
        callee_name="run",
        call_type="DIRECT",
        line_number=1,
    )
    base_call = await CallEdge.objects.acreate(
        repository=test_repository,
        branch_name="",
        caller_file="src/main.ts",
        callee_name="run",
        call_type="DIRECT",
        line_number=1,
    )

    stats = await sync_to_async(backfill_symbol_resolution)(
        str(test_repository.id),
        str(tmp_path),
        branch_name="feature/a",
        dry_run=True,
    )

    await feature_call.arefresh_from_db()
    await base_call.arefresh_from_db()
    assert stats["total"] == 1
    assert stats["resolved"] == 1
    assert stats["changed"] == 0
    assert feature_call.callee_symbol_id is None
    assert base_call.callee_symbol_id is None
    assert target.id is not None

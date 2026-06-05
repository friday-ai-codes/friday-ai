"""initial implementation plan（work item-01）：GraphWriter.delete_for_files 同步/异步双 API 测试。

覆盖五维场景：
1. 短路：file_paths == [] 返回 0 且不进 transaction（mock spy 验证）
2. 计数：返回 Symbol + ImportEdge + Endpoint 三表删除总和
3. 过滤：repository_id + file_path__in 双条件，互不串扰
4. Rollback：transaction.atomic 内某步 raise 后三表行数零变化
5. Async：adelete_for_files 等价于 sync 版本
6. 字段差异：ImportEdge 的 source_file 字段被正确处理（非 file_path）

与既有 write_bundle_sync 套件平行，不替换原有 per-file delete 逻辑。
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from codegraph.models import Endpoint, ImportEdge, Symbol
from codegraph.services.graph_writer import GraphWriter


@pytest.fixture
def graph_writer() -> GraphWriter:
    """返回 GraphWriter 实例。"""
    return GraphWriter()


def _make_symbol(repository_id: str, file_path: str, name: str = "func") -> Symbol:
    """构造 Symbol 实例（不入库）。"""
    return Symbol(
        repository_id=repository_id,
        name=name,
        symbol_type=Symbol.SymbolType.FUNCTION,
        file_path=file_path,
        start_line=1,
        end_line=2,
        signature=f"def {name}():",
        is_async=False,
    )


def _make_import(repository_id: str, source_file: str, target_module: str = "os") -> ImportEdge:
    """构造 ImportEdge 实例（注意字段是 source_file 而非 file_path）。"""
    return ImportEdge(
        repository_id=repository_id,
        source_file=source_file,
        target_module=target_module,
        imported_names=[target_module],
        is_relative=False,
    )


def _make_endpoint(repository_id: str, file_path: str, handler_name: str = "view") -> Endpoint:
    """构造 Endpoint 实例。"""
    return Endpoint(
        repository_id=repository_id,
        http_method="GET",
        url_path="/api/x/",
        handler_name=handler_name,
        view_type=Endpoint.ViewType.FUNCTION_VIEW,
        file_path=file_path,
        line_number=1,
        metadata=None,
    )


# ============================================================================
# 1. 短路：file_paths == [] 不进 transaction
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_empty_file_paths_short_circuit_returns_zero_without_transaction(
    repository, graph_writer
) -> None:
    """空 file_paths 直接返回 0，且 transaction.atomic 完全未被调用。"""
    with patch(
        "codegraph.services.graph_writer.transaction.atomic"
    ) as spy_atomic:
        result = graph_writer.delete_for_files(str(repository.id), [])

    assert result == 0
    assert spy_atomic.call_count == 0


# ============================================================================
# 2. 计数：三表删除总和
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_returns_total_deleted_count_across_three_tables(
    repository, graph_writer
) -> None:
    """同 file_path 的 Symbol×3 + ImportEdge×2 + Endpoint×1 → 返回 6。"""
    repo_id = str(repository.id)
    Symbol.objects.bulk_create([
        _make_symbol(repo_id, "a.py", f"f{i}") for i in range(3)
    ])
    ImportEdge.objects.bulk_create([
        _make_import(repo_id, "a.py", f"m{i}") for i in range(2)
    ])
    Endpoint.objects.bulk_create([_make_endpoint(repo_id, "a.py")])

    deleted = graph_writer.delete_for_files(repo_id, ["a.py"])

    assert deleted == 6
    assert Symbol.objects.filter(repository_id=repo_id, file_path="a.py").count() == 0
    assert ImportEdge.objects.filter(repository_id=repo_id, source_file="a.py").count() == 0
    assert Endpoint.objects.filter(repository_id=repo_id, file_path="a.py").count() == 0


# ============================================================================
# 3. 过滤：repository_id + file_path__in 双条件隔离
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_filters_by_repository_and_file_paths(repository, graph_writer) -> None:
    """构造 repo_A/a.py、repo_A/b.py、repo_B/a.py 三组数据；只删 repo_A/a.py。"""
    from repositories.models import Repository

    repo_b = Repository.objects.create(
        id=uuid.uuid4(),
        name="other-repo",
        git_url="https://github.com/test/other.git",
        default_branch="main",
    )
    repo_a_id = str(repository.id)
    repo_b_id = str(repo_b.id)

    Symbol.objects.bulk_create([
        _make_symbol(repo_a_id, "a.py", "fa1"),
        _make_symbol(repo_a_id, "b.py", "fb1"),
        _make_symbol(repo_b_id, "a.py", "fb_other"),
    ])
    ImportEdge.objects.bulk_create([
        _make_import(repo_a_id, "a.py", "ma"),
        _make_import(repo_a_id, "b.py", "mb"),
        _make_import(repo_b_id, "a.py", "m_other"),
    ])
    Endpoint.objects.bulk_create([
        _make_endpoint(repo_a_id, "a.py", "ha"),
        _make_endpoint(repo_a_id, "b.py", "hb"),
        _make_endpoint(repo_b_id, "a.py", "h_other"),
    ])

    deleted = graph_writer.delete_for_files(repo_a_id, ["a.py"])

    assert deleted == 3
    assert Symbol.objects.filter(repository_id=repo_a_id, file_path="a.py").count() == 0
    assert Symbol.objects.filter(repository_id=repo_a_id, file_path="b.py").count() == 1
    assert Symbol.objects.filter(repository_id=repo_b_id, file_path="a.py").count() == 1
    assert ImportEdge.objects.filter(repository_id=repo_a_id, source_file="a.py").count() == 0
    assert ImportEdge.objects.filter(repository_id=repo_a_id, source_file="b.py").count() == 1
    assert ImportEdge.objects.filter(repository_id=repo_b_id, source_file="a.py").count() == 1
    assert Endpoint.objects.filter(repository_id=repo_a_id, file_path="a.py").count() == 0
    assert Endpoint.objects.filter(repository_id=repo_a_id, file_path="b.py").count() == 1
    assert Endpoint.objects.filter(repository_id=repo_b_id, file_path="a.py").count() == 1


# ============================================================================
# 4. Rollback：单步 raise 整体 atomic 回滚
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_atomic_rollback_on_exception_preserves_all_rows(
    repository, graph_writer
) -> None:
    """让 Endpoint.objects.filter().delete() raise → 抛异常后三表行数全部不变。"""
    repo_id = str(repository.id)
    Symbol.objects.bulk_create([_make_symbol(repo_id, "a.py", "f1")])
    ImportEdge.objects.bulk_create([_make_import(repo_id, "a.py", "m1")])
    Endpoint.objects.bulk_create([_make_endpoint(repo_id, "a.py")])

    sym_before = Symbol.objects.filter(repository_id=repo_id, file_path="a.py").count()
    imp_before = ImportEdge.objects.filter(repository_id=repo_id, source_file="a.py").count()
    ep_before = Endpoint.objects.filter(repository_id=repo_id, file_path="a.py").count()
    assert (sym_before, imp_before, ep_before) == (1, 1, 1)

    real_filter = Endpoint.objects.filter

    def _raising_filter(*args, **kwargs):
        qs = real_filter(*args, **kwargs)
        qs.delete = lambda: (_ for _ in ()).throw(RuntimeError("simulated"))  # type: ignore[method-assign]
        return qs

    with patch.object(Endpoint.objects, "filter", side_effect=_raising_filter):
        with pytest.raises(RuntimeError, match="simulated"):
            graph_writer.delete_for_files(repo_id, ["a.py"])

    assert Symbol.objects.filter(repository_id=repo_id, file_path="a.py").count() == sym_before
    assert ImportEdge.objects.filter(repository_id=repo_id, source_file="a.py").count() == imp_before
    assert Endpoint.objects.filter(repository_id=repo_id, file_path="a.py").count() == ep_before


# ============================================================================
# 5. 异步 API 等价同步
# ============================================================================


@pytest.mark.django_db(transaction=True)
async def test_async_api_routes_to_sync_via_thread_sensitive_false(
    repository, graph_writer
) -> None:
    """await adelete_for_files 返回值与 sync delete_for_files 一致。"""
    from asgiref.sync import sync_to_async

    repo_id = str(repository.id)
    await sync_to_async(Symbol.objects.bulk_create)([
        _make_symbol(repo_id, "a.py", "fa1"),
        _make_symbol(repo_id, "a.py", "fa2"),
    ])
    await sync_to_async(ImportEdge.objects.bulk_create)([
        _make_import(repo_id, "a.py", "m1"),
    ])

    deleted = await graph_writer.adelete_for_files(repo_id, ["a.py"])

    assert deleted == 3
    remaining_syms = await sync_to_async(
        Symbol.objects.filter(repository_id=repo_id, file_path="a.py").count
    )()
    assert remaining_syms == 0


@pytest.mark.django_db(transaction=True)
async def test_async_empty_file_paths_short_circuit(
    repository, graph_writer
) -> None:
    """async 短路：file_paths == [] 返回 0，不调度到线程池。"""
    result = await graph_writer.adelete_for_files(str(repository.id), [])
    assert result == 0


# ============================================================================
# 6. ImportEdge 字段差异处理（source_file 而非 file_path）
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_handles_import_edge_source_file_field(repository, graph_writer) -> None:
    """ImportEdge.source_file == "a.py" 必须被 delete_for_files(["a.py"]) 命中。"""
    repo_id = str(repository.id)
    ImportEdge.objects.bulk_create([
        _make_import(repo_id, "a.py", "m1"),
        _make_import(repo_id, "a.py", "m2"),
        _make_import(repo_id, "other.py", "m3"),
    ])
    assert ImportEdge.objects.filter(repository_id=repo_id).count() == 3

    deleted = graph_writer.delete_for_files(repo_id, ["a.py"])

    assert deleted == 2
    assert ImportEdge.objects.filter(repository_id=repo_id, source_file="a.py").count() == 0
    assert ImportEdge.objects.filter(repository_id=repo_id, source_file="other.py").count() == 1

"""contract 回归测试：GraphWriter branch-scoped 写/删。

覆盖 initial implementation 验收红线 —— feature 分支 per-file 删除/重建只清本分支行，
base 行（branch_name=""）绝不被删或被 feature 写覆盖；base+feature 双写后 4 表
（Symbol/ImportEdge/Endpoint/CallEdge）各 branch_name 维度行数互不覆盖、按预期翻倍。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from codegraph.extractors.base import (
    CallData,
    EndpointData,
    ExtractionBundle,
    ImportData,
    SymbolData,
)
from codegraph.models import CallEdge, Endpoint, ImportEdge, Symbol
from codegraph.services.graph_writer import GraphWriter
from repositories.models import Repository

# 单文件 bundle 的确定性行数（4 表各自预期），用于双写计数断言。
_EXPECTED_SYMBOLS = 2
_EXPECTED_IMPORTS = 1
_EXPECTED_ENDPOINTS = 1
_EXPECTED_CALLS = 1

_FEATURE_BRANCH = "feat-x"


@pytest_asyncio.fixture
async def branch_repo():
    """创建测试用 Repository（base_branch=main）。"""
    repo = await Repository.objects.acreate(
        id=uuid.uuid4(),
        name="test-branch-graph-writer",
        git_url="https://example.com/branch-graph.git",
        default_branch="main",
    )
    yield repo
    await Repository.objects.filter(id=repo.id).adelete()


@pytest_asyncio.fixture
async def writer():
    """返回 GraphWriter 实例。"""
    return GraphWriter()


def _make_bundle(file_path: str = "src/sample.py") -> ExtractionBundle:
    """构造确定性单文件 bundle —— 行数与 _EXPECTED_* 常量对齐。"""
    return ExtractionBundle(
        file_path=file_path,
        language="python",
        symbols=[
            SymbolData(name="alpha", symbol_type="FUNCTION", file_path=file_path,
                       start_line=1, end_line=3, signature="def alpha():"),
            SymbolData(name="beta", symbol_type="FUNCTION", file_path=file_path,
                       start_line=5, end_line=7, signature="def beta():"),
        ],
        imports=[
            ImportData(source_file=file_path, target_module="os",
                       imported_names=["os"], is_relative=False),
        ],
        calls=[
            CallData(caller_key=(file_path, "alpha", 1), callee_name="print",
                     call_type="DIRECT", line_number=2),
        ],
        endpoints=[
            EndpointData(http_method="GET", url_path="/api/sample/",
                         handler_name="sample_view", view_type="FUNCTION_VIEW",
                         file_path=file_path, line_number=1),
        ],
    )


async def _counts(repo: Repository, branch_name: str) -> dict[str, int]:
    """返回某分支维度下 4 表的行数快照。"""
    return {
        "symbols": await Symbol.objects.filter(
            repository=repo, branch_name=branch_name,
        ).acount(),
        "imports": await ImportEdge.objects.filter(
            repository=repo, branch_name=branch_name,
        ).acount(),
        "endpoints": await Endpoint.objects.filter(
            repository=repo, branch_name=branch_name,
        ).acount(),
        "calls": await CallEdge.objects.filter(
            repository=repo, branch_name=branch_name,
        ).acount(),
    }


@pytest.mark.django_db(transaction=True)
async def test_feature_delete_preserves_base(branch_repo, writer) -> None:
    """contract：feature per-file 写入/删除只动本分支行，base 行绝不被覆盖或删除。

    流程：先写 base（branch_name=""）→ 记录 base 行数；再对同一 file_path 以
    branch_name="feat-x" write_bundle（feature 的 per-file delete 加 branch 过滤，
    不应删到 base）；最后 adelete_for_files(branch_name="feat-x") 清 feature 孤儿，
    断言 base 行数始终不变、feature 行独立存在/独立删除。
    """
    file_path = "src/sample.py"
    bundle = _make_bundle(file_path)

    # 1) 写 base 行（branch_name=""）。
    await writer.write_bundle(str(branch_repo.id), bundle)
    base_after_base_write = await _counts(branch_repo, "")
    assert base_after_base_write == {
        "symbols": _EXPECTED_SYMBOLS,
        "imports": _EXPECTED_IMPORTS,
        "endpoints": _EXPECTED_ENDPOINTS,
        "calls": _EXPECTED_CALLS,
    }

    # 2) 对同一 file_path 写 feature 行 —— feature 的 per-file delete 带
    #    branch_name="feat-x" 过滤，绝不删到 base 行。
    await writer.write_bundle(
        str(branch_repo.id), bundle, branch_name=_FEATURE_BRANCH,
    )
    base_after_feature_write = await _counts(branch_repo, "")
    feature_after_feature_write = await _counts(branch_repo, _FEATURE_BRANCH)

    assert base_after_feature_write == base_after_base_write, (
        "feature 写入后 base 行数必须不变（base 不被 feature 覆盖/删除）"
    )
    assert feature_after_feature_write == {
        "symbols": _EXPECTED_SYMBOLS,
        "imports": _EXPECTED_IMPORTS,
        "endpoints": _EXPECTED_ENDPOINTS,
        "calls": _EXPECTED_CALLS,
    }, "feature 行应独立存在"

    # 3) 清理 feature 孤儿（adelete_for_files 带 branch_name）—— 只清 feature，
    #    base 行必须保留。
    deleted = await writer.adelete_for_files(
        str(branch_repo.id), [file_path], branch_name=_FEATURE_BRANCH,
    )
    assert deleted == (
        _EXPECTED_SYMBOLS + _EXPECTED_IMPORTS
        + _EXPECTED_ENDPOINTS + _EXPECTED_CALLS
    ), f"应只删除 feature 行，实际删除 {deleted}"

    base_after_feature_delete = await _counts(branch_repo, "")
    feature_after_feature_delete = await _counts(branch_repo, _FEATURE_BRANCH)
    assert base_after_feature_delete == base_after_base_write, (
        "feature 删除后 base 行数必须不变（feature 删除绝不碰 base 行）"
    )
    assert feature_after_feature_delete == {
        "symbols": 0, "imports": 0, "endpoints": 0, "calls": 0,
    }, "feature 行应被完全清除"


@pytest.mark.django_db(transaction=True)
async def test_dual_write_row_counts(branch_repo, writer) -> None:
    """contract：base + feature 对同一 file 双写后，4 表各分支行数互不覆盖、翻倍。"""
    file_path = "src/sample.py"
    bundle = _make_bundle(file_path)

    await writer.write_bundle(str(branch_repo.id), bundle)
    await writer.write_bundle(
        str(branch_repo.id), bundle, branch_name=_FEATURE_BRANCH,
    )

    base_counts = await _counts(branch_repo, "")
    feature_counts = await _counts(branch_repo, _FEATURE_BRANCH)
    expected = {
        "symbols": _EXPECTED_SYMBOLS,
        "imports": _EXPECTED_IMPORTS,
        "endpoints": _EXPECTED_ENDPOINTS,
        "calls": _EXPECTED_CALLS,
    }
    assert base_counts == expected, "base 分支行数应符合预期"
    assert feature_counts == expected, "feature 分支行数应符合预期"

    # 全量（不区分 branch）应为两分支之和 —— 证明双写行数翻倍、互不覆盖。
    for model, key in (
        (Symbol, "symbols"), (ImportEdge, "imports"),
        (Endpoint, "endpoints"), (CallEdge, "calls"),
    ):
        total = await model.objects.filter(repository=branch_repo).acount()
        assert total == expected[key] * 2, (
            f"{model.__name__} 全量行数应为 base+feature 之和 "
            f"{expected[key] * 2}，实际 {total}"
        )

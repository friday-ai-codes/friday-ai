"""resolver 解析层共享 fixture —— 多文件 Symbol/ImportEdge/CallEdge 构造工具。

供全 phase（checkpoint / checkpoint / checkpoint）复用，提供两套构造路线：

- **路线 A** ``build_repo_via_graph_writer(repo, bundles)``：用 ``ExtractionBundle`` 经
  真实 ``GraphWriter`` 写库，端到端贴近真实抽取/写入路径基准（用于坐实 RESEARCH Q1：
  ``Symbol.file_path`` 的存储基准与 import 模块名解析路径是否对齐）。
- **路线 B** ``acreate_symbols / acreate_imports / acreate_calls``：直接经 ORM
  ``acreate`` 精确构造多文件场景（同文件同名不同 start_line、相对/绝对/第三方 import、
  alias import），用于精确驱动 resolver 各分支断言。

后续 plan 直接 ``from codegraph.resolver.tests.conftest import ...`` 复用。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest_asyncio

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")

if TYPE_CHECKING:
    from codegraph.models import CallEdge, ImportEdge, Symbol
    from repositories.models import Repository


# ---------------------------------------------------------------------------
# Repository fixture（照搬 test_graph_writer.py，改 name="test-resolver-repo"）
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def test_repository() -> AsyncIterator[Repository]:
    """创建测试用 Repository 实例，测试结束后清理。"""
    from repositories.models import Repository

    repo = await Repository.objects.acreate(
        id=uuid.uuid4(),
        name="test-resolver-repo",
        git_url="https://github.com/test/resolver-repo.git",
        default_branch="main",
    )
    yield repo
    await Repository.objects.filter(id=repo.id).adelete()


# ---------------------------------------------------------------------------
# 路线 B：直接 ORM acreate 精确构造（多文件 / 同名歧义 / alias import）
# ---------------------------------------------------------------------------


@dataclass
class SymbolSpec:
    """一条 Symbol 构造规格 —— 字段与 ``codegraph.models.Symbol`` 对齐。"""

    name: str
    file_path: str
    symbol_type: str = "FUNCTION"
    start_line: int = 1
    end_line: int = 1
    signature: str = ""
    is_async: bool = False


@dataclass
class ImportSpec:
    """一条 ImportEdge 构造规格 —— 字段与 ``codegraph.models.ImportEdge`` 对齐。"""

    source_file: str
    target_module: str
    imported_names: list[str] = field(default_factory=list)
    is_relative: bool = False


@dataclass
class CallSpec:
    """一条 CallEdge 构造规格 —— 字段与 ``codegraph.models.CallEdge`` 对齐。

    ``caller_symbol`` / ``callee_symbol`` 传 ``Symbol`` 实例（或 None 表示模块级 /
    未解析），其余字段直填。
    """

    caller_file: str
    callee_name: str
    call_type: str = "DIRECT"
    line_number: int = 1
    caller_symbol: Symbol | None = None
    callee_symbol: Symbol | None = None
    callee_file: str | None = None
    is_cross_file: bool = False
    callee_qualifier: str | None = None


async def acreate_symbols(repo: Repository, specs: Sequence[SymbolSpec]) -> list[Symbol]:
    """按 ``SymbolSpec`` 列表逐个 acreate Symbol，返回创建结果列表。"""
    from codegraph.models import Symbol

    created: list[Symbol] = []
    for spec in specs:
        created.append(
            await Symbol.objects.acreate(
                repository=repo,
                name=spec.name,
                symbol_type=spec.symbol_type,
                file_path=spec.file_path,
                start_line=spec.start_line,
                end_line=spec.end_line,
                signature=spec.signature,
                is_async=spec.is_async,
            )
        )
    return created


async def acreate_imports(repo: Repository, specs: Sequence[ImportSpec]) -> list[ImportEdge]:
    """按 ``ImportSpec`` 列表逐个 acreate ImportEdge，返回创建结果列表。"""
    from codegraph.models import ImportEdge

    created: list[ImportEdge] = []
    for spec in specs:
        created.append(
            await ImportEdge.objects.acreate(
                repository=repo,
                source_file=spec.source_file,
                target_module=spec.target_module,
                imported_names=spec.imported_names,
                is_relative=spec.is_relative,
            )
        )
    return created


async def acreate_calls(repo: Repository, specs: Sequence[CallSpec]) -> list[CallEdge]:
    """按 ``CallSpec`` 列表逐个 acreate CallEdge，返回创建结果列表。"""
    from codegraph.models import CallEdge

    created: list[CallEdge] = []
    for spec in specs:
        created.append(
            await CallEdge.objects.acreate(
                repository=repo,
                caller_symbol=spec.caller_symbol,
                caller_file=spec.caller_file,
                callee_name=spec.callee_name,
                callee_symbol=spec.callee_symbol,
                callee_file=spec.callee_file,
                is_cross_file=spec.is_cross_file,
                call_type=spec.call_type,
                line_number=spec.line_number,
                callee_qualifier=spec.callee_qualifier,
            )
        )
    return created


# ---------------------------------------------------------------------------
# 路线 A：经真实 GraphWriter 写库（端到端，贴近真实路径基准，用于 Q1）
# ---------------------------------------------------------------------------


async def build_repo_via_graph_writer(
    repo: Repository, bundles: Sequence[Any]
) -> dict[str, int]:
    """用真实 ``GraphWriter`` 把多个 ``ExtractionBundle`` 写入测试库。

    端到端走与生产一致的写入路径，使 ``Symbol.file_path`` 的存储基准与真实抽取一致，
    供 Q1 路径基准断言。返回各维度写入总数 ``{"symbols","imports","calls","endpoints"}``。
    """
    from codegraph.services.graph_writer import GraphWriter

    writer = GraphWriter()
    totals: dict[str, int] = {"symbols": 0, "imports": 0, "calls": 0, "endpoints": 0}
    for bundle in bundles:
        stats = await writer.write_bundle(str(repo.id), bundle)
        for key, value in stats.items():
            totals[key] = totals.get(key, 0) + value
    return totals

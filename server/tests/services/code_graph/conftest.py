"""内存图服务（``services/code_graph/``）测试包的共享 fixtures。

**本目录的 fixture 全部自建，不复用 ``tests/codegraph/conftest.py``。**
pytest 的 conftest 作用域是「所在目录及其子目录」，``tests/codegraph/`` 与本目录
是兄弟分支、互不可见（Phase 121 RESEARCH Pitfall 11）；且那边的 ``graph_repo``
没有设 ``index_status``（默认 ``NOT_INDEXED``），会被 ``ensure_repository_readable``
在第一道闸直接拒掉。

约定：
- ORM 模型一律走**函数体内 lazy import**，避免 ``services`` 包在 Django app
  loading 早期触发模型导入（与 ``services/code_intel/local_provider.py`` 同因）。
- 分支语义两套、不可混用：``Symbol`` / ``CallEdge`` 的 ``branch_name=""`` 表示
  base；``RepositoryBranchIndex.branch_name`` 存**真实分支名**，base 由
  ``is_base_branch=True`` 标识，从不为空串（RESEARCH Pitfall 6）。
"""

from __future__ import annotations

from typing import Any, Callable

import pytest


@pytest.fixture
def indexed_repo(db):
    """已索引且未删除的 Repository —— 后续 ``ensure_repository_readable`` 的两道闸都过。

    显式设 ``index_status=INDEXED``：图服务对未索引仓库抛错而非返回空图（空图会被
    上层工具误读为「没有影响」），不设就会在第一道闸全军覆没。
    """
    from repositories.models import IndexStatus, Repository

    return Repository.objects.create(
        name="code-graph-test-repo",
        git_url="https://example.com/code-graph-test-repo.git",
        default_branch="main",
        index_status=IndexStatus.INDEXED,
        is_deleted=False,
        last_indexed_commit_sha="a" * 40,
    )


@pytest.fixture
def branch_index(indexed_repo):
    """``indexed_repo`` 的 base 分支索引记录（签名水位分量的来源之一）。

    ``branch_name`` 存真实分支名 ``"main"``，base 身份由 ``is_base_branch=True``
    表达——**不要**写成 ``branch_name=""``，那样水位查询永远落空、
    ``RepositoryBranchIndex`` 分量形同虚设（RESEARCH Pitfall 6）。
    """
    from django.utils import timezone

    from repositories.models import RepositoryBranchIndex

    return RepositoryBranchIndex.objects.create(
        repository=indexed_repo,
        branch_name="main",
        is_base_branch=True,
        last_indexed_commit_sha=indexed_repo.last_indexed_commit_sha,
        last_indexed_at=timezone.now(),
    )


@pytest.fixture
def symbols_factory(indexed_repo) -> Callable[..., Any]:
    """建 ``Symbol`` 行的工厂。``branch_name`` 默认 ``""``（base 分支）。"""
    from codegraph.models import Symbol

    def _create(
        name: str,
        file_path: str,
        *,
        branch_name: str = "",
        start_line: int = 1,
        end_line: int = 10,
        symbol_type: str = "FUNCTION",
    ):
        return Symbol.objects.create(
            repository=indexed_repo,
            branch_name=branch_name,
            name=name,
            symbol_type=symbol_type,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
        )

    return _create


@pytest.fixture
def call_edges_factory(indexed_repo) -> Callable[..., Any]:
    """建 ``CallEdge`` 行的工厂，覆盖解析边与裸名边两档。

    ``callee=None`` 时造**裸名边**：``callee_symbol`` 留空、只填 ``callee_name``
    （必要时配 ``callee_file`` / ``callee_qualifier``），对应 ``bare_name`` 置信度档。
    """
    from codegraph.models import CallEdge

    def _create(
        caller,
        callee=None,
        *,
        branch_name: str = "",
        callee_name: str | None = None,
        callee_file: str | None = None,
        callee_qualifier: str | None = None,
        line_number: int = 1,
        call_type: str = "DIRECT",
    ):
        resolved_name = callee_name or (callee.name if callee is not None else "")
        return CallEdge.objects.create(
            repository=indexed_repo,
            branch_name=branch_name,
            caller_symbol=caller,
            caller_file=caller.file_path if caller is not None else "",
            callee_symbol=callee,
            callee_name=resolved_name,
            callee_file=callee_file,
            callee_qualifier=callee_qualifier,
            call_type=call_type,
            line_number=line_number,
        )

    return _create


@pytest.fixture
def exclusion_rule_factory(indexed_repo) -> Callable[..., Any]:
    """建 per-repo ``RepoExclusionRule`` 行的工厂（驱动 exclusion 过滤与规则指纹用例）。"""
    from repositories.models import RepoExclusionRule

    def _create(
        pattern: str,
        *,
        rule_type: str = RepoExclusionRule.RuleType.GLOB,
        enabled: bool = True,
        source: str = "user",
    ):
        return RepoExclusionRule.objects.create(
            repository=indexed_repo,
            pattern=pattern,
            rule_type=rule_type,
            enabled=enabled,
            source=source,
        )

    return _create


@pytest.fixture(autouse=True)
def _reset_code_graph_state():
    """用例间清进程级缓存，防止上一个用例的状态污染下一个。

    三份进程级状态**都要清**：``services.exclusion`` 的 60s TTL matcher 缓存（模块级
    裸字典）、``services.code_graph.access`` 自建的 matcher/指纹 memo（同为 60s TTL，
    但同步路径够不着前者，见该模块注释），以及 ``services.code_graph.cache`` 的
    ``GraphService`` 模块级单例。少清一份就会让断言读到上一个用例留下的旧值、随机失败
    ——单例那份尤其隐蔽：缓存命中会让下一个用例**根本不走建图路径**，于是「builder 被
    调用几次」这类断言的结果取决于用例执行顺序。
    """
    from services.exclusion import invalidate_matcher_cache

    def _reset() -> None:
        invalidate_matcher_cache()
        # Plan 121-03 / 121-07 之前对应模块不存在，用 ImportError 兜住保持子计划顺序安全。
        try:
            from services.code_graph.access import invalidate_matcher_fingerprint_cache
        except ImportError:
            pass
        else:
            invalidate_matcher_fingerprint_cache()

        try:
            from services.code_graph.cache import _reset_for_tests
        except ImportError:
            return
        _reset_for_tests()

    _reset()
    yield
    _reset()

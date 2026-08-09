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

import networkx as nx
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


@pytest.fixture
def known_topology() -> nx.MultiDiGraph:
    """可逐点核对的**合成冻结** ``MultiDiGraph`` —— Phase 122 全部零 DB 内核断言的地基。

    拓扑（三个互不连通的簇 + 一个孤立点）::

        簇一（A 的反向影响面）
            E ──resolved───▶ B ──resolved───▶ A      A 的 d1={B,C}、d2={E,D}
            C ──bare_name──▶ B
            D ──resolved───▶ C ──resolved───▶ A      C 同时是 d1 与 d2 ⇒ 取最浅 d1
            F ──cross_repo(0.7)──▶ A
            A ──resolved───▶ G                       下游，反向遍历不得看到 G
            X ──bare_name──▶ B                       只经裸名边可达的观察点

        簇二（等长多解）
            P ──resolved──▶ Q ──resolved──▶ S
            P ──resolved──▶ R ──resolved──▶ S        P→S 两条等长最短路

        孤立点
            H

    为什么这么造：

    - **簇二存在的唯一理由**是 ``test_equal_length_paths_declared``（122-04）。簇一里
      ``D → A`` 只有一条最短路，验证不了 D-18 的「存在 N 条等长路径」声明；簇二与 A 完全
      不连通，加它不会扰动任何既有的深度分组断言。
    - **``X`` 存在的唯一理由**是 ``test_bare_name_requires_both_gates``（122-03）：D-08
      的双闸需要一个**只能经 bare_name 边到达**的观察点。``C`` 担不了这个角色——它还有
      ``C → A(resolved)``，两道闸没开时它照样出现在结果里，用例会恒真。
      ⛔ **不要给 ``X`` 加任何别的出边**，加了就等于把那条用例悄悄弄成永远通过。
    - 节点 ``file_path`` / ``start_line`` 两两不同，断言可以逐点核对是哪一个符号。

    ⚠️ **必须 ``nx.freeze``**：Phase 121 的 ``get_graph`` 出图前会冻结（``cache.py:1025``），
    fixture 不冻结的话「内核不修改入参图」（``test_kernel_does_not_mutate_graph``）这条断言
    恒真、等于没写。冻结后就地修改直接抛 ``NetworkXError``，只读遍历与
    ``reverse(copy=False)`` 视图不受影响。

    属性个数照 ``services/code_graph/model.py::CodeGraph`` 的内存契约逐字对齐：节点恒 5 个
    （``name`` / ``symbol_type`` / ``file_path`` / ``start_line`` / ``end_line``），边恒 3 个
    （``kind`` / ``confidence`` / ``line_number``），``cross_repo`` 档**唯一例外**多一个
    ``match_confidence``。``reason`` 现推不存（D-09），不得出现在边属性里。
    """
    graph = nx.MultiDiGraph()
    for node_id, file_path, start_line in [
        ("A", "pkg/a.go", 10),
        ("B", "pkg/b.go", 20),
        ("C", "pkg/c.go", 30),
        ("D", "pkg/d.go", 40),
        ("E", "pkg/e.go", 50),
        ("F", "web/f.ts", 60),
        ("G", "pkg/g.go", 70),
        ("H", "pkg/h.go", 80),
        ("P", "pkg/p.go", 90),
        ("Q", "pkg/q.go", 100),
        ("R", "pkg/r.go", 110),
        ("S", "pkg/s.go", 120),
        ("X", "pkg/x.go", 130),
    ]:
        graph.add_node(
            node_id,
            name=node_id.lower(),
            symbol_type="FUNCTION",
            file_path=file_path,
            start_line=start_line,
            end_line=start_line + 5,
        )

    graph.add_edge("B", "A", kind="call", confidence="resolved", line_number=21)
    graph.add_edge("E", "B", kind="call", confidence="resolved", line_number=51)
    graph.add_edge("C", "B", kind="call", confidence="bare_name", line_number=31)
    graph.add_edge("C", "A", kind="call", confidence="resolved", line_number=32)
    graph.add_edge("D", "C", kind="call", confidence="resolved", line_number=41)
    graph.add_edge(
        "F", "A", kind="cross_repo", confidence="cross_repo", line_number=61, match_confidence=0.7
    )
    graph.add_edge("A", "G", kind="call", confidence="resolved", line_number=11)
    # ⛔ X 的唯一出边，见上方 docstring。
    graph.add_edge("X", "B", kind="call", confidence="bare_name", line_number=131)

    graph.add_edge("P", "Q", kind="call", confidence="resolved", line_number=91)
    graph.add_edge("Q", "S", kind="call", confidence="resolved", line_number=101)
    graph.add_edge("P", "R", kind="call", confidence="resolved", line_number=92)
    graph.add_edge("R", "S", kind="call", confidence="resolved", line_number=111)

    nx.freeze(graph)
    return graph


@pytest.fixture
def hub_topology() -> Callable[..., nx.MultiDiGraph]:
    """可调扇入的 hub 图工厂：``hub`` + ``fan_in`` 个直接前驱 + 每个前驱各一个二级前驱。

    服务于 ``test_truncation_summary``（D-16 的 200 条上限）与 ``test_risk_levels``
    （D-15 的 d1 = 2/3/7/8/19/20 边界）的取值。为什么需要「可调」而不是再来一张定死的
    小图：``122-RESEARCH.md`` Pitfall 6 实测生产解析边入度 **max 2,803 / p99 25**，
    200 条截断在热点符号上**必然触发**——截断计数与排序是会被真实用到的功能，用例必须
    能一路造到上限两侧，而不是只在理论边界上比划。

    二级前驱让 d2 层非空：只有 d1 的图验证不了「深度升序」这个排序主键。

    :param fan_in: ``hub`` 的直接前驱个数（d1 层大小）。
    :param confidence: 全图统一的置信度档位，用于把同一形状复用到各档过滤用例。
    :returns: 已 ``nx.freeze`` 的 ``MultiDiGraph``，共 ``1 + 2 * fan_in`` 个节点。
    """

    def _build(fan_in: int, *, confidence: str = "resolved") -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph()

        def _add(node_id: str, start_line: int) -> None:
            graph.add_node(
                node_id,
                name=node_id.lower(),
                symbol_type="FUNCTION",
                file_path=f"pkg/{node_id.lower()}.go",
                start_line=start_line,
                end_line=start_line + 5,
            )

        _add("hub", 1)
        for i in range(fan_in):
            caller = f"caller_{i}"
            grand = f"grandcaller_{i}"
            _add(caller, 100 + i * 10)
            _add(grand, 1000 + i * 10)
            graph.add_edge(
                caller, "hub", kind="call", confidence=confidence, line_number=100 + i * 10 + 1
            )
            graph.add_edge(
                grand, caller, kind="call", confidence=confidence, line_number=1000 + i * 10 + 1
            )

        nx.freeze(graph)
        return graph

    return _build


@pytest.fixture
def cross_repo_call_factory(db) -> Callable[..., Any]:
    """建一条 ``CrossRepoApiCall`` 及其四模型链（``ApiWrapper`` → ``ApiCallSite`` →
    ``Endpoint`` → ``CrossRepoApiCall``）的工厂。

    ``endpoint_repository`` 传**另一个仓库**即造出一条真正的跨仓行——两端分属不同仓，
    正是 IMPACT-03 四条分支要覆盖的形状。生产库 ``CrossRepoApiCall`` / ``ApiCallSite`` /
    ``ApiWrapper`` **均为 0 行**（上游产出器依赖 volar LSP，server 镜像无 Node，归
    LSP-01 / Phase 127），跨仓验收只能靠这个工厂造合成数据（D-26）。

    ⚠️ 这是 ``test_loader.py::_make_cross_repo_call`` 之外**有意的第二份实现**，不是遗漏。
    那个 helper 是 Phase 121 的既有回归资产；把它搬进 conftest 会改动一批已绿的 121 用例，
    跨模块 import 别的测试模块里的私有 helper 也不是本仓做法。两份各自演进，代价是几十行
    重复，收益是 121 的绿测不因 122 的需要而承担风险。

    ⚠️ 两端都**没有 ``Symbol`` 外键**，``CrossRepoApiCall`` 自身也**没有 ``repository``
    字段**——这正是 loader 必须做「文件路径 + 名字」二次解析的原因，也是 D-25 判定
    「跨仓穿越必须走 ORM 直查、不能靠图内 ``cross_repo`` 边」的事实依据。
    """
    from codegraph.models import ApiCallSite, ApiWrapper, CrossRepoApiCall, Endpoint

    def _create(
        repository,
        *,
        caller_file: str,
        caller_function: str,
        endpoint_file: str,
        handler_name: str,
        match_confidence: float = 0.7,
        caller_line: int = 33,
        endpoint_repository=None,
    ):
        target_repository = endpoint_repository or repository

        wrapper = ApiWrapper.objects.create(
            repository=repository,
            file_path="web/src/api/orders.ts",
            function_symbol=f"fetch_{handler_name}",
            http_method="GET",
            url_path_raw="/api/orders",
            url_path_pattern="/api/orders",
        )
        call_site = ApiCallSite.objects.create(
            repository=repository,
            api_wrapper=wrapper,
            caller_file=caller_file,
            caller_function=caller_function,
            line_number=caller_line,
        )
        endpoint = Endpoint.objects.create(
            repository=target_repository,
            http_method="GET",
            url_path="/api/orders",
            handler_name=handler_name,
            view_type="FUNCTION_VIEW",
            file_path=endpoint_file,
            line_number=8,
        )
        return CrossRepoApiCall.objects.create(
            call_site=call_site,
            endpoint=endpoint,
            match_confidence=match_confidence,
        )

    return _create

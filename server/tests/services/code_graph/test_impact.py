"""``services/code_graph/impact.py`` 的内核用例（覆盖 IMPACT-01 / 02 / 04）。

**本文件零数据库**：全部断言跑在 ``known_topology`` / ``hub_topology`` 两个合成冻结图上，
不起 Django ORM、不建库（D-01 的全部意义所在——内核是纯函数，只吃 ``MultiDiGraph``）。
⛔ 后续 plan 往本文件加用例时也不得引入数据库标记，需要库的分支请放 ``test_impact_shell.py``。

Wave 0（Plan 122-01）先落地 fixture 自检这一条真用例；其余用例以 skip 桩占位，由
``122-RESEARCH.md`` §Validation Architecture 表点名的后续 plan 逐条填实。
"""

from __future__ import annotations

import networkx as nx
import pytest


# 122-VALIDATION.md A1：Wave 0 地基自检。fixture 一旦退化（忘了 freeze、属性个数漂移、
# 少造了观察点），后面九个 plan 的断言会集体失去意义——所以这条必须先于它们绿。
def test_known_topology_fixture_is_frozen(known_topology: nx.MultiDiGraph) -> None:
    """合成图是冻结的 ``MultiDiGraph``，且节点/边属性个数与 Phase 121 的内存契约逐字一致。"""
    # 不冻结的话「内核不修改入参图」这条断言恒真（Phase 121 出图前也是这么冻的）。
    assert nx.is_frozen(known_topology) is True
    # DiGraph 会静默覆盖同一符号对的第二条边，四档边契约会直接失效。
    assert known_topology.is_multigraph() is True

    # A–H 八个 + 等长多解簇 P/Q/R/S 四个 + 只经裸名边可达的观察点 X。
    assert known_topology.number_of_nodes() == 13

    # 节点属性恒 5 个：signature 是 TextField、可长达数 KB，绝不放进节点属性。
    assert set(known_topology.nodes["A"]) == {
        "name",
        "symbol_type",
        "file_path",
        "start_line",
        "end_line",
    }

    # 边属性恒 3 个；cross_repo 档是唯一例外，多一个 match_confidence（原值，不归一化）。
    assert set(known_topology["F"]["A"][0]) == {
        "kind",
        "confidence",
        "line_number",
        "match_confidence",
    }
    assert set(known_topology["B"]["A"][0]) == {"kind", "confidence", "line_number"}


@pytest.mark.skip(reason="Wave 0 桩：由 122-03 落地")
def test_depth_grouping() -> None:
    """合成图上 d1/d2/d3 分组逐点正确；同符号多层出现取最浅；方向正确（下游不出现）。

    （Req: IMPACT-01, 决策: D-05）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-03 落地")
def test_max_depth_budget() -> None:
    """``max_depth`` 生效；超深节点不出现。

    （Req: IMPACT-01, 决策: D-05）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-03 落地")
def test_kernel_does_not_mutate_graph() -> None:
    """内核不修改入参图（fixture 已 ``freeze``，就地改必抛）。

    （Req: IMPACT-01, 决策: D-01）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-03 落地")
def test_edge_confidence_and_reason() -> None:
    """每条结果带 ``confidence`` 档 + ``reason``（经 ``derive_reason``）+ ``path_confidence``
    （= path min，D-07）。

    （Req: IMPACT-02, 决策: D-06 / D-07 / D-09）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-03 落地")
def test_min_confidence_filter() -> None:
    """``min_confidence`` 各阈值下结果集单调收缩；``cross_repo`` 用 ``match_confidence``
    原值参与比较（不归一化）。

    （Req: IMPACT-02, 决策: D-06 / D-13）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-03 落地")
def test_bare_name_requires_both_gates() -> None:
    """**D-08 双闸**：单开 ``include_low_confidence`` 或单降 ``min_confidence`` 都不足以让
    bare_name 边参与扩散。

    观察点用 ``known_topology`` 的 ``X``——它只有 ``X --bare_name--> B`` 一条出边，两道闸
    没同时开时它必须缺席。⛔ 不要改用 ``C``：``C`` 还有 ``C --resolved--> A``，用它会让本条
    用例恒真。

    （Req: IMPACT-02, 决策: D-08）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-03 落地")
def test_risk_levels() -> None:
    """四级风险分级在阈值边界（d1 = 2/3/7/8/19/20 与穿仓组合）上逐点正确。

    （Req: IMPACT-04, 决策: D-15 / D-29）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-03 落地")
def test_truncation_summary() -> None:
    """截断：``total_found``/``returned``/``truncated_by_depth`` 计数正确；排序键为
    「深度升序 + 置信度降序」且在截断前生效。

    （Req: IMPACT-04, 决策: D-16）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-06 落地")
def test_graph_cross_repo_edges_are_intra_repo() -> None:
    """**反向守护**：图里 ``kind == "cross_repo"`` 的边两端必在同仓，不得被标 ``cross_repo: true``。

    （Req: IMPACT-03, 决策: D-25）
    """
    pytest.fail("Wave 0 桩")

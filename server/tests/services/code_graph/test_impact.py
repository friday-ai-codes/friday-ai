"""``services/code_graph/impact.py`` 的内核用例（覆盖 IMPACT-01 / 02 / 04）。

**本文件零数据库**：全部断言跑在 ``known_topology`` / ``hub_topology`` 两个合成冻结图上，
不起 Django ORM、不建库（D-01 的全部意义所在——内核是纯函数，只吃 ``MultiDiGraph``）。
⛔ 后续 plan 往本文件加用例时也不得引入数据库标记，需要库的分支请放 ``test_impact_shell.py``。

Wave 0（Plan 122-01）先落地 fixture 自检这一条真用例；其余用例以 skip 桩占位，由
``122-RESEARCH.md`` §Validation Architecture 表点名的后续 plan 逐条填实。
"""

from __future__ import annotations

import networkx as nx


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

"""``services/code_graph/trace.py`` 的内核用例（覆盖 IMPACT-05）。

**本文件零数据库**：最短路、等长多解声明与「无路径」显式结构全部跑在 ``known_topology``
合成冻结图上（D-01）。⛔ 不得引入数据库标记——需要库的分支（重名候选要取
``Symbol.signature``）请放 ``test_symbol_resolve.py``。

Wave 0（Plan 122-01）只落骨架，用例由 122-04 填实。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 122-04 落地")
def test_shortest_path_hops() -> None:
    """最短路逐跳 ``file:line`` + ``kind`` + ``confidence`` 正确。

    （Req: IMPACT-05, 决策: D-18）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-04 落地")
def test_equal_length_paths_declared() -> None:
    """多条等长路径时返回第一条 + ``equal_length_path_count``（D-18）。

    用 ``known_topology`` 的等长多解簇：``P → Q → S`` 与 ``P → R → S`` 两条等长最短路。
    ⛔ 不要拿 ``D → A`` 试——那条只有一条最短路，声明恒为 1，验证不了任何东西。

    （Req: IMPACT-05, 决策: D-18）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 122-04 落地")
def test_no_path_explicit_structure() -> None:
    """不可达 → 显式「无路径」结构（含两端解析结果与 ``min_confidence``），⛔ 不是空数组（D-20）。

    （Req: IMPACT-05, 决策: D-20）
    """
    pytest.fail("Wave 0 桩")

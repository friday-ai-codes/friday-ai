"""``services/code_graph/loader.py`` 的装配用例（覆盖 GRAPH-01、GRAPH-03）。

本文件目前只有用例桩，由 **Plan 121-05**（MultiDiGraph 装配、分支 overlay）与
**Plan 121-06**（跨仓边二次解析、ChunkEdge 旁挂证据面、按需子图）填充。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import pytest


# 121-VALIDATION.md 121-05-T1：四类数据装配成 MultiDiGraph，节点/边计数与档位正确。
@pytest.mark.skip(reason="stub：由 Plan 121-05 实现")
def test_assembles_multidigraph() -> None:
    pass


# 121-VALIDATION.md 121-06-T1：CrossRepoApiCall 按 file+name 解析到符号；
# 解析不上直接丢弃（不建虚拟节点）并计数上报 cross_repo_unresolved_count（D-05）。
@pytest.mark.skip(reason="stub：由 Plan 121-06 实现")
def test_cross_repo_edge_resolution() -> None:
    pass


# 121-VALIDATION.md 121-05-T1：feature 分支 overlay（base ∪ feature），
# 同文件 feature 覆盖 base，去重键取整文件（D-06）。
@pytest.mark.skip(reason="stub：由 Plan 121-05 实现")
def test_branch_overlay_feature_over_base() -> None:
    pass


# 121-VALIDATION.md 121-06-T2：ChunkEdge 走旁挂证据面，绝不进 MultiDiGraph 边集
# （chunk 与 symbol 粒度不同，展开成符号级边会笛卡尔爆炸）。
@pytest.mark.skip(reason="stub：由 Plan 121-06 实现")
def test_chunk_evidence_side_channel() -> None:
    pass


# 121-VALIDATION.md 121-06-T3：按需子图在 SQL 侧多跳收敛，
# 查询次数不随仓库规模增长（深度有界，不先全量再裁剪）。
@pytest.mark.skip(reason="stub：由 Plan 121-06 实现")
def test_on_demand_subgraph_depth_bounded() -> None:
    pass

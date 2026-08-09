"""Process BFS / 社区分类验收桩（EXEC-01 / D-02 / D-05；T-126-04）。

Wave 0：节点名已登记；实现由 126-02 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 126-02/03/04/05 落地")


@_SKIP
def test_bfs_respects_depth_branching_min_steps_conf() -> None:
    """硬闸 maxDepth=10 / maxBranching=4 / minSteps=3 / conf≥0.5。

    （Req: EXEC-01, 决策: D-02, 威胁: T-126-04）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_cycle_marked_not_silently_skipped() -> None:
    """环检测后显式标注，不得静默跳过。

    （Req: EXEC-01, 决策: D-02）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_async_dispatch_boundary_not_crossed() -> None:
    """async 派发边界标 boundary，v1 不跨过。

    （Req: EXEC-01, 决策: D-02）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_community_class_intra_cross_unknown() -> None:
    """intra / cross / community_class_unknown 降级，不编造社区。

    （Req: EXEC-01, 决策: D-05）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_get_graph_only_no_loader_import() -> None:
    """静态：process_trace.py 不 import loader/cache；只经 get_graph_service。

    （Req: EXEC-01, 决策: D-03）
    """
    pytest.fail("Wave 0 桩")

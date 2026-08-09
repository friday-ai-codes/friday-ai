"""run_list_processes / run_get_process + 薄壳 call-through 验收桩（EXEC-02 / D-06）。

Wave 0：节点名已登记；实现由 126-03 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 126-02/03/04/05 落地")


@_SKIP
def test_run_list_processes_and_get_process() -> None:
    """共享编排：list 过滤/排序 + get by process_key；信封含 ok/staleness。

    默认 cross_community 优先排序。

    （Req: EXEC-02, 决策: D-06）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_mcp_list_get_process_call_through() -> None:
    """薄壳 View 只调 run_list_processes / run_get_process，无算法分叉。

    （Req: EXEC-02, 决策: D-06）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_agents_list_get_process_call_through() -> None:
    """@tool 同名只调同一 run_*。

    （Req: EXEC-02, 决策: D-06）
    """
    pytest.fail("Wave 0 桩")

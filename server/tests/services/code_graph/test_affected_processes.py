"""assemble_affected_processes 验收桩（EXEC-03 / D-07）。

Wave 0：节点名已登记；实现由 126-03 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 126-02/03/04/05 落地")


@_SKIP
def test_assemble_affected_processes_single_dialect() -> None:
    """输出键 name/process_key/affected_steps/total_steps/community_class。

    （Req: EXEC-03, 决策: D-07）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_run_impact_fills_affected_processes() -> None:
    """run_impact 信封回填 affected_processes（单一方言）。

    （Req: EXEC-03, 决策: D-07）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_run_detect_changes_fills_affected_processes() -> None:
    """run_detect_changes 信封回填 affected_processes。

    （Req: EXEC-03, 决策: D-07）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_no_intersection_returns_empty_list() -> None:
    """无 Process 行 / 无交集 → []（合法 fail-soft）。

    （Req: EXEC-03, 决策: D-07）
    """
    pytest.fail("Wave 0 桩")

"""process enqueue + QUEUE_GRAPH 验收桩（EXEC-01 / D-03）。

Wave 0：节点名已登记；实现由 126-02 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 126-02/03/04/05 落地")


@_SKIP
def test_enqueue_uses_queue_graph_and_process_lock() -> None:
    """idempotency_key / queueing_lock = process:{repo_id}:{branch}；QUEUE_GRAPH。

    （Req: EXEC-01, 决策: D-03）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_enqueue_passes_initiated_by_user_id() -> None:
    """enqueue 透传 initiated_by_user_id（无则 system）。

    （Req: EXEC-01, 决策: D-03）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_community_success_chains_process_enqueue() -> None:
    """run_community_rebuild 成功路径 best-effort enqueue；raise 不链式。

    （Req: EXEC-01, 决策: D-03）
    """
    pytest.fail("Wave 0 桩")

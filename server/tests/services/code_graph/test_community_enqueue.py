"""``services/community_enqueue.py`` + 钩子旁路 Wave 0 验收桩（MOD-01 / D-03）。

行为用例由 125-02 去 skip 填实。
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_enqueue_uses_queue_graph_and_community_lock() -> None:
    """``enqueue_community_rebuild`` 走 ``QUEUE_GRAPH`` 与 community 锁键。

    （Req: MOD-01, 决策: D-03, 威胁: T-125-05）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_enqueue_passes_initiated_by_user_id() -> None:
    """enqueue payload 携带 ``initiated_by_user_id``（观测绑定触发用户）。

    （Req: MOD-01, 决策: D-03）
    """
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason="Wave 0 桩：由 125-02 落地")
def test_hooks_enqueue_not_inline_louvain() -> None:
    """graph_builder / code_relations 钩子旁只调用 enqueue，不内联 Louvain。

    （Req: MOD-01, 决策: D-03）
    """
    pytest.fail("Wave 0 桩")

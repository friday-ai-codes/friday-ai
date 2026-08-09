"""Semgrep enqueue / QUEUE_SCAN 验收桩（D-02/D-04；归属 127-03）。

Wave 0：节点名可收集；实现由 127-03 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-03 落地")


@_SKIP
def test_enqueue_uses_queue_scan_and_slot_lock() -> None:
    """QUEUE_SCAN；idempotency_key=semgrep:{repo}:{mr_key}；scan-slot-*；N=2。

    （决策: D-02/D-04）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_enqueue_passes_initiated_by_user_id() -> None:
    """enqueue 透传 initiated_by_user_id（可观测绑定触发用户）。

    （决策: D-04）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_enqueue_failure_returns_none_not_raise() -> None:
    """enqueue 失败返回 None，不 raise 到建 MR。

    （决策: D-04；威胁: T-127-02）
    """
    pytest.fail("Wave 0 桩")

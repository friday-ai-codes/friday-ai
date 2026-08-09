"""Coding 建 MR 安全扫描挂点验收桩（TAINT-02；D-06；归属 127-04）。

Wave 0：节点名可收集；实现由 127-04 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-04 落地")


@_SKIP
def test_coding_create_mr_appends_security_scan_and_enqueues() -> None:
    """coding 缝调 append + enqueue；不阻断建 MR。

    （Req: TAINT-02, 决策: D-06）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_coding_security_scan_shell_failure_is_fail_open() -> None:
    """coding 路径 shell/scan 失败 fail-open，不阻断建 MR。

    （Req: TAINT-02, 决策: D-04/D-06；威胁: T-127-02）
    """
    pytest.fail("Wave 0 桩")

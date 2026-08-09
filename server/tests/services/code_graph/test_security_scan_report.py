"""Security scan MR 段文案验收桩（TAINT-02/03；D-06..D-09；归属 127-04）。

Wave 0：节点名可收集；实现由 127-04 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-04 落地")


@_SKIP
def test_append_security_scan_idempotent() -> None:
    """标记头 ``## 安全扫描``；已含则不重复；不覆盖 ``## 影响面``。

    （Req: TAINT-02, 决策: D-06）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_security_section_lists_severity_advisory() -> None:
    """ERROR/WARNING/INFO 分级展示；无 blocking raise。

    （Req: TAINT-02, 决策: D-07；威胁: T-127-05）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_security_section_has_ce_disclaimer() -> None:
    """CE 函数内 taint 边界文案。

    （Req: TAINT-03, 决策: D-07；威胁: T-127-05）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_security_section_nosemgrep_mention() -> None:
    """段内/文档句说明 ``nosemgrep``。

    （Req: TAINT-02, 决策: D-08）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_stub_omits_token_stack_and_abs_paths() -> None:
    """token/Traceback/绝对路径不得进 section。

    （Req: TAINT-03, 决策: D-09；威胁: T-127-01）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_pro_token_configured_line_without_hype() -> None:
    """有 token →「Pro 能力已启用」类短句且不夸大；空 token → 纯 CE。

    （Req: TAINT-03, 决策: D-09/D-10）
    """
    pytest.fail("Wave 0 桩")

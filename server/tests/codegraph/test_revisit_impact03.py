"""IMPACT-03 复验 / 诚实延期验收桩（D-17；归属 127-05）。

Wave 0：节点名可收集；实现由 127-05 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-05 落地")


@_SKIP
def test_revisit_impact03_zero_samples_honest_defer_path() -> None:
    """样本 0 → 诚实延期路径（不得宣称跨仓已验证）。

    （决策: D-17）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_revisit_impact03_positive_samples_invokes_four_branches() -> None:
    """样本 >0 → 四分支复验。

    （决策: D-17）
    """
    pytest.fail("Wave 0 桩")

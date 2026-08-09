"""rename_preview 只读双源验收桩（RENAME-01 / D-09/D-10/D-11；T-126-01/02/05）。

Wave 0：节点名已登记；实现由 126-04 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 126-02/03/04/05 落地")


@_SKIP
def test_applied_always_false() -> None:
    """applied 恒为 false；本相位无 apply/rewrite API。

    （Req: RENAME-01, 决策: D-09, 威胁: T-126-05）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_dual_source_confidence_graph_or_text_search() -> None:
    """置信标签二值：graph | text_search。

    （Req: RENAME-01, 决策: D-10）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_same_file_line_prefers_graph() -> None:
    """同 file:line 双源命中时保留一条并以 graph 为准。

    （Req: RENAME-01, 决策: D-10）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_grep_half_uses_grep_mirror_not_bare() -> None:
    """源文件静态禁止另起 walk/re 裸扫；须走 grep_mirror。

    （Req: RENAME-01, 决策: D-11, 威胁: T-126-01）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_disambiguation_or_unindexed_ok_false_not_fake_empty() -> None:
    """消歧/未索引失败 → ok=False，不静默空清单假装零引用。

    （Req: RENAME-01, 决策: D-11, 威胁: T-126-02）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_coverage_limitations_declared() -> None:
    """输出声明动态引用覆盖限制。

    （Req: RENAME-01, 决策: D-11）
    """
    pytest.fail("Wave 0 桩")

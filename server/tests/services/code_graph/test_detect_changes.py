"""``services/code_graph/detect_changes.py`` 纯内核用例（覆盖 DIFF-01 / DIFF-02）。

**本文件零数据库**：交叠 / rename 分类 / formatting / 阈值形状全部用字符串 fixture
与纯值断言，不起 Django ORM、不建库。
⛔ 后续 plan 往本文件加用例时也不得引入数据库标记；需要库或 mock mirror 的分支请放
``test_detect_changes_orchestrator.py``。

Wave 0（Plan 123-00）只登记 pytest 节点名；实现由 Plan 123-01 填实。
"""

from __future__ import annotations

import pytest

_WAVE0 = "Wave 0 桩：由 123-01 落地"


@pytest.mark.skip(reason=_WAVE0)
def test_ranges_overlap() -> None:
    """hunk 行区间 × Symbol 行区间求交命中（D-05）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_symbols_hit_by_old_hunk() -> None:
    """索引水位 old 侧 hunk 区间命中既有 Symbol（D-05）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_pure_insert_hunk_no_fake_uid() -> None:
    """纯新增 hunk → 文件级 added 摘要，不伪造 uid（D-05）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_rename_single_entry_not_delete_add() -> None:
    """纯 rename → 仅 renamed 一条，无 deleted+added 双列表（D-06 / DIFF-02）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_formatting_only_not_impact_seed() -> None:
    """formatting_only 不进入 impact 种子集（D-07）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_deleted_file_symbols_are_seeds() -> None:
    """整文件 delete → 旧路径符号 deleted，仍可作为 impact 种子（D-08）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_threshold_file_summary_shape() -> None:
    """>100 符号 → truncated / not_expanded 字段形状（纯函数侧，D-08）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_affected_symbol_min_fields() -> None:
    """受影响符号六字段 + file:line + changeType 枚举（D-15）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_exclusion_paths_absent() -> None:
    """交叠输入已过滤后输出不含排除路径（GRAPH-04 延续 / T-123-EXCL）。"""
    pytest.fail("Wave 0 桩")

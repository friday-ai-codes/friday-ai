"""_parse_numstat_output 单测。

覆盖 git diff --numstat -z 解析的四类输入（纯函数，无 DB / 无 subprocess）：
- 真实数字记录正确汇总
- 二进制文件（-\\t-）计 0（不累加，区别于真实 0）
- rename（-z 模式额外两个 NUL 路径字段）正确消费、不污染汇总
- multi-file 汇总各文件 added/deleted
"""

from __future__ import annotations

from services.indexer import _parse_numstat_output


def test_real_numstat() -> None:
    """单条真实记录 `3\\t1\\tfile.py\\0` → (3, 1)。"""
    assert _parse_numstat_output("3\t1\tfile.py\0") == (3, 1)


def test_binary_zero() -> None:
    """二进制文件 `-\\t-\\timg.png\\0` → (0, 0)（计 0，不累加）。"""
    assert _parse_numstat_output("-\t-\timg.png\0") == (0, 0)


def test_binary_mixed_with_real() -> None:
    """二进制与真实记录混合：仅真实记录累加，二进制计 0。"""
    output = "5\t2\ta.py\0-\t-\tb.png\0"
    assert _parse_numstat_output(output) == (5, 2)


def test_rename() -> None:
    """rename `0\\t0\\t\\0old.py\\0new.py\\0` → (0, 0) 且消费 old/new 不崩。"""
    assert _parse_numstat_output("0\t0\t\0old.py\0new.py\0") == (0, 0)


def test_rename_with_changes_then_real() -> None:
    """带行数变更的 rename 后接真实记录：rename 行数正确取前两列，old/new 不污染。"""
    # rename 记录（4 增 2 删，path 空 + old/new 两个 NUL 字段）后接一条普通记录
    output = "4\t2\t\0old/a.py\0new/a.py\0" + "1\t0\tb.py\0"
    assert _parse_numstat_output(output) == (5, 2)


def test_multi_file() -> None:
    """多条普通记录正确汇总。"""
    output = "3\t1\ta.py\0" + "10\t5\tb.py\0" + "0\t0\tc.py\0"
    assert _parse_numstat_output(output) == (13, 6)


def test_empty_output() -> None:
    """空输出 → (0, 0)，不抛错。"""
    assert _parse_numstat_output("") == (0, 0)


def test_dirty_record_skipped() -> None:
    """脏记录（前两列非数字、字段不足）跳过不抛错，仅累加合法记录。"""
    output = "x\ty\tbad.py\0" + "2\t3\tgood.py\0" + "incomplete\0"
    assert _parse_numstat_output(output) == (2, 3)

"""``services.repo_mirror.diff_mirror`` / ``ensure_mirror_sha`` 用例桩（DIFF-02）。

优先临时 bare repo + 直接调 helper；需要 settings 时再挂 django_db。
Wave 0（Plan 123-00）只登记节点；实现由 Plan 123-01 填实。
"""

from __future__ import annotations

import pytest

_WAVE0 = "Wave 0 桩：由 123-01 落地"


@pytest.mark.skip(reason=_WAVE0)
def test_diff_mirror_uses_find_renames() -> None:
    """diff argv 含 ``--find-renames`` 与 ``--unified=0``（D-06）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_diff_mirror_two_dot_not_three_dot() -> None:
    """diff 使用两-dot 区间；argv 不得出现三-dot ``...``（D-01）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_diff_mirror_rename_detected() -> None:
    """纯 rename commit → unified 含 rename 头（DIFF-02）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_ensure_mirror_sha_pins_object() -> None:
    """40 位 sha 可 fetch；不走 ``refs/heads/{sha}``（D-01）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_diff_mirror_output_byte_cap() -> None:
    """超 DETECT_CHANGES_MAX_DIFF_BYTES / 16MiB → MirrorError（T-123-DOS）。"""
    pytest.fail("Wave 0 桩")

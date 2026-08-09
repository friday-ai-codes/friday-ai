"""``run_detect_changes`` 编排壳用例桩（覆盖 D-01..D-04 / D-09..D-12 / D-14）。

与 ``test_detect_changes.py`` 的分工：内核是纯函数、零 DB；本文件测的是**编排壳**——
base pin、hard reject、batch ``run_impact``、staleness。需要库或 mock，故单独成文件。

Wave 0（Plan 123-00）只登记节点；实现由 Plan 123-02 填实。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

_WAVE0 = "Wave 0 桩：由 123-02 落地"


@pytest.mark.skip(reason=_WAVE0)
def test_diff_base_pinned_to_last_indexed() -> None:
    """mock mirror：diff argv 左端 == last_indexed_commit_sha（D-01）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_base_ref_declarative_only() -> None:
    """传 base_ref 不改变 argv 左端（D-02 / DIFF-02 / T-123-BASE）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_hard_reject_unindexed() -> None:
    """空索引 → ok=False repository_not_indexed，非空清单（D-03）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_hard_reject_mirror_error() -> None:
    """MirrorError → ok=False + error_code，非空清单（D-03）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_hard_reject_acl() -> None:
    """GraphAccessDenied → 上抛或 ok=False，无空成功 affected（D-03 / T-123-ACL）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_batch_impact_calls_run_impact_with_symbol_id() -> None:
    """spy：默认 max_depth=3 / min_confidence=1.0 / graph_branch=None（D-09/D-10）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_formatting_only_skipped_from_impact_seeds() -> None:
    """formatting_only 不进 batch impact 种子（D-07）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_threshold_skips_batch_impact() -> None:
    """>100 → 零次 run_impact + not_expanded（D-08 / T-123-DOS）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_impact_fail_soft_per_symbol() -> None:
    """单符号 GraphError → impact_error，整体 ok=True（D-12）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_staleness_behind_still_ok() -> None:
    """behind 大仍 ok=True + as_of（D-04/D-14）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_affected_processes_placeholder_empty() -> None:
    """affected_processes == []（D-12；Phase 126 回填）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_compare_equals_base_sha_explicit() -> None:
    """head == base → 明确 error_code 或空清单+声明，不静默可信无改动。"""
    pytest.fail("Wave 0 桩")

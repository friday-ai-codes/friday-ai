"""``services/code_graph/impact_report`` formatter / stub / 观测用例桩（DIFF-04）。

归属 Plan 124-02：mock ``run_detect_changes`` 边界，不重测 diff/BFS。
覆盖 D-05/D-07/D-08/D-09/D-10/D-11/D-12/D-15 与 T-124-02/03/04/05。

Wave 0（Plan 124-00）只登记 pytest 节点名；实现由 Plan 124-02 填实。
"""

from __future__ import annotations

import pytest

_WAVE0 = "Wave 0 桩：由 124-02/124-03 落地"


@pytest.mark.skip(reason=_WAVE0)
def test_build_impact_report_four_sections() -> None:
    """fixture 信封 → ``## 影响面`` + Changes/Affected/Risk/Recommendations 四段（D-07）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_ok_false_yields_stub_error_code() -> None:
    """``ok=False`` → 短 stub 含稳定 ``error_code``，不抛（D-11）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_timeout_yields_stub_timeout() -> None:
    """超时 → stub ``timeout``；不向上抛（D-10 / T-124-04）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_graph_access_denied_yields_stub_unavailable() -> None:
    """ACL / GraphAccessDenied → stub ``unavailable``，禁止空成功四段（T-124-05）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_partial_success_still_four_sections() -> None:
    """``ok=True`` + staleness/degradation 仍渲染完整四段（D-12）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_max_chars_truncation_note() -> None:
    """超软上限截断并注明 truncated（D-08）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_no_source_body_in_section() -> None:
    """段内无源码正文（T-124-03 / D-08）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_append_impact_report_idempotent() -> None:
    """已含影响面标记头则不重复 append。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_stub_omits_stack_and_secrets() -> None:
    """stub/日志无堆栈、token、绝对路径、凭证（T-124-02）。"""
    pytest.fail("Wave 0 桩")


@pytest.mark.skip(reason=_WAVE0)
def test_observability_events_static_names() -> None:
    """started/completed/failed 静态字面量；``initiated_by_user_id`` 有 user→str(id) / 无→system（D-15）。"""
    pytest.fail("Wave 0 桩")

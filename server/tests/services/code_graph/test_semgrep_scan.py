"""Semgrep CLI / fail-open 验收桩（TAINT-01；D-01..D-04；归属 127-03）。

Wave 0：节点名可收集；实现由 127-03 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-03 落地")


@_SKIP
def test_semgrep_argv_uses_baseline_commit_merge_base() -> None:
    """argv 含 scan、--baseline-commit=<merge-base>；禁止 ci 子命令；bin 来自 SEMGREP_BIN。

    （Req: TAINT-01, 决策: D-01..D-03）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_semgrep_never_imports_semgrep_module() -> None:
    """静态读 semgrep_scan.py 无 import semgrep（CLI only；不进 uv.lock）。

    （Req: TAINT-01, 决策: D-01）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_semgrep_fail_open_on_timeout_and_unavailable() -> None:
    """timeout/mirror/CLI → 稳定 error_code；不 raise 到建 MR。

    （Req: TAINT-01, 决策: D-04；威胁: T-127-02）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_semgrep_packs_from_semgrep_configs_setting() -> None:
    """SEMGREP_CONFIGS CSV → 多个 --config。

    （Req: TAINT-01, 决策: D-02）
    """
    pytest.fail("Wave 0 桩")

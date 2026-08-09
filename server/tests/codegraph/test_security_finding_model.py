"""SecurityFinding 模型验收桩（D-05；归属 127-02）。

Wave 0：节点名可收集；实现由 127-02 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-02 落地")


@_SKIP
def test_security_finding_required_fields() -> None:
    """SecurityFinding 必填字段可持久化（repo/path/check_id/severity 等）。

    （决策: D-05）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_security_finding_has_no_symbol_fk() -> None:
    """SecurityFinding 无 Symbol FK（软引用）。

    （决策: D-05）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_security_finding_message_expected_redacted_at_write_path() -> None:
    """写入路径过 redact_secrets_in_text——实现期断言 helper/service。

    （决策: D-05；威胁: T-127-01）
    """
    pytest.fail("Wave 0 桩")

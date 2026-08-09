"""SEMGREP_APP_TOKEN Fernet 写读验收桩（D-09；归属 127-02）。

Wave 0：节点名可收集；实现由 127-02 去 skip。
"""

from __future__ import annotations

import pytest

_SKIP = pytest.mark.skip(reason="Wave 0 桩：由 127-02 落地")


@_SKIP
def test_set_semgrep_app_token_encrypts_round_trip() -> None:
    """set → DB is_encrypted=True 且 value≠明文 → get 还原。

    （Req: TAINT-03, 决策: D-09；威胁: T-127-01）
    """
    pytest.fail("Wave 0 桩")


@_SKIP
def test_empty_token_means_ce() -> None:
    """空/缺失 → get \"\"（纯 CE）。

    （Req: TAINT-03, 决策: D-10）
    """
    pytest.fail("Wave 0 桩")

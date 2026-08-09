"""SEMGREP_APP_TOKEN Fernet 写读验收（D-09；归属 127-02）。"""

from __future__ import annotations

import pytest

from system.models import SettingKeys, SystemSetting


@pytest.mark.django_db
def test_set_semgrep_app_token_encrypts_round_trip() -> None:
    """set → DB is_encrypted=True 且 value≠明文 → get 还原。

    （Req: TAINT-03, 决策: D-09；威胁: T-127-01）
    """
    from services.code_graph.semgrep_token import (
        get_semgrep_app_token,
        set_semgrep_app_token,
    )

    plaintext = "sgp_test_token_not_for_logs"
    set_semgrep_app_token(plaintext)

    row = SystemSetting.objects.get(key=SettingKeys.SEMGREP_APP_TOKEN)
    assert row.is_encrypted is True
    assert row.value != plaintext
    assert plaintext not in row.value

    assert get_semgrep_app_token() == plaintext


@pytest.mark.django_db
def test_empty_token_means_ce() -> None:
    """空/缺失 → get \"\"（纯 CE）。

    （Req: TAINT-03, 决策: D-10）
    """
    from services.code_graph.semgrep_token import (
        get_semgrep_app_token,
        set_semgrep_app_token,
    )

    assert get_semgrep_app_token() == ""

    set_semgrep_app_token("sgp_temp")
    assert get_semgrep_app_token() == "sgp_temp"

    set_semgrep_app_token("")
    assert get_semgrep_app_token() == ""

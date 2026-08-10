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


@pytest.mark.django_db
def test_pro_enabled_honors_env_escape_hatch() -> None:
    """env escape hatch 打开 Pro 时判定也为 True（扫描与 MR 段口径一致）。

    （Req: TAINT-03, 决策: D-09；review: MJ-02）
    """
    from django.test import override_settings

    from services.code_graph.semgrep_token import (
        is_semgrep_pro_enabled,
        resolve_semgrep_app_token,
        set_semgrep_app_token,
    )

    set_semgrep_app_token("")
    with override_settings(SEMGREP_APP_TOKEN_ENV=""):
        assert is_semgrep_pro_enabled() is False

    with override_settings(SEMGREP_APP_TOKEN_ENV="sgp_env_only"):
        assert is_semgrep_pro_enabled() is True
        assert resolve_semgrep_app_token() == "sgp_env_only"

    # 加密 SystemSetting 优先于 env
    set_semgrep_app_token("sgp_db_wins")
    with override_settings(SEMGREP_APP_TOKEN_ENV="sgp_env_only"):
        assert resolve_semgrep_app_token() == "sgp_db_wins"
    set_semgrep_app_token("")


@pytest.mark.django_db
def test_mr_section_pro_line_follows_env_escape_hatch() -> None:
    """MR 段的 Pro 诚实声明与扫描注入共用同一判定入口。

    （Req: TAINT-03, 决策: D-09；review: MJ-02）
    """
    import inspect

    from services.code_graph import security_scan_report

    source = inspect.getsource(security_scan_report.patch_mr_security_scan_section)
    # 只查 get_semgrep_app_token 会漏掉 env escape hatch —— 必须走共享判定
    assert "is_semgrep_pro_enabled" in source
    assert "get_semgrep_app_token" not in source

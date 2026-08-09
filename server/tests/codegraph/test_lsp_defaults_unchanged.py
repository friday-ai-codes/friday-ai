"""LSP kill-switch 默认仍为 False + SEMGREP_* 默认（D-12/D-16/D-01/D-10；归属 127-02）。

Wave 0：真实静态断言（不 skip）——禁止盲翻 VOLAR/GOPLS 默认。
"""

from __future__ import annotations

from django.conf import settings


def test_volar_and_gopls_backend_defaults_false() -> None:
    """settings.VOLAR_BACKEND_ENABLED / GOPLS_BACKEND_ENABLED 默认 False。

    （Req: LSP-01, 决策: D-12/D-16）
    """
    assert settings.VOLAR_BACKEND_ENABLED is False
    assert settings.GOPLS_BACKEND_ENABLED is False


def test_semgrep_settings_defaults() -> None:
    """SEMGREP_BIN/TIMEOUT/墙钟/CONFIGS 默认对齐 D-01/D-04/D-10。

    （Req: TAINT-01, 决策: D-01/D-04/D-10）
    """
    assert settings.SEMGREP_BIN == "/opt/semgrep/bin/semgrep"
    assert settings.SEMGREP_TIMEOUT == 5
    assert settings.SEMGREP_TASK_TIMEOUT == 180
    configs = settings.SEMGREP_CONFIGS
    for pack in ("p/python", "p/django", "p/javascript", "p/typescript", "p/golang"):
        assert pack in configs

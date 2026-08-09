"""LSP kill-switch 默认仍为 False（D-12/D-16；归属 127-02/05）。

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

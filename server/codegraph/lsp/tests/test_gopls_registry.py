"""BACKEND_REGISTRY gopls kill-switch 守门测试（≥ 3 场景）。

覆盖：
- GOPLS_BACKEND_ENABLED=False 时 BACKEND_REGISTRY['go'] 仍为 tree-sitter（非 _GoplsLazyBackend）
- GOPLS_BACKEND_ENABLED=True 时 _register_gopls_backend 替换 BACKEND_REGISTRY['go']
- GOPLS_BACKEND_ENABLED=False 时 ready() 不调 _register_gopls_backend
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.conf import settings

from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.registry import BACKEND_REGISTRY


def _register_gopls_via_appconfig() -> None:
    """直接调 CodegraphConfig._register_gopls_backend（绕开 ready 钩子重入风险）。"""
    from codegraph.apps import CodegraphConfig

    config: CodegraphConfig = CodegraphConfig.create("codegraph")  # type: ignore[assignment]
    config._register_gopls_backend()


class TestGoplsRegistryKillSwitch:
    @pytest.fixture(autouse=False)
    def restore_go_registry(self) -> object:
        """备份 + 测试后还原 BACKEND_REGISTRY['go']（避免测试间污染）。"""
        original = BACKEND_REGISTRY.get("go")
        yield
        if original is None:
            BACKEND_REGISTRY.pop("go", None)
        else:
            BACKEND_REGISTRY["go"] = original

    def test_gopls_backend_not_registered_by_default(self) -> None:
        """GOPLS_BACKEND_ENABLED 默认 False → BACKEND_REGISTRY['go'] 不为 _GoplsLazyBackend。"""
        assert settings.GOPLS_BACKEND_ENABLED is False

        factory = BACKEND_REGISTRY.get("go")
        if factory is not None:
            instance = factory("go")
            from codegraph.lsp.gopls_backend import _GoplsLazyBackend
            assert not isinstance(instance, _GoplsLazyBackend), (
                "GOPLS_BACKEND_ENABLED=False 时 BACKEND_REGISTRY['go'] 不应为 _GoplsLazyBackend"
            )

    def test_gopls_backend_registered_when_enabled(
        self, restore_go_registry: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """调 _register_gopls_backend 后 BACKEND_REGISTRY['go'] 为 _GoplsLazyBackend 工厂。"""
        from codegraph.lsp.gopls_backend import _GoplsLazyBackend

        monkeypatch.setattr(settings, "GOPLS_BACKEND_ENABLED", True, raising=False)
        BACKEND_REGISTRY["go"] = TreeSitterBackend  # 设置 baseline

        _register_gopls_via_appconfig()

        factory = BACKEND_REGISTRY.get("go")
        assert factory is not None
        assert callable(factory)

        instance = factory("go")
        assert isinstance(instance, _GoplsLazyBackend), (
            "_register_gopls_backend 后 BACKEND_REGISTRY['go']('go') 应为 _GoplsLazyBackend"
        )

    def test_gopls_backend_enabled_false_does_not_call_register(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GOPLS_BACKEND_ENABLED=False 时 ready() 不调 _register_gopls_backend。"""
        from codegraph.apps import CodegraphConfig

        monkeypatch.setattr(settings, "GOPLS_BACKEND_ENABLED", False, raising=False)
        monkeypatch.setattr(settings, "VOLAR_BACKEND_ENABLED", False, raising=False)

        config: CodegraphConfig = CodegraphConfig.create("codegraph")  # type: ignore[assignment]

        with patch.object(config, "_register_gopls_backend") as mock_gopls:
            config.ready()
            mock_gopls.assert_not_called()

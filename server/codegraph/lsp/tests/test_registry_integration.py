"""implementation: registry 集成测试（apps.ready + EXTRACTOR_BACKENDS 切 volar + work item fallback）。

per implementation plan Task 3 acceptance：
- VOLAR_BACKEND_ENABLED=True：BACKEND_REGISTRY 5 项替换为 make_volar_backend 闭包
- VOLAR_BACKEND_ENABLED=False：BACKEND_REGISTRY 保 tree_sitter 默认
- 5 闭包都是 callable 且接受 1 arg
- work item 端到端：Vue 2.6- mock VolarPool.get raise → LspBackend 基类 fallback →
  TreeSitterBackend → 返 SymbolData
- LspUnhealthyError / LspDisabledError 路径走 fallback
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from django.conf import settings

from codegraph.backends.protocols import ExtractorBackend, TreeSitterBackend
from codegraph.extractors.base import FileContext, SymbolData
from codegraph.extractors.registry import BACKEND_REGISTRY
from codegraph.lsp.exceptions import LspDisabledError, LspUnhealthyError
from codegraph.lsp.supervisor import LspSupervisor
from codegraph.lsp.volar_backend import VolarBackend, make_volar_backend


@pytest.fixture
def clear_backend_registry() -> Any:
    """备份 + 测试后还原 BACKEND_REGISTRY 5 项（避免测试间污染）。"""
    languages = ("vue", "typescript", "tsx", "javascript", "jsx", "python", "go", "html", "css")
    backup = {lang: BACKEND_REGISTRY.get(lang) for lang in languages}
    yield
    for lang, value in backup.items():
        if value is None:
            BACKEND_REGISTRY.pop(lang, None)
        else:
            BACKEND_REGISTRY[lang] = value


def _register_via_appconfig() -> None:
    """直接调 CodegraphConfig._register_volar_backends（绕开 ready 钩子重入风险）。"""
    from codegraph.apps import CodegraphConfig

    config: CodegraphConfig = CodegraphConfig.create("codegraph")  # type: ignore[assignment]
    config._register_volar_backends()


def test_volar_backend_enabled_registers_5_languages(
    clear_backend_registry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VOLAR_BACKEND_ENABLED=True + _register_volar_backends → 5 项替换为闭包。"""
    monkeypatch.setattr(settings, "VOLAR_BACKEND_ENABLED", True, raising=False)
    # 强制 reset 5 项为 TreeSitterBackend baseline
    for lang in ("vue", "typescript", "tsx", "javascript", "jsx"):
        BACKEND_REGISTRY[lang] = TreeSitterBackend

    _register_via_appconfig()

    for lang in ("vue", "typescript", "tsx", "javascript", "jsx"):
        factory = BACKEND_REGISTRY.get(lang)
        assert factory is not None
        assert callable(factory)
        assert "make_volar_backend" in getattr(factory, "__qualname__", "")


def test_volar_backend_disabled_keeps_tree_sitter(
    clear_backend_registry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VOLAR_BACKEND_ENABLED=False → ready 跳过 _register_volar_backends。"""
    from codegraph.apps import CodegraphConfig

    monkeypatch.setattr(settings, "VOLAR_BACKEND_ENABLED", False, raising=False)
    # baseline：5 项都设为 TreeSitterBackend 类
    for lang in ("vue", "typescript", "tsx", "javascript", "jsx"):
        BACKEND_REGISTRY[lang] = TreeSitterBackend

    config: CodegraphConfig = CodegraphConfig.create("codegraph")  # type: ignore[assignment]
    config.ready()

    for lang in ("vue", "typescript", "tsx", "javascript", "jsx"):
        factory = BACKEND_REGISTRY.get(lang)
        # 仍是原 TreeSitterBackend 类（不是 make_volar_backend 闭包）
        assert factory is TreeSitterBackend


def test_5_factory_closures_are_callable_and_return_extractor_backend(
    clear_backend_registry: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5 闭包调用返 ExtractorBackend 实例（lazy 占位，hook 入口 raise → fallback）。"""
    monkeypatch.setattr(settings, "VOLAR_BACKEND_ENABLED", True, raising=False)
    _register_via_appconfig()

    for lang in ("vue", "typescript", "tsx", "javascript", "jsx"):
        factory = BACKEND_REGISTRY[lang]
        instance = factory(lang)
        assert isinstance(instance, ExtractorBackend)


def test_vue26_fallback_end_to_end_via_lsp_unhealthy_error(tmp_path: Any) -> None:
    """work item 端到端：mock supervisor raise LspUnhealthyError →
    LspBackend.extract_symbols 基类捕获 → TreeSitterBackend fallback 返 SymbolData。
    """
    file_path = tmp_path / "App.vue"
    file_path.write_text("export const x = 1\n")

    fake_supervisor = MagicMock(spec=LspSupervisor)
    fake_supervisor.name = "volar:vue26-app"
    fake_supervisor.call_async_in_loop.side_effect = LspUnhealthyError(
        "vue<2.7（实际 '2.6.14'）不支持 volar"
    )

    fake_fallback = MagicMock(spec=ExtractorBackend)
    fake_fallback.parse_file.return_value = "fake_tree"
    fake_fallback.extract_symbols.return_value = [
        SymbolData(
            name="MyComponent",
            symbol_type="CLASS",
            file_path=str(file_path),
            start_line=1,
            end_line=10,
        )
    ]

    backend = VolarBackend(
        language="vue",
        supervisor=fake_supervisor,
        fallback=fake_fallback,
    )
    ctx = FileContext(file_path=str(file_path), language="vue", repository_id="r1")
    handle = backend.parse_file(str(file_path), file_path.read_text())

    result = backend.extract_symbols(handle, file_path.read_text(), ctx)

    assert len(result) == 1
    assert result[0].name == "MyComponent"
    fake_fallback.extract_symbols.assert_called_once()


def test_lsp_disabled_falls_through_to_tree_sitter(tmp_path: Any) -> None:
    """通用 LspDisabledError → 基类 fallback 路径同样生效。"""
    file_path = tmp_path / "x.ts"
    file_path.write_text("export const a = 1\n")

    fake_supervisor = MagicMock(spec=LspSupervisor)
    fake_supervisor.call_async_in_loop.side_effect = LspDisabledError("disabled")

    fake_fallback = MagicMock(spec=ExtractorBackend)
    fake_fallback.parse_file.return_value = "fake_tree"
    fake_fallback.extract_symbols.return_value = [
        SymbolData(
            name="a",
            symbol_type="VARIABLE",
            file_path=str(file_path),
            start_line=1,
            end_line=1,
        )
    ]

    backend = VolarBackend(
        language="typescript",
        supervisor=fake_supervisor,
        fallback=fake_fallback,
    )
    ctx = FileContext(file_path=str(file_path), language="typescript", repository_id="r1")
    handle = backend.parse_file(str(file_path), file_path.read_text())
    result = backend.extract_symbols(handle, file_path.read_text(), ctx)
    assert len(result) == 1
    assert result[0].name == "a"


def test_settings_extractor_backends_5_languages_are_volar() -> None:
    """settings.EXTRACTOR_BACKENDS 含 5 项 'volar' + 4 项 tree_sitter（python/go/html/css）。"""
    volar_keys = {k for k, v in settings.EXTRACTOR_BACKENDS.items() if v == "volar"}
    assert volar_keys == {"typescript", "tsx", "vue", "javascript", "jsx"}
    assert settings.EXTRACTOR_BACKENDS["python"] == "tree_sitter"
    assert settings.EXTRACTOR_BACKENDS["go"] == "tree_sitter"
    assert settings.EXTRACTOR_BACKENDS["html"] == "tree_sitter"
    assert settings.EXTRACTOR_BACKENDS["css"] == "tree_sitter"


def test_make_volar_backend_qualname_signature() -> None:
    """make_volar_backend 闭包 qualname 含 'make_volar_backend'（守门 grep gate 5）。"""
    factory = make_volar_backend("vue")
    assert "make_volar_backend" in factory.__qualname__

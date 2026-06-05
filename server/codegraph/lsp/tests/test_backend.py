"""initial implementation: LspBackend 抽象基类 + 工厂 + supervisor 单例工厂单元测试。

覆盖 V1（ExtractorBackend Protocol 兼容）+ V2（fallback 4×4 parametrize）+
V5（4 fallback 事件名）+ P14（make_lsp_backend 工厂闭包）+ work item（单例）。
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from structlog.testing import capture_logs

from codegraph.backends.protocols import ExtractorBackend
from codegraph.extractors.base import (
    CallData,
    EndpointData,
    FileContext,
    ImportData,
    SymbolData,
)
from codegraph.lsp import get_or_create_supervisor
from codegraph.lsp.backend import LspBackend, make_lsp_backend
from codegraph.lsp.exceptions import (
    LspDisabledError,
    LspError,
    LspTimeoutError,
    LspUnhealthyError,
)
from codegraph.lsp.supervisor import LspSupervisor


class _StubLspBackend(LspBackend):
    """测试用 stub 子类（默认 hook 走 NotImplementedError，测试 patch 后覆盖）。"""

    name = "stub"
    language_ids = ["plaintext"]
    command = ["echo", "stub"]

    def _lsp_extract_symbols(
        self, tree: Any, source: str, ctx: FileContext
    ) -> list[SymbolData]:
        raise NotImplementedError("stub override; tests should patch this")

    def _lsp_extract_imports(
        self, tree: Any, ctx: FileContext
    ) -> list[ImportData]:
        raise NotImplementedError("stub override")

    def _lsp_extract_calls(
        self, tree: Any, ctx: FileContext
    ) -> list[CallData]:
        raise NotImplementedError("stub override")

    def _lsp_extract_endpoints(
        self, tree: Any, source: str, ctx: FileContext
    ) -> list[EndpointData]:
        raise NotImplementedError("stub override")


# =============================================================================
# V1: ExtractorBackend Protocol 兼容
# =============================================================================


def test_lsp_backend_subclass_implements_extractor_backend_protocol() -> None:
    """子类实例满足 ExtractorBackend Protocol（@runtime_checkable）。"""
    sup = MagicMock(spec=LspSupervisor)
    fallback = MagicMock(spec=ExtractorBackend)
    instance = _StubLspBackend(language="python", supervisor=sup, fallback=fallback)
    assert isinstance(instance, ExtractorBackend)


def test_lsp_backend_5_methods_signatures_match_protocol() -> None:
    """5 个方法签名兼容 ExtractorBackend Protocol。"""
    extract_symbols_params = list(
        inspect.signature(LspBackend.extract_symbols).parameters.keys()
    )
    assert extract_symbols_params == ["self", "tree", "source", "ctx"]

    extract_imports_params = list(
        inspect.signature(LspBackend.extract_imports).parameters.keys()
    )
    assert extract_imports_params == ["self", "tree", "ctx"]

    extract_calls_params = list(
        inspect.signature(LspBackend.extract_calls).parameters.keys()
    )
    assert extract_calls_params == ["self", "tree", "ctx"]

    extract_endpoints_params = list(
        inspect.signature(LspBackend.extract_endpoints).parameters.keys()
    )
    assert extract_endpoints_params == ["self", "tree", "source", "ctx"]

    parse_file_params = list(
        inspect.signature(LspBackend.parse_file).parameters.keys()
    )
    assert parse_file_params == ["self", "file_path", "source"]


# =============================================================================
# V1: abstract hook 强制覆写
# =============================================================================


def test_lsp_backend_cannot_be_instantiated_directly() -> None:
    """LspBackend 抽象，不可直接实例化（abc 强制）。"""
    sup = MagicMock(spec=LspSupervisor)
    with pytest.raises(TypeError, match="abstract"):
        LspBackend(language="python", supervisor=sup)  # type: ignore[abstract]


def test_5_abstract_hooks_raise_not_implemented_error_in_base_class() -> None:
    """4 个 abstract hook 在基类内 raise NotImplementedError 含 266 字面。"""
    sup = MagicMock(spec=LspSupervisor)
    fallback = MagicMock(spec=ExtractorBackend)
    instance = _StubLspBackend(language="python", supervisor=sup, fallback=fallback)
    ctx = FileContext(file_path="x.py", language="python", repository_id="r1")

    for hook_name in (
        "_lsp_extract_symbols",
        "_lsp_extract_imports",
        "_lsp_extract_calls",
        "_lsp_extract_endpoints",
    ):
        base_hook = getattr(LspBackend, hook_name)
        with pytest.raises(NotImplementedError, match="266"):
            if hook_name in ("_lsp_extract_symbols", "_lsp_extract_endpoints"):
                base_hook(instance, None, "", ctx)
            else:
                base_hook(instance, None, ctx)


# =============================================================================
# V2: 4 类异常 × 4 维 fallback parametrize
# =============================================================================


def _build_backend_with_fallback() -> tuple[_StubLspBackend, MagicMock]:
    sup = MagicMock(spec=LspSupervisor)
    fallback = MagicMock(spec=ExtractorBackend)
    fallback.parse_file = MagicMock(return_value="ts_tree_stub")
    backend = _StubLspBackend(language="python", supervisor=sup, fallback=fallback)
    return backend, fallback


@pytest.mark.parametrize(
    "exc_cls",
    [LspError, LspTimeoutError, LspUnhealthyError, LspDisabledError],
)
def test_extract_symbols_falls_back_on_exception(
    exc_cls: type[Exception],
) -> None:
    backend, fallback = _build_backend_with_fallback()
    fallback.extract_symbols = MagicMock(
        return_value=[
            SymbolData(
                name="X",
                symbol_type="FUNCTION",
                file_path="x.py",
                start_line=1,
                end_line=1,
            )
        ]
    )
    with patch.object(
        backend, "_lsp_extract_symbols", side_effect=exc_cls("simulated")
    ):
        ctx = FileContext(file_path="x.py", language="python", repository_id="r1")
        result = backend.extract_symbols(tree=None, source="src", ctx=ctx)

    assert fallback.parse_file.called
    assert fallback.extract_symbols.called
    assert len(result) == 1
    assert result[0].name == "X"


@pytest.mark.parametrize(
    "exc_cls",
    [LspError, LspTimeoutError, LspUnhealthyError, LspDisabledError],
)
def test_extract_imports_falls_back_on_exception(
    exc_cls: type[Exception],
) -> None:
    backend, fallback = _build_backend_with_fallback()
    fallback.extract_imports = MagicMock(
        return_value=[ImportData(source_file="x.py", target_module="os")]
    )
    with patch.object(
        backend, "_lsp_extract_imports", side_effect=exc_cls("simulated")
    ):
        ctx = FileContext(file_path="x.py", language="python", repository_id="r1")
        result = backend.extract_imports(tree=None, ctx=ctx)

    assert fallback.parse_file.called
    assert fallback.extract_imports.called
    assert result[0].target_module == "os"


@pytest.mark.parametrize(
    "exc_cls",
    [LspError, LspTimeoutError, LspUnhealthyError, LspDisabledError],
)
def test_extract_calls_falls_back_on_exception(
    exc_cls: type[Exception],
) -> None:
    backend, fallback = _build_backend_with_fallback()
    fallback.extract_calls = MagicMock(
        return_value=[
            CallData(
                caller_key=("x.py", "foo", 1),
                callee_name="bar",
                call_type="DIRECT",
                line_number=2,
            )
        ]
    )
    with patch.object(
        backend, "_lsp_extract_calls", side_effect=exc_cls("simulated")
    ):
        ctx = FileContext(file_path="x.py", language="python", repository_id="r1")
        result = backend.extract_calls(tree=None, ctx=ctx)

    assert fallback.parse_file.called
    assert fallback.extract_calls.called
    assert result[0].callee_name == "bar"


@pytest.mark.parametrize(
    "exc_cls",
    [LspError, LspTimeoutError, LspUnhealthyError, LspDisabledError],
)
def test_extract_endpoints_falls_back_on_exception(
    exc_cls: type[Exception],
) -> None:
    backend, fallback = _build_backend_with_fallback()
    fallback.extract_endpoints = MagicMock(
        return_value=[
            EndpointData(
                http_method="GET",
                url_path="/api/foo",
                handler_name="views.foo",
                view_type="FUNCTION_VIEW",
                file_path="x.py",
                line_number=1,
            )
        ]
    )
    with patch.object(
        backend, "_lsp_extract_endpoints", side_effect=exc_cls("simulated")
    ):
        ctx = FileContext(file_path="x.py", language="python", repository_id="r1")
        result = backend.extract_endpoints(tree=None, source="src", ctx=ctx)

    assert fallback.parse_file.called
    assert fallback.extract_endpoints.called
    assert result[0].url_path == "/api/foo"


# =============================================================================
# V5: 4 fallback 事件名（per work item）
# =============================================================================


def test_fallback_emits_structlog_event_per_dimension() -> None:
    """4 维 extract 各触发对应 fallback 事件，含 language / file_path / error_class。"""
    backend, fallback = _build_backend_with_fallback()
    fallback.extract_symbols = MagicMock(return_value=[])
    fallback.extract_imports = MagicMock(return_value=[])
    fallback.extract_calls = MagicMock(return_value=[])
    fallback.extract_endpoints = MagicMock(return_value=[])

    ctx = FileContext(file_path="x.py", language="python", repository_id="r1")

    with capture_logs() as cap:
        with patch.object(
            backend, "_lsp_extract_symbols", side_effect=LspError("e1")
        ):
            backend.extract_symbols(tree=None, source="src", ctx=ctx)
        with patch.object(
            backend, "_lsp_extract_imports", side_effect=LspTimeoutError("e2")
        ):
            backend.extract_imports(tree=None, ctx=ctx)
        with patch.object(
            backend, "_lsp_extract_calls", side_effect=LspUnhealthyError("e3")
        ):
            backend.extract_calls(tree=None, ctx=ctx)
        with patch.object(
            backend, "_lsp_extract_endpoints", side_effect=LspDisabledError("e4")
        ):
            backend.extract_endpoints(tree=None, source="src", ctx=ctx)

    events = {log.get("event") for log in cap}
    assert "lsp_extract_symbols_fallback" in events
    assert "lsp_extract_imports_fallback" in events
    assert "lsp_extract_calls_fallback" in events
    assert "lsp_extract_endpoints_fallback" in events

    fallback_logs = [
        log for log in cap if log.get("event", "").endswith("_fallback")
    ]
    for log in fallback_logs:
        assert "language" in log
        assert "file_path" in log
        assert "error_class" in log


# =============================================================================
# P14: make_lsp_backend 工厂闭包
# =============================================================================


def test_make_lsp_backend_returns_callable() -> None:
    """make_lsp_backend 返 callable；本 phase 调用即 raise NotImplementedError 含 266。"""
    factory = make_lsp_backend("volar")
    assert callable(factory)
    with pytest.raises(NotImplementedError, match="266"):
        factory("vue")


# =============================================================================
# work item: get_or_create_supervisor 单例工厂
# =============================================================================


def test_get_or_create_supervisor_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同 name 多次调用返同一实例；atexit.register 仅触发 1 次。"""
    from django.conf import settings as dj_settings

    monkeypatch.setattr(
        dj_settings,
        "LSP_SERVERS",
        {
            "singleton_stub": {
                "command": ["echo", "stub"],
                "language_ids": ["plaintext"],
                "workspace_root": "/tmp",
            }
        },
        raising=False,
    )

    # 清空既有缓存
    import codegraph.lsp as lsp_pkg

    monkeypatch.setattr(lsp_pkg, "_SUPERVISORS", {})

    atexit_calls: list[object] = []

    def fake_atexit_register(fn: object, *args: object, **kwargs: object) -> None:
        atexit_calls.append(fn)

    monkeypatch.setattr("atexit.register", fake_atexit_register)

    sup1 = get_or_create_supervisor("singleton_stub")
    sup2 = get_or_create_supervisor("singleton_stub")

    assert sup1 is sup2
    assert len(atexit_calls) == 1


def test_get_or_create_supervisor_raises_keyerror_when_unknown_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未知 name 触发 KeyError 含 name 字面。"""
    from django.conf import settings as dj_settings

    monkeypatch.setattr(dj_settings, "LSP_SERVERS", {}, raising=False)
    import codegraph.lsp as lsp_pkg

    monkeypatch.setattr(lsp_pkg, "_SUPERVISORS", {})

    with pytest.raises(KeyError, match="unknown"):
        get_or_create_supervisor("unknown")

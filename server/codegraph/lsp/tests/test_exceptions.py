"""initial implementation: 5 类 LSP 异常体系单元测试。"""

from __future__ import annotations

import pytest

from codegraph.lsp.exceptions import (
    LspDisabledError,
    LspError,
    LspStartupError,
    LspTimeoutError,
    LspUnhealthyError,
)


def test_lsp_error_is_base_class() -> None:
    """4 个子类全部继承 LspError 兜底基类。"""
    assert issubclass(LspStartupError, LspError)
    assert issubclass(LspTimeoutError, LspError)
    assert issubclass(LspUnhealthyError, LspError)
    assert issubclass(LspDisabledError, LspError)


def test_exceptions_are_distinct() -> None:
    """4 子类之间互不继承（避免误捕获 / 误升级路径）。"""
    assert not issubclass(LspTimeoutError, LspStartupError)
    assert not issubclass(LspStartupError, LspTimeoutError)
    assert not issubclass(LspDisabledError, LspUnhealthyError)
    assert not issubclass(LspUnhealthyError, LspDisabledError)
    assert not issubclass(LspStartupError, LspDisabledError)
    assert not issubclass(LspTimeoutError, LspUnhealthyError)


def test_raise_from_chain_preserved() -> None:
    """raise ... from 链路 __cause__ 字段保留底层 ValueError。"""
    cause = ValueError("底层错误")
    try:
        raise LspStartupError("启动失败") from cause
    except LspStartupError as exc:
        assert exc.__cause__ is cause
        assert isinstance(exc.__cause__, ValueError)


def test_can_catch_all_via_lsp_error() -> None:
    """4 子类实例都能被 try / except LspError 兜底捕获。"""
    for exc_cls in (
        LspStartupError,
        LspTimeoutError,
        LspUnhealthyError,
        LspDisabledError,
    ):
        with pytest.raises(LspError):
            raise exc_cls("测试")


def test_lsp_error_message_preserved() -> None:
    """异常 str(...) 保留原始信息（含数值字面，便于运维 grep）。"""
    err = LspTimeoutError("timeout 10s")
    assert "timeout 10s" in str(err)

    err2 = LspDisabledError("crash-loop after 3 attempts")
    assert "crash-loop" in str(err2)
    assert "3" in str(err2)

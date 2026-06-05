"""Provider 注册表 frozen 行为锁定测试 —— per implementation contract / contract。

CONTEXT.md contract 字面要求::

    PROVIDER_REGISTRY: Mapping[str, type[BaseCodeProvider]] = MappingProxyType({...})

implementation 在 implementation 既有 ``register_provider`` + ``freeze`` 之上：
追加 ``PROVIDER_REGISTRY`` 模块级只读视图（``types.MappingProxyType`` 包装内部
``_REGISTRY`` dict），形成"双层防御"：

1. **运行时写守卫**：``PROVIDER_REGISTRY["x"] = ...`` / ``del PROVIDER_REGISTRY["x"]``
   抛 ``TypeError``（mappingproxy 不支持 ``__setitem__`` / ``__delitem__``）。
2. **生命周期守卫**：``register_provider`` 在 ``freeze()`` 后抛 ``RuntimeError``
   （implementation contract 既有行为，本套件回归保护）。

外部模块只能通过 ``PROVIDER_REGISTRY`` 视图读 provider 实例；底层 ``_REGISTRY``
不在 ``__all__`` 暴露（Python 语义限制：仍可通过 ``from ... import _REGISTRY``
访问，但走视图是上游契约）。
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

import pytest

from services.code_intel import PROVIDER_REGISTRY
from services.code_intel.null_provider import NullProvider
from services.code_intel.protocols import BaseCodeProvider
from services.code_intel.registry import (
    _REGISTRY,
    _reset_for_tests,
    freeze,
    get_provider,
    is_frozen,
    register_provider,
)


@pytest.fixture(autouse=True)
def _registry_isolation():
    """snapshot + restore module-level _REGISTRY，防 reset 抹掉 AppConfig.ready()
    注册的 LocalProvider 致后续依赖 get_provider() 的套件全部失败（Rule 1 bug
    回归保护）。

    teardown 步骤：
      1. ``_reset_for_tests()`` 清空 _REGISTRY 与 _FROZEN
      2. ``_REGISTRY.update(snapshot)`` 还原 ready() 注册的 default provider
      3. ``freeze()`` 还原 module-level frozen 状态（与 AppConfig.ready() 末尾一致）
    """
    snapshot: dict[str, BaseCodeProvider] = dict(_REGISTRY)
    snapshot_frozen: bool = is_frozen()
    _reset_for_tests()
    try:
        yield
    finally:
        _reset_for_tests()
        _REGISTRY.update(snapshot)
        if snapshot_frozen:
            freeze()


def _setup_default_provider() -> NullProvider:
    """注册 default + freeze，返回注册的实例供断言对照。"""
    provider = NullProvider()
    register_provider("default", provider)
    freeze()
    return provider


def test_provider_registry_is_mappingproxy_instance() -> None:
    """PROVIDER_REGISTRY 实例类型必须是 ``types.MappingProxyType``。

    类型守卫：上游模块若误把 PROVIDER_REGISTRY 当 dict 调 .update()，必须 AttributeError，
    本测试通过 isinstance 锁定该契约（per context contract 字面要求）。
    """
    assert isinstance(PROVIDER_REGISTRY, MappingProxyType), (
        f"PROVIDER_REGISTRY must be MappingProxyType, got {type(PROVIDER_REGISTRY).__name__}"
    )
    assert isinstance(PROVIDER_REGISTRY, Mapping), (
        "MappingProxyType is also a Mapping (PEP 234) — read-only typing alias 应兼容"
    )


def test_provider_registry_frozen_mapping_rejects_setitem() -> None:
    """``PROVIDER_REGISTRY["new"] = NullProvider()`` 抛 TypeError（per contract）。"""
    _setup_default_provider()

    with pytest.raises(TypeError, match="does not support item assignment"):
        PROVIDER_REGISTRY["new"] = NullProvider()  # type: ignore[index]


def test_provider_registry_frozen_mapping_rejects_delitem() -> None:
    """``del PROVIDER_REGISTRY["default"]`` 抛 TypeError（mappingproxy 不可删）。"""
    _setup_default_provider()

    with pytest.raises(TypeError, match="does not support item deletion"):
        del PROVIDER_REGISTRY["default"]  # type: ignore[attr-defined]


def test_register_provider_after_freeze_raises_runtime_error() -> None:
    """freeze() 后调 register_provider 抛 RuntimeError（implementation contract 行为回归）。"""
    _setup_default_provider()

    assert is_frozen() is True
    with pytest.raises(RuntimeError, match="frozen"):
        register_provider("malicious", NullProvider())


def test_provider_registry_view_reflects_default_provider() -> None:
    """freeze 后 ``PROVIDER_REGISTRY["default"]`` 与 ``get_provider()`` 返同实例。

    视图必须与底层 dict **同步**——MappingProxyType 不复制底层 dict，仅暴露只读
    视图，意味着 register_provider 写入对视图立即可见。
    """
    expected = _setup_default_provider()

    assert PROVIDER_REGISTRY["default"] is expected
    assert get_provider("default") is expected
    assert PROVIDER_REGISTRY["default"] is get_provider("default")
    assert isinstance(PROVIDER_REGISTRY["default"], BaseCodeProvider)


def test_freeze_idempotent() -> None:
    """连续两次 freeze() 不抛错（implementation 既有行为回归）。"""
    register_provider("default", NullProvider())
    freeze()
    freeze()
    assert is_frozen() is True


def test_provider_registry_supports_iteration_read_only() -> None:
    """视图支持 keys() / items() / iter / len / contains 五种只读操作。

    确保上游 `for k in PROVIDER_REGISTRY` / `"default" in PROVIDER_REGISTRY`
    等读路径不被 MappingProxyType 包装破坏。
    """
    _setup_default_provider()

    assert list(PROVIDER_REGISTRY.keys()) == ["default"]
    items = list(PROVIDER_REGISTRY.items())
    assert len(items) == 1 and items[0][0] == "default"
    assert "default" in PROVIDER_REGISTRY
    assert len(PROVIDER_REGISTRY) == 1
    assert [k for k in PROVIDER_REGISTRY] == ["default"]

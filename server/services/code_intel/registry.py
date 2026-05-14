"""代码智能 Provider 单例 registry (per Phase / + Phase / ).
设计要点：
- 由 ``CodeIntelConfig.ready`` 一次性 ``register_provider("default", instance)``
 后立刻 ``freeze``；之后任何 ``register_provider`` 调用都会 raise RuntimeError，
 防止 web 请求生命周期内被恶意/误用代码重新注册（T-，Phase）。
- ``get_provider`` 是 module-level 单例入口；上游统一通过本函数取实例，
 禁止跨包直接 ``import LocalProvider``，确保 settings 切换 RemoteProvider 时
 一处替换全局生效。
- ``PROVIDER_REGISTRY`` 是 ``types.MappingProxyType`` 包装的**只读视图**
 （per Phase / / T-）：试图
 ``PROVIDER_REGISTRY["x"] = ...`` / ``del PROVIDER_REGISTRY["x"]``
 抛 ``TypeError``，与 ``register_provider`` freeze 后 ``RuntimeError`` 形成
 双层防御；视图与底层 ``_REGISTRY`` 同生命周期，``register_provider`` /
 ``_reset_for_tests`` 写入对视图立即可见。
"""
from __future__ import annotations
from types import MappingProxyType
from typing import Mapping
from services.code_intel.protocols import BaseCodeProvider
_REGISTRY: dict[str, BaseCodeProvider] = {}
_FROZEN: bool = False
PROVIDER_REGISTRY: Mapping[str, BaseCodeProvider] = MappingProxyType(_REGISTRY)
"""Provider 注册表只读视图（per Phase / ）。
外部模块通过本视图读 provider 实例（``PROVIDER_REGISTRY["default"]``）。
mappingproxy 不支持 ``__setitem__`` / ``__delitem__`` / ``.update`` 等
任何写操作——runtime 注入恶意 Provider 的所有路径都会抛 ``TypeError``
（T- mitigation）。底层 ``_REGISTRY`` dict 通过 ``register_provider``
+ ``freeze`` 双重生命周期守卫（T- / ）独占写入。
"""
def register_provider(key: str, provider: BaseCodeProvider) -> None:
 """注册 Provider 单例。仅 AppConfig.ready 期可调，之后 frozen。"""
 global _FROZEN
 if _FROZEN:
 raise RuntimeError(
 "code_intel registry is frozen; "
 "web request lifecycle cannot register new providers (per, T-)"
 )
 # 修复（Phase REVIEW）：``@runtime_checkable Protocol + isinstance``
 # 检查的就是**结构化兼容**（有 capabilities attribute + health_check
 # method），任何带这两个属性的类都会通过——所以这层**不是安全边界**，纯
 # 类型卫生：防 register_provider("default", 42)、拼错方法名、传入完全无关
 # 类等类型错误。控制 env / 进程内代码的 attacker 已绕过本检查。
 if not isinstance(provider, BaseCodeProvider):
 raise TypeError(
 f"provider must implement BaseCodeProvider Protocol "
 f"(structured contract: capabilities + health_check), "
 f"got {type(provider).__name__}"
 )
 _REGISTRY[key] = provider
def freeze -> None:
 """冻结 registry —— 由 AppConfig.ready 末尾调用。"""
 global _FROZEN
 _FROZEN = True
def is_frozen -> bool:
 """暴露给测试用的探测接口。"""
 return _FROZEN
def get_provider(key: str = "default") -> BaseCodeProvider:
 """取 Provider 单例。
 Args:
 key: 注册 key，默认 ``"default"``（CodeIntelConfig.ready 注册）。
 Raises:
 LookupError: 当 key 未注册时（通常意味着 Django apps loading 顺序出错）。
 """
 try:
 return _REGISTRY[key]
 except KeyError as exc:
 raise LookupError(
 f"code_intel provider '{key}' not registered; "
 "ensure 'services.code_intel.apps.CodeIntelConfig' is in INSTALLED_APPS"
 ) from exc
def _reset_for_tests -> None:
 """测试用 reset 钩子（仅在 pytest 上下文调用，per 不暴露给业务）。"""
 global _FROZEN
 _REGISTRY.clear
 _FROZEN = False
__all__ = [
 "PROVIDER_REGISTRY",
 "freeze",
 "get_provider",
 "is_frozen",
 "register_provider",
]

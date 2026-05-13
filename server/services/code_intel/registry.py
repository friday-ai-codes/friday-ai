"""代码智能 Provider 单例 registry (per Phase / ).
设计要点（per ）：
- 由 ``CodeIntelConfig.ready`` 一次性 ``register_provider("default", instance)``
 后立刻 ``freeze``；之后任何 ``register_provider`` 调用都会 raise RuntimeError，
 防止 web 请求生命周期内被恶意/误用代码重新注册（T-）。
- ``get_provider`` 是 module-level 单例入口；上游统一通过本函数取实例，
 禁止跨包直接 ``import LocalProvider``，确保 settings 切换 RemoteProvider 时
 一处替换全局生效。
"""
from __future__ import annotations
from services.code_intel.protocols import BaseCodeProvider
_REGISTRY: dict[str, BaseCodeProvider] = {}
_FROZEN: bool = False
def register_provider(key: str, provider: BaseCodeProvider) -> None:
 """注册 Provider 单例。仅 AppConfig.ready 期可调，之后 frozen。"""
 global _FROZEN
 if _FROZEN:
 raise RuntimeError(
 "code_intel registry is frozen; "
 "web request lifecycle cannot register new providers (per, T-)"
 )
 if not isinstance(provider, BaseCodeProvider):
 raise TypeError(
 f"provider must implement BaseCodeProvider Protocol, got {type(provider).__name__}"
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
 "register_provider",
 "freeze",
 "is_frozen",
 "get_provider",
]

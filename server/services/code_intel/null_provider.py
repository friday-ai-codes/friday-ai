"""NullProvider —— 代码智能不可用时的降级实现 (per Phase / ).
主体严格控制在 30 行以内（Pitfall 5）：只实现 BaseCodeProvider，
``isinstance(NullProvider, SymbolCapableProvider)`` 必须为 ``False``。
为了让 isinstance 守卫正确失败，类上不显式定义 ``lookup_symbols`` / ``expand_graph``；
上游若误绕过 capability 检查直接 ``await provider.lookup_symbols(...)``，会通过
``__getattr__`` 拿到一个抛 ``NotImplementedError`` 的协程，错误信息带上 capability
名让 debug 容易（per ）。
NullProvider 不读任何 Django settings —— 开关语义集中在 AppConfig.ready
的 CODE_INTELLIGENCE_PROVIDER 注入，不分散到 provider 内部。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
async def _capability_missing(capability: str) -> Any:
 raise NotImplementedError(f"NullProvider does not support {capability}")
@dataclass(frozen=True, slots=True)
class NullProvider:
 """空实现 Provider：仅满足 BaseCodeProvider，无任何 capability。"""
 capabilities: frozenset[str] = field(default_factory=frozenset)
 async def health_check(self) -> bool:
 return True
 def __getattr__(self, name: str) -> Any:
 if name in {"lookup_symbols", "expand_graph"}:
 return lambda *_a, **_kw: _capability_missing(name)
 raise AttributeError(name)
__all__ = ["NullProvider"]

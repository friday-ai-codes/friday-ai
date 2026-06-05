"""代码智能 Provider 抽象包 (implementation contract / contract..contract).

对外暴露三层 Protocol 与 ``get_provider`` 单例入口；``register_provider`` 仅供
``CodeIntelConfig.ready()`` 使用，web 请求生命周期内调用会因 frozen 标志
raise RuntimeError (per contract)。
"""

from __future__ import annotations

from services.code_intel.protocols import (
    BaseCodeProvider,
    GraphCapableProvider,
    SymbolCapableProvider,
)
from services.code_intel.registry import (
    PROVIDER_REGISTRY,
    get_provider,
    register_provider,
)

__all__ = [
    "BaseCodeProvider",
    "GraphCapableProvider",
    "PROVIDER_REGISTRY",
    "SymbolCapableProvider",
    "get_provider",
    "register_provider",
]

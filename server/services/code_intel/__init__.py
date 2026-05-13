"""代码智能 Provider 抽象包 (Phase / ..)。
对外只暴露三层 Protocol 与 ``get_provider`` 单例入口；
``register_provider`` 仅供 ``CodeIntelConfig.ready`` 使用，
web 请求生命周期内调用会因 frozen 标志 raise RuntimeError (per )。
"""
from __future__ import annotations
from services.code_intel.protocols import (
 BaseCodeProvider,
 GraphCapableProvider,
 SymbolCapableProvider,
)
__all__ = [
 "BaseCodeProvider",
 "GraphCapableProvider",
 "SymbolCapableProvider",
]

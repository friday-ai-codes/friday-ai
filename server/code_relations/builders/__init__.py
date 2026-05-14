"""Phase EdgeBuilder 包：6 类 ChunkEdge 构建器（per ）。
BUILDERS 注册表是 Plan 末尾由 orchestrator 统一填入的实例列表，
本 plan 仅提供空骨架与 BaseEdgeBuilder re-export，避免 Plan..06
并行落地各自 builder 时同时改 __init__.py 引发 wave 内文件冲突。
"""
from __future__ import annotations
from .base import BaseEdgeBuilder
__all__ = ["BUILDERS", "BaseEdgeBuilder"]
BUILDERS: list[type[BaseEdgeBuilder]] =
"""6 类 EdgeBuilder 类列表（Plan 末尾注册，per orchestrator 用此 list 并发跑）。"""

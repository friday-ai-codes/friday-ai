"""implementation EdgeBuilder 包：6 类 ChunkEdge 构建器（per contract）。

`BUILDERS` 注册表由 plan 07 末尾填入（plan 01..06 各自落地 builder 类，plan 07
在此统一注册），含全部 6 个 builder 类，orchestrator 用此 list 并发跑
（per contract：`asyncio.gather(*[cls().build(...) for cls in BUILDERS], ...)`）。
新增 builder 时只需在此 list 追加即可。
"""

from __future__ import annotations

from .base import BaseEdgeBuilder
from .call_edge import CallEdgeBuilder
from .co_changed_edge import CoChangedEdgeBuilder
from .import_edge import ImportEdgeBuilder
from .same_file_edge import SameFileEdgeBuilder
from .semantic_edge import SemanticEdgeBuilder
from .test_of_edge import TestOfEdgeBuilder

__all__ = [
    "BUILDERS",
    "BaseEdgeBuilder",
    "CallEdgeBuilder",
    "CoChangedEdgeBuilder",
    "ImportEdgeBuilder",
    "SameFileEdgeBuilder",
    "SemanticEdgeBuilder",
    "TestOfEdgeBuilder",
]

BUILDERS: list[type[BaseEdgeBuilder]] = [
    CallEdgeBuilder,
    ImportEdgeBuilder,
    SameFileEdgeBuilder,
    TestOfEdgeBuilder,
    CoChangedEdgeBuilder,
    SemanticEdgeBuilder,
]
"""6 类 EdgeBuilder 注册表（per contract orchestrator 用此 list 并发跑）。

顺序遵循 context contract..contract 章节顺序（CALL → IMPORT → SAME_FILE → TEST_OF →
CO_CHANGED → SEMANTIC），与 ROADMAP 锁定的 6 类边语义对齐。
"""

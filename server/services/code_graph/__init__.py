"""内存符号图服务包（Phase 121 交付的 v0.22.0 图分析地基）。

本文件目前只是**占位**：让 ``services.code_graph.model`` 可被 import。

对外导出面（curated barrel，只 re-export ``GraphService`` 与 ``model.py`` 的契约
类型，**不导出 ``loader`` / ``cache``**——上层工具直连 loader 是架构红线）由
**Plan 121-09** 补全，届时本文件会长出 ``__all__``。在那之前请显式
``from services.code_graph.model import ...``。
"""

from __future__ import annotations

"""切片数据结构 —— ``CodeChunk`` 与 ``SymbolSpan``。

抽为独立模块（无重依赖），让 ``code_parser`` / ``symbol_chunker`` / ``indexer``
三方共享同一份 ``CodeChunk`` 定义，避免 ``code_parser`` ↔ ``symbol_chunker``
循环导入。``services.code_parser`` 仍重新导出 ``CodeChunk``，保持既有
``from services.code_parser import CodeChunk`` 调用方零改动。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CodeChunk", "SymbolSpan"]


@dataclass
class CodeChunk:
    """Represents a chunk of code for indexing."""

    content: str
    file_path: str
    file_hash: str
    language: str
    start_line: int
    end_line: int
    node_type: str  # function, class, rule, etc.
    context_header: str  # For embedding enrichment
    # 上下文增强字段（用于提升 embedding 质量，不存入 Qdrant payload）
    imports: str = ""  # 文件级 import 语句
    module_docstring: str = ""  # 模块级 docstring/注释
    sibling_signatures: str = ""  # 同文件其他函数/类签名
    parent_symbol: str | None = None  # AST-aware 模式下标记 chunk 所属的父符号名
    # 第二阶段：chunk 来自 codegraph Symbol 时，回填该 Symbol 的稳定 key
    # （file_path, name, start_line），供 indexer 建立 chunk_id ↔ Symbol 双向绑定，
    # 取代 SymbolChunkResolver 的行号 bisect 软对齐。None = 非符号驱动来源。
    symbol_key: tuple[str, str, int] | None = None


@dataclass
class SymbolSpan:
    """语言无关的符号边界（1-based 闭区间），``symbol_chunker`` 的输入单元。

    两类来源映射到同一结构，让切分核心被两阶段复用：

    - **第一阶段**：``code_parser`` 用 tree-sitter ``walk_tree`` 抽出的顶层符号。
    - **第二阶段**：``indexer`` 把 codegraph ``ExtractionBundle.symbols``（``SymbolData``）
      映射成 ``SymbolSpan``，使 chunk 与 codegraph ``Symbol`` 同源。

    Attributes:
        name: 符号名（``None`` 表示匿名 / 模块级）。
        kind: 规范化种类——``"function" | "class" | "method" | "variable" | "other"``。
            合并策略据此判定（class/method 不参与小符号激进合并）。
        start_line: 起始行（1-based，闭区间）。
        end_line: 结束行（1-based，闭区间）。
        node_type: 原始节点类型（写入 ``CodeChunk.node_type``）；空则回退 ``kind``。
        symbol_key: 第二阶段回填的 codegraph Symbol 稳定 key（file_path, name, start_line），
            供 chunk ↔ Symbol 绑定；第一阶段为 ``None``。
    """

    name: str | None
    kind: str
    start_line: int
    end_line: int
    node_type: str = ""
    symbol_key: tuple[str, str, int] | None = None

"""解析层语言无关契约 —— ImportResolver Protocol + ResolveResult dataclass。

per work item（interface-first，零依赖）：先把跨语言共享的解析契约定下来，
让 wave/3（symbol_resolver / python_import）以及 289（前端）/290（Go）的新语言
实现直接对接已定义接口，避免"寻宝式"探索。

- ``ImportResolver`` 用 ``typing.Protocol``（结构化子类型）而非 ABC：289/290 各挂一个
  语言专属实现时无需显式继承，鸭子类型即可被 ``SymbolResolver`` 注入。
- ``ResolveResult`` 是 4 路径解析算法的统一产出物，承载回填 287 留 NULL 的
  ``callee_symbol`` / ``callee_file`` / ``is_cross_file`` 三字段所需信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ImportResolver(Protocol):
    """语言专属 import 解析器接口 —— 289（前端）/ 290（Go）各实现一个。"""

    def resolve_module(
        self, target_module: str, is_relative: bool, source_file: str
    ) -> str | None:
        """把 import 模块名解析为仓内 ``file_path``。

        Args:
            target_module: import 的模块名（如 ``"a.b"`` / ``".x"``）。
            is_relative: 是否相对导入（``from .x import y``）。
            source_file: 发起 import 的源文件仓相对路径（相对导入按其目录回溯）。

        Returns:
            命中则返回仓内 ``file_path``；第三方库 / 解析不到返回 ``None``
            （绝不误连，留给上层走"留空"分支）。
        """
        ...


@dataclass
class ResolveResult:
    """单条调用解析产出；前三字段保持旧回填契约兼容。"""

    callee_symbol_id: str | None
    callee_file: str | None
    is_cross_file: bool
    status: str = "unresolved"
    language: str = "unknown"
    call_shape: str = "direct"
    strategy: str = "none"
    candidates: list[dict[str, str]] = field(default_factory=list)
    evidence: list[dict[str, str]] = field(default_factory=list)


__all__ = ["ImportResolver", "ResolveResult"]

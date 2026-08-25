"""work item —— 仓库级内存符号索引 SymbolIndex。

给定 ``repository_id`` 一次性把全仓 ``Symbol`` 灌入两个内存 dict：

- 精确索引 ``_exact``：``(file_path, name) -> list[IndexedSymbol]``，命中 O(1) +
  O(同名数)。值为 **list** 而非单值——同文件同名（top-level ``def foo`` 与类内
  ``method foo``，同 name/file、不同 start_line，``Symbol.unique_together`` 允许）必须
  全部保留，不互相覆盖（RESEARCH Pitfall 4）。
- 模糊索引 ``_fuzzy``：``name -> list[IndexedSymbol]``，O(1) 取桶 + O(k) 遍历，跨文件
  同名候选供上层裁定。
- 文件集合 ``_files``：仓内全部 ``file_path``，供 ``ImportResolver`` 判定模块是否落仓内
  （``has_file``，checkpoint 用）。

逐边 ORM 查 Symbol 在 19629 Symbol / 数万 CallEdge 规模下是 N+1 灾难；本索引一次性
``.only(...).iterator(chunk_size=)`` 流式灌入，避免一次性 materialize 全表。
``[VERIFIED: graph_writer.py 已用同款 (file,name)->id 的 symbol_name_index 内存映射模式]``
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexedSymbol:
    """索引内的轻量 Symbol 视图 —— 回填只需 id/file_path，symbol_type 供同名优先级裁定。"""

    id: str
    name: str
    file_path: str
    symbol_type: str


class SymbolIndex:
    """仓库级内存符号索引：精确 (file,name) O(1) + 模糊 name O(k)。"""

    def __init__(self) -> None:
        self._exact: dict[tuple[str, str], list[IndexedSymbol]] = {}
        self._fuzzy: dict[str, list[IndexedSymbol]] = {}
        self._by_file: dict[str, list[IndexedSymbol]] = {}
        self._files: set[str] = set()

    @classmethod
    def build(cls, repository_id: str, branch_name: str = "") -> SymbolIndex:
        """一次性读取该仓全部 Symbol，构建精确/模糊双索引 + 文件集合。

        用 ``.only(...)`` 仅取索引所需 4 字段 + ``.iterator(chunk_size=2000)`` 流式灌入，
        避免大仓一次性把全表 materialize 进内存。
        """
        from codegraph.models import Symbol

        idx = cls()
        branch_filter = ["", branch_name] if branch_name else [""]
        qs = Symbol.objects.filter(
            repository_id=repository_id, branch_name__in=branch_filter
        ).only(
            "id", "name", "file_path", "symbol_type"
        )
        for symbol in qs.iterator(chunk_size=2000):
            indexed = IndexedSymbol(
                id=str(symbol.id),
                name=symbol.name,
                file_path=symbol.file_path,
                symbol_type=symbol.symbol_type,
            )
            idx._exact.setdefault((indexed.file_path, indexed.name), []).append(indexed)
            idx._fuzzy.setdefault(indexed.name, []).append(indexed)
            idx._by_file.setdefault(indexed.file_path, []).append(indexed)
            idx._files.add(indexed.file_path)
        # 纯 re-export/barrel 文件可能没有可索引 Symbol，但仍是合法模块路径。
        # 把 ImportEdge.source_file 纳入文件集合，允许 FrontendImportResolver 进入下一跳。
        from codegraph.models import ImportEdge

        idx._files.update(
            ImportEdge.objects.filter(
                repository_id=repository_id,
                branch_name__in=branch_filter,
            ).values_list("source_file", flat=True)
        )
        return idx

    def exact(self, file_path: str, name: str) -> list[IndexedSymbol]:
        """精确查 (file_path, name)，未命中返回空 list（不抛 KeyError）。"""
        return self._exact.get((file_path, name), [])

    def fuzzy(self, name: str) -> list[IndexedSymbol]:
        """模糊查 name（跨文件全部同名候选），未命中返回空 list。"""
        return self._fuzzy.get(name, [])

    def has_file(self, file_path: str) -> bool:
        """判定 ``file_path`` 是否属于本仓（供 ImportResolver 精确等值口径使用）。"""
        return file_path in self._files

    def symbols_in_file(self, file_path: str) -> list[IndexedSymbol]:
        """返回某文件内的全部 Symbol（供组件引用解析按文件取组件 Symbol）。"""
        return self._by_file.get(file_path, [])


__all__ = ["IndexedSymbol", "SymbolIndex"]

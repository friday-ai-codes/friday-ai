""" —— PythonImportResolver：Python import 模块名 → 仓内文件路径。
**移植**（不从零写）``server/code_relations/builders/import_edge.py:_resolve_target_file``
经实战修复的算法：
-：相对导入按前导点数决定向上回溯层级（PEP 328：1 点=同包、2 点=父包，
 ``up_levels = n_leading_dots - 1``），**不用** ``lstrip("./")``（字符集剥离会把 ``..``
 一并剥掉，破坏父级相对导入语义——已踩坑）。
- 点→斜杠转换 + 路径分隔符归一化（折叠重复 ``/`` 与前导 ``/``）。
相对 ``import_edge.py`` 的三处必改：
① **目标集合**：从 ``ChunkRegistry`` ORM ``endswith`` 查询改为查内存 ``SymbolIndex._files``
 集合（精确等值， Q1 已坐实 ``Symbol.file_path`` = 仓相对路径基准）；
② **同步化**：去 ``async`` / 去 ``sync_to_async`` / 去 ORM / 去 ``Q`` —— 纯同步字符串运算
 + 一次内存集合查找，无文件系统访问（无 path traversal 面）；
③ ``a/b/__init__.py`` 包候选（``import_edge.py`` 的 ``CANDIDATE_EXTENSIONS`` 不含）——见
 Task 2 落地。
实现 ``base.ImportResolver`` Protocol（结构化子类型，无需显式继承）。
"""
from __future__ import annotations
from code_relations.constants import CANDIDATE_EXTENSIONS
from codegraph.resolver.symbol_index import SymbolIndex
__all__ = ["PythonImportResolver"]
class PythonImportResolver:
 """Python import 模块名 → 仓内 ``file_path`` 的语言专属解析器。"""
 def __init__(self, symbol_index: SymbolIndex) -> None:
 self._idx = symbol_index
 def resolve_module(
 self, target_module: str, is_relative: bool, source_file: str
 ) -> str | None:
 """把 import 模块名解析为仓内 ``file_path``，第三方/解析不到返回 ``None``。
 Args:
 target_module: import 的模块名（绝对 ``"a.b"`` / 相对 ``".x"`` / ``"..util"``）。
 is_relative: 是否相对导入（``from .x import y``）。
 source_file: 发起 import 的源文件仓相对路径（相对导入按其目录回溯）。
 Returns:
 命中则返回仓内 ``file_path``；第三方库 / 解析不到返回 ``None``（绝不误连）。
 """
 # ① 先剥离显式文件扩展名（移植 import_edge.py：JS/TS 相对导入常带扩展名，
 # 若不剥离后续 ``replace(".","/")`` 会把扩展名的点也替换成 ``/``）。
 explicit_ext = ""
 mod = target_module
 for ext in CANDIDATE_EXTENSIONS:
 if mod.endswith(ext):
 explicit_ext = ext
 mod = mod[: -len(ext)]
 break
 # ② 相对导入：按前导点数计回溯层级（PEP 328 /，禁用 lstrip("./")）。
 if is_relative and mod.startswith("."):
 n_leading_dots = 0
 for ch in mod:
 if ch == ".":
 n_leading_dots += 1
 else:
 break
 suffix = mod[n_leading_dots:]
 suffix_path = suffix if explicit_ext else suffix.replace(".", "/")
 src_dir = source_file.rsplit("/", 1)[0] if "/" in source_file else ""
 up_levels = max(0, n_leading_dots - 1) # 1 点=同包（up=0），2 点=父包（up=1）
 parts = src_dir.split("/") if src_dir else
 if up_levels > 0:
 parts = if up_levels >= len(parts) else parts[:-up_levels]
 base_dir = "/".join(p for p in parts if p)
 if base_dir and suffix_path:
 base = f"{base_dir}/{suffix_path}"
 elif base_dir:
 base = base_dir
 else:
 base = suffix_path
 # ③ 绝对导入：点 → 斜杠。
 else:
 base = mod if explicit_ext else mod.replace(".", "/")
 # ④ 归一化：折叠重复 ``/`` 与前导 ``/``，保证 has_file 精确命中。
 base = "/".join(seg for seg in base.split("/") if seg)
 # 候选：``a/b.py`` 查内存 _files 精确等值（Task 2 补 __init__.py 包候选 + 锚定兜底）。
 candidate = f"{base}.py"
 if self._idx.has_file(candidate):
 return candidate
 return None

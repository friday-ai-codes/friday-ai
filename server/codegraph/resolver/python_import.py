""" —— PythonImportResolver：Python import 模块名 → 仓内文件路径。
**移植**（不从零写）``server/code_relations/builders/import_edge.py:_resolve_target_file``
经实战修复的算法：
-：相对导入按前导点数决定向上回溯层级（PEP 328：1 点=同包、2 点=父包，
 ``up_levels = n_leading_dots - 1``），**不用** ``lstrip("./")``（字符集剥离会把 ``..``
 一并剥掉，破坏父级相对导入语义——已踩坑）。
- 点→斜杠转换 + 路径分隔符归一化（折叠重复 ``/`` 与前导 ``/``）。
相对旧 chunk 域解析逻辑的三处必改：
① **目标集合**：从数据库后缀查询改为查内存 ``SymbolIndex._files`` 集合
 （精确等值， 路径基准结论已坐实 ``Symbol.file_path`` = 仓相对路径基准）；
② **同步化**：去异步桥接、数据库查询和查询表达式 —— 纯同步字符串运算
 + 一次内存集合查找，无文件系统访问（无 path traversal 面）；
③ ``a/b/__init__.py`` 包候选（``import_edge.py`` 的 ``CANDIDATE_EXTENSIONS`` 不含）：
 候选固定顺序「先模块文件 ``a/b.py`` 再包 ``a/b/__init__.py``」（Pitfall 5）。
实现 ``base.ImportResolver`` Protocol（结构化子类型，无需显式继承）。
## 已知可接受漏连（CONTEXT 锁定「少数动态/别名可接受漏连」，非缺陷）
本 resolver 只解析 import 模块名 → 文件，下面两类调用形态由上层 ``SymbolResolver``
路径②按 ``imported_names`` 匹配时天然落空，**留 NULL 即可，不报错、不乱连**：
- **(a) ``import a.b`` 后 ``a.b.foo``（Pitfall 3）**：导入的是模块对象，调用经
 ``a.b.`` 限定符，``callee_name="foo"`` 不在 ``imported_names=["a.b"]`` 中，路径②不命中。
 本 phase 优先打通 ``from a.b import foo``（``imported_names`` 含 ``foo`` 可命中）。
- **(b) ``from a.b import c`` 中 ``c`` 是子模块 ``a/b/c.py``（Pitfall 6）**：``c`` 是
 子模块而非 ``a/b.py`` / ``a/b/__init__.py`` 内的符号；若调用 ``c.func`` 则
 ``callee_name="func"`` 同样不在 ``imported_names``。子模块二次解析留待未来，本 phase 漏连。
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
 # ⑤ 候选枚举：显式扩展名按该扩展精确匹配；否则固定顺序「先模块文件 a/b.py
 # 再包 a/b/__init__.py」（Pitfall 5：模块文件优先于包）。
 if explicit_ext:
 candidates: tuple[str, ...] = (f"{base}{explicit_ext}",)
 else:
 candidates = (f"{base}.py", f"{base}/__init__.py")
 # ⑥ 命中判定双保险：先精确等值，miss 再 /+endswith 锚定兜底；两候选全 miss
 # → 返回 None（真第三方，不误连）。
 for candidate in candidates:
 hit = self._lookup(candidate)
 if hit is not None:
 return hit
 return None
 def _lookup(self, candidate: str) -> str | None:
 """单个候选的命中判定：精确等值优先，miss 后 ``/`` + endswith 锚定兜底。
 路径基准结论已坐实 ``Symbol.file_path`` = 仓相对路径，正常 ``has_file`` 精确等值即
 命中；锚定兜底是防御性双保险——仅当仓内 ``file_path`` 含统一前缀目录（与精确口径
 不一致）时生效。锚定用 ``f"/{candidate}"`` 而非裸 ``candidate`` endswith，防
 ``auth.py`` 误匹配 ``oauth.py``。
 """
 if self._idx.has_file(candidate):
 return candidate
 anchored = f"/{candidate}"
 for file_path in self._idx._files:
 if file_path.endswith(anchored):
 return file_path
 return None

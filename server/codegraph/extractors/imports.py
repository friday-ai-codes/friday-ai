"""Import 抽取器 —— 从 AST 中提取 import 依赖关系。
per: 系统能从代码文件中提取 import 关系，分析模块间依赖。
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any
import structlog
if TYPE_CHECKING:
 from codegraph.extractors.base import FileContext, ImportData
logger = structlog.get_logger(__name__)
def extract_imports(tree: Any, ctx: "FileContext") -> "list[ImportData]":
 """从 tree-sitter AST 提取所有 import 语句。
 Args:
 tree: tree-sitter Tree 对象
 ctx: FileContext (file_path, language, repository_id, module_path)
 Returns:
 list[ImportData]: import 关系列表
 """
 from codegraph.extractors.base import ImportData
 from codegraph.extractors.walker import walk_tree, IMPORT_TYPES
 import_types = IMPORT_TYPES.get(ctx.language, )
 if not import_types:
 return
 imports: list[ImportData] =
 for wn in walk_tree(tree, ctx.language):
 node = wn.node
 if node.type not in import_types:
 continue
 try:
 results = _extract_one_import(wn, ctx)
 if results:
 imports.extend(results)
 except Exception as e:
 logger.warning(
 "import_extraction_failed",
 file_path=ctx.file_path,
 node_type=node.type,
 error=str(e),
 )
 return imports
def _extract_one_import(
 wn: Any, ctx: "FileContext"
) -> "list[ImportData] | None":
 """从单个 WalkerNode 提取 ImportData 列表。
 处理 import_statement / import_from_statement 两种节点类型。
 内部函数供 GraphExtractor（orchestrator.py）复用。
 Args:
 wn: WalkerNode
 ctx: FileContext
 Returns:
 list[ImportData] | None: 成功返回 ImportData 列表，失败返回 None
 """
 from codegraph.extractors.base import ImportData
 node = wn.node
 if node.type == "import_statement":
 if ctx.language in ("typescript", "tsx"):
 return _parse_import_statement_ts(node, ctx)
 return _parse_import_statement(node, ctx)
 elif node.type == "import_from_statement":
 return _parse_import_from_statement(node, ctx)
 elif node.type == "import_declaration":
 # Go 等语言的 import declaration
 return _parse_import_declaration(node, ctx)
 elif node.type == "export_statement" and ctx.language in ("typescript", "tsx"):
 #：TS / TSX 重导出 `export { x } from '...'`
 return _parse_export_statement_ts(node, ctx)
 return None
def _parse_import_statement(node: Any, ctx: "FileContext") -> "list[ImportData]":
 """解析 import X, Y as Z 语句。
 每个导入的模块产生一个 ImportData。
 """
 from codegraph.extractors.base import ImportData
 results: list[ImportData] =
 for child in node.named_children:
 if child.type == "dotted_name":
 module_name = child.text
 if isinstance(module_name, bytes):
 module_name = module_name.decode("utf-8")
 results.append(
 ImportData(
 source_file=ctx.file_path,
 target_module=module_name,
 imported_names=[module_name],
 is_relative=False,
 )
 )
 elif child.type == "aliased_import":
 name, alias = _parse_aliased_import(child)
 results.append(
 ImportData(
 source_file=ctx.file_path,
 target_module=name,
 imported_names=[f"{name} as {alias}" if alias else name],
 is_relative=False,
 )
 )
 if not results:
 # 无法解析出任何模块名 —— 大型仓库里这种 "import 语句没识别出模块" 的情况
 # 非常常见（typescript path alias、未知 DSL 等），降级到 debug 避免刷屏。
 logger.debug(
 "import_statement_no_modules",
 file_path=ctx.file_path,
 node_text=_safe_text(node),
 )
 return results
def _parse_import_declaration(
 node: Any, ctx: "FileContext"
) -> "list[ImportData]":
 """解析 Go 等语言的 import_declaration 节点。
 支持 import_spec_list（多 import 括号块）和单个 import_spec。
 """
 from codegraph.extractors.base import ImportData
 results: list[ImportData] =
 def _extract_string(node: Any) -> str | None:
 """从 interpreted_string_literal 提取模块名。"""
 text = node.text
 if isinstance(text, bytes):
 text = text.decode("utf-8")
 text = text.strip
 if text.startswith('"') and text.endswith('"'):
 return text[1:-1]
 return text
 def _parse_spec(spec: Any) -> None:
 """解析单个 import_spec。"""
 # import_spec 直接包含 interpreted_string_literal（如 "fmt"）
 if spec.type == "interpreted_string_literal":
 module = _extract_string(spec)
 if module:
 results.append(
 ImportData(
 source_file=ctx.file_path,
 target_module=module,
 imported_names=[module],
 is_relative=False,
 )
 )
 # import_spec 包含 alias + path（如 utils "fmt"）
 elif spec.type == "import_spec":
 literal = None
 alias = None
 for child in spec.children:
 if child.type == "interpreted_string_literal":
 literal = _extract_string(child)
 elif child.type == "identifier" or child.type == "package_identifier":
 alias = child.text
 if isinstance(alias, bytes):
 alias = alias.decode("utf-8")
 if literal:
 name = f"{alias} as {literal}" if alias else literal
 results.append(
 ImportData(
 source_file=ctx.file_path,
 target_module=literal,
 imported_names=[name],
 is_relative=False,
 )
 )
 # 遍历所有子节点找 import_spec 或 interpreted_string_literal
 def _walk(n: Any) -> None:
 if n.type in ("import_spec", "interpreted_string_literal"):
 _parse_spec(n)
 else:
 for child in n.children:
 _walk(child)
 _walk(node)
 return results
def _parse_import_from_statement(
 node: Any, ctx: "FileContext",
) -> "list[ImportData]":
 """解析 from X import a, b as c 语句。
 同一 from 语句的多个符号合并为一条 ImportData。
 """
 from codegraph.extractors.base import ImportData
 # 获取模块名
 module_node = node.child_by_field_name("module_name")
 if module_node is None:
 logger.warning(
 "import_from_no_module_name",
 file_path=ctx.file_path,
 )
 return
 module_name = module_node.text
 if isinstance(module_name, bytes):
 module_name = module_name.decode("utf-8")
 # 检查相对导入
 is_relative = module_name.startswith(".")
 # 收集导入的符号名
 imported_names: list[str] =
 for child in node.named_children:
 if child.type == "dotted_name":
 name = child.text
 if isinstance(name, bytes):
 name = name.decode("utf-8")
 imported_names.append(name)
 elif child.type == "aliased_import":
 name, alias = _parse_aliased_import(child)
 imported_names.append(f"{name} as {alias}" if alias else name)
 return [
 ImportData(
 source_file=ctx.file_path,
 target_module=module_name,
 imported_names=imported_names,
 is_relative=is_relative,
 )
 ]
def _parse_aliased_import(node: Any) -> "tuple[str, str | None]":
 """解析 aliased_import 节点，返回 (原名, 别名)。
 tree-sitter Python grammar: aliased_import → name: identifier, alias: identifier?
 """
 name_node = node.child_by_field_name("name")
 alias_node = node.child_by_field_name("alias")
 name = name_node.text if name_node else ""
 if isinstance(name, bytes):
 name = name.decode("utf-8")
 alias = None
 if alias_node:
 alias = alias_node.text
 if isinstance(alias, bytes):
 alias = alias.decode("utf-8")
 return name, alias
def _strip_quotes(text: str) -> str:
 """剥除字符串字面量两侧的单引号 / 双引号。"""
 text = text.strip
 if len(text) >= 2 and text[0] in ("'", '"') and text[-1] == text[0]:
 return text[1:-1]
 return text
def _parse_import_statement_ts(
 node: Any, ctx: "FileContext"
) -> "list[ImportData]":
 """解析 TS / TSX 的 import_statement 节点（per / / ）。
 支持四种 import 形态：
 - 命名导入 `import { a, b } from 'mod'` —— named_imports → import_specifier.name
 - 命名空间导入 `import * as ns from './utils'` —— namespace_import → identifier
 - 默认导入 `import Default from 'mod'` —— import_clause → identifier
 - type-only 导入 `import type { T } from 'mod'` —— 与运行时同等记录
 始终返回长度为 1 的 list[ImportData]（同一 import 语句聚合为一条）。
 """
 from codegraph.extractors.base import ImportData
 source_node = node.child_by_field_name("source")
 if source_node is None:
 return
 source_text = source_node.text
 if isinstance(source_text, bytes):
 source_text = source_text.decode("utf-8")
 target_module = _strip_quotes(source_text)
 imported_names: list[str] =
 for child in node.children:
 if child.type != "import_clause":
 continue
 for clause_child in child.children:
 if clause_child.type == "named_imports":
 for spec in clause_child.children:
 if spec.type != "import_specifier":
 continue
 name_node = spec.child_by_field_name("name")
 if name_node is None:
 continue
 nm = name_node.text
 if isinstance(nm, bytes):
 nm = nm.decode("utf-8")
 imported_names.append(nm)
 elif clause_child.type == "namespace_import":
 # `* as ns` —— 取末尾 identifier 作 alias
 alias = None
 for sub in clause_child.children:
 if sub.type == "identifier":
 alias = sub.text
 if isinstance(alias, bytes):
 alias = alias.decode("utf-8")
 if alias:
 imported_names.append(f"* as {alias}")
 elif clause_child.type == "identifier":
 # 默认导入 `import Default from 'mod'`
 default_name = clause_child.text
 if isinstance(default_name, bytes):
 default_name = default_name.decode("utf-8")
 imported_names.append(default_name)
 is_relative = target_module.startswith(".")
 return [
 ImportData(
 source_file=ctx.file_path,
 target_module=target_module,
 imported_names=imported_names,
 is_relative=is_relative,
 )
 ]
def _parse_export_statement_ts(
 node: Any, ctx: "FileContext"
) -> "list[ImportData]":
 """解析 TS / TSX 的 export_statement 重导出形态（per ）。
 仅处理含 `source` 字段的重导出（如 `export { foo } from './types'`）；
 本地 export（`export function helper {}` / `export class Bar {}`）
 无 source 字段 → 返空，避免误抽（Pitfall 7 守卫）。
 """
 from codegraph.extractors.base import ImportData
 source_node = node.child_by_field_name("source")
 if source_node is None:
 return
 source_text = source_node.text
 if isinstance(source_text, bytes):
 source_text = source_text.decode("utf-8")
 target_module = _strip_quotes(source_text)
 imported_names: list[str] =
 for child in node.children:
 if child.type != "export_clause":
 continue
 for spec in child.children:
 if spec.type != "export_specifier":
 continue
 name_node = spec.child_by_field_name("name")
 if name_node is None:
 continue
 nm = name_node.text
 if isinstance(nm, bytes):
 nm = nm.decode("utf-8")
 imported_names.append(nm)
 is_relative = target_module.startswith(".")
 return [
 ImportData(
 source_file=ctx.file_path,
 target_module=target_module,
 imported_names=imported_names,
 is_relative=is_relative,
 )
 ]
def _safe_text(node: Any) -> str:
 """安全获取节点文本。"""
 try:
 text = node.text
 if isinstance(text, bytes):
 text = text.decode("utf-8")
 return text[:100] # 截断防过长
 except Exception:
 return "<unable to decode>"
__all__ = [
 "extract_imports",
 "_extract_one_import",
 "_parse_import_statement_ts",
 "_parse_export_statement_ts",
]

"""Symbol 抽取器 —— 从 AST 中提取函数/类/方法定义。
per: Symbol 包含 name / symbol_type / file_path / start_line / end_line / signature / is_async
per: 系统能从代码文件中提取函数/类/接口等符号定义
"""
from typing import Any
import structlog
logger = structlog.get_logger(__name__)
def extract_symbols(tree: Any, source: str, ctx: "FileContext") -> "list[SymbolData]":
 """从 tree-sitter AST 提取所有函数/类/方法定义。
 Args:
 tree: tree-sitter Tree 对象
 source: 源文件完整文本（用于签名提取）
 ctx: FileContext (file_path, language, repository_id, module_path)
 Returns:
 list[SymbolData]: 符号定义列表，按代码出现顺序排列
 """
 from server.codegraph.extractors.base import SymbolData
 from server.codegraph.extractors.walker import walk_tree, SYMBOL_TYPES
 symbol_types = SYMBOL_TYPES.get(ctx.language, )
 if not symbol_types:
 return
 symbols: list[SymbolData] =
 for wn in walk_tree(tree, ctx.language):
 node = wn.node
 if node.type not in symbol_types:
 continue
 try:
 sym = _extract_one_symbol(wn, source, ctx)
 if sym is not None:
 symbols.append(sym)
 except Exception as e:
 logger.warning(
 "symbol_extraction_failed",
 file_path=ctx.file_path,
 node_type=node.type,
 error=str(e),
 )
 return symbols
def _extract_one_symbol(
 wn: Any, source: str, ctx: "FileContext"
) -> "SymbolData | None":
 """从单个 WalkerNode 提取 SymbolData。
 处理 function_definition / class_definition / decorated_definition 三种节点类型。
 内部函数供 GraphExtractor（orchestrator.py）复用，避免重复实现。
 Args:
 wn: WalkerNode（携带 node + ancestor_function + ancestor_class）
 source: 源文件完整文本
 ctx: FileContext
 Returns:
 SymbolData | None: 成功提取返回 SymbolData，跳过则返回 None
 """
 from server.codegraph.extractors.base import SymbolData
 node = wn.node
 # --- 处理 decorated_definition：取出内部实际定义 ---
 actual_node = node
 is_decorated = False
 if node.type == "decorated_definition":
 is_decorated = True
 for child in node.children:
 if child.type in ("function_definition", "class_definition"):
 actual_node = child
 break
 # --- 提取名称 ---
 name_node = actual_node.child_by_field_name("name")
 if name_node is None:
 return None
 name = name_node.text
 if isinstance(name, bytes):
 name = name.decode("utf-8")
 # --- 确定 symbol_type ---
 if actual_node.type == "class_definition":
 symbol_type = "CLASS"
 elif wn.ancestor_class is not None:
 symbol_type = "METHOD"
 else:
 symbol_type = "FUNCTION"
 # --- 行号（tree-sitter 行号从 0 开始，+1 转为 1-based）---
 start_line = node.start_point[0] + 1
 end_line = node.end_point[0] + 1
 # --- async 检测 ---
 is_async = False
 if actual_node.type == "function_definition":
 for child in actual_node.children:
 if child.type == "async":
 is_async = True
 break
 # --- 签名提取：取节点文本的第一行（定义行）---
 signature = _extract_signature(node, actual_node, is_decorated)
 # --- 跳过条件：体过短（空函数/空类）---
 body_text = actual_node.text
 if isinstance(body_text, bytes):
 body_text = body_text.decode("utf-8")
 # 去掉第一行（签名行）后看剩余体长度
 body_only = "\n".join(body_text.split("\n")[1:]).strip
 if len(body_only) < 10 and symbol_type != "CLASS":
 # 空函数/方法体（如 def foo: pass）→ 仍保留但标记
 # 不跳过，因为 GraphWriter 后续可能需要这些符号
 pass
 return SymbolData(
 name=name,
 symbol_type=symbol_type,
 file_path=ctx.file_path,
 start_line=start_line,
 end_line=end_line,
 signature=signature,
 is_async=is_async,
 )
def _extract_signature(node: Any, actual_node: Any, is_decorated: bool) -> str:
 """从节点文本中提取签名。
 对于普通函数/类：取定义行
 对于 decorated_definition：包含装饰器行 + 定义行
 """
 # 获取节点完整文本
 node_text = node.text
 if isinstance(node_text, bytes):
 node_text = node_text.decode("utf-8")
 lines = node_text.split("\n")
 if is_decorated:
 # 包含装饰器行 + 定义行
 # 找到包含 'def ' 或 'class ' 的定义行
 def_line_idx = -1
 for i, line in enumerate(lines):
 stripped = line.strip
 if stripped.startswith("def ") or stripped.startswith("class "):
 def_line_idx = i
 break
 if def_line_idx >= 0:
 # 取装饰器行（第 0 到 def_line_idx 行）
 return "\n".join(line.strip for line in lines[: def_line_idx + 1])
 else:
 return lines[0].strip if lines else ""
 else:
 # 取第一行作为签名
 first_line = lines[0].strip if lines else ""
 return first_line
__all__ = ["extract_symbols", "_extract_one_symbol"]

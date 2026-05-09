"""Call 抽取器 —— 从 AST 中提取函数调用关系。
per: 系统能从代码文件中提取函数调用关系。
per: 仅文件内解析，caller 通过 WalkerNode.ancestor_function 判定。
per: call_type 支持 DIRECT / METHOD / ATTRIBUTE。
"""
from typing import Any
import structlog
logger = structlog.get_logger(__name__)
def extract_calls(tree: Any, ctx: "FileContext") -> "list[CallData]":
 """从 tree-sitter AST 提取所有函数调用关系。
 仅提取文件内调用（有 ancestor_function 的调用），
 模块级调用（ancestor_function is None）被跳过。
 Args:
 tree: tree-sitter Tree 对象
 ctx: FileContext (file_path, language, repository_id, module_path)
 Returns:
 list[CallData]: 调用边列表
 """
 from codegraph.extractors.base import CallData
 from codegraph.extractors.walker import walk_tree, CALL_TYPES
 call_types = CALL_TYPES.get(ctx.language, )
 if not call_types:
 return
 calls: list[CallData] =
 for wn in walk_tree(tree, ctx.language):
 node = wn.node
 if node.type not in call_types:
 continue
 try:
 call = _extract_one_call(wn, ctx)
 if call is not None:
 calls.append(call)
 except Exception as e:
 logger.warning(
 "call_extraction_failed",
 file_path=ctx.file_path,
 error=str(e),
 )
 return calls
def _extract_one_call(wn: Any, ctx: "FileContext") -> "CallData | None":
 """从单个 WalkerNode 提取 CallData。
 处理 call 节点，判定 call_type（DIRECT / METHOD）。
 跳过模块级调用（无 ancestor_function）。
 内部函数供 GraphExtractor（orchestrator.py）复用。
 Args:
 wn: WalkerNode（携带 node + ancestor_function + ancestor_class）
 ctx: FileContext
 Returns:
 CallData | None: 成功返回 CallData，跳过返回 None
 """
 from codegraph.extractors.base import CallData
 node = wn.node
 # --- 跳过模块级调用 ---
 if wn.ancestor_function is None:
 return None
 # --- 获取被调用者（function 子字段）---
 function_node = node.child_by_field_name("function")
 if function_node is None:
 return None
 # --- 判定 callee_name 和 call_type ---
 callee_name: str | None = None
 call_type: str = "DIRECT"
 if function_node.type == "identifier":
 # 直接调用：foo
 callee_name = function_node.text
 if isinstance(callee_name, bytes):
 callee_name = callee_name.decode("utf-8")
 call_type = "DIRECT"
 elif function_node.type == "attribute":
 # 方法调用：obj.method
 attr_node = function_node.child_by_field_name("attribute")
 if attr_node is not None:
 callee_name = attr_node.text
 if isinstance(callee_name, bytes):
 callee_name = callee_name.decode("utf-8")
 call_type = "METHOD"
 else:
 # attribute 无 attribute 子字段（异常情况）
 return None
 else:
 # 其他调用形式（如 call 嵌套）→ 暂不处理
 return None
 if callee_name is None:
 return None
 # --- 行号 ---
 line_number = node.start_point[0] + 1
 # --- caller_key：三元组 (file_path, name, 0)
 # start_line 填 0 表示 unknown，GraphWriter 通过 (file_path, name) 匹配 caller Symbol
 # 因同一文件内同名函数不会重复定义，(file_path, name) 足以唯一定位
 caller_key = (ctx.file_path, wn.ancestor_function, 0)
 return CallData(
 caller_key=caller_key,
 callee_name=callee_name,
 call_type=call_type,
 line_number=line_number,
 )
__all__ = ["extract_calls", "_extract_one_call"]

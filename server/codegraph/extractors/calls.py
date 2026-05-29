"""Call 抽取器 —— 从 AST 中提取函数调用关系。
per: 系统能从代码文件中提取函数调用关系。
per: 仅文件内解析，caller 通过 WalkerNode.ancestor_function 判定。
per: call_type 支持 DIRECT / METHOD / ATTRIBUTE。
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any
import structlog
if TYPE_CHECKING:
 from codegraph.extractors.base import CallData, FileContext
logger = structlog.get_logger(__name__)
def extract_calls(tree: Any, ctx: "FileContext") -> "list[CallData]":
 """从 tree-sitter AST 提取所有函数调用关系。
 文件内调用归属其 ancestor_function；模块级调用（不在任何函数体内）
 caller_key[1] 用稳定字面 sentinel "<module>"。
 Args:
 tree: tree-sitter Tree 对象
 ctx: FileContext (file_path, language, repository_id, module_path)
 Returns:
 list[CallData]: 调用边列表
 """
 from codegraph.extractors.walker import CALL_TYPES, walk_tree
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
 模块级调用（无 ancestor_function）caller_key[1] 用 "<module>"，
 不再被丢弃；GraphWriter 据此写成 caller_symbol=NULL + caller_file 的边。
 内部函数供 GraphExtractor（orchestrator.py）复用。
 Args:
 wn: WalkerNode（携带 node + ancestor_function + ancestor_class）
 ctx: FileContext
 Returns:
 CallData | None: 成功返回 CallData，无法识别 callee 时返回 None
 """
 from codegraph.extractors.base import CallData
 node = wn.node
 # caller 归属：文件内调用用 ancestor_function；模块级调用（不在任何函数体内）
 # 用稳定字面 sentinel "<module>"（与 Vue 既有 "<template>" / "<script setup>"
 # 口径一致）。GraphWriter 在 symbol map 查不到该 caller 时即视为模块级边。
 caller_name = wn.ancestor_function or "<module>"
 # ★ JSX 元素分支：仅大写组件抽为 call_type=JSX
 if node.type in ("jsx_element", "jsx_self_closing_element"):
 opening = node if node.type == "jsx_self_closing_element" else None
 if opening is None:
 for child in node.children:
 if child.type == "jsx_opening_element":
 opening = child
 break
 if opening is None:
 return None
 name_node = opening.child_by_field_name("name")
 if name_node is None:
 return None
 jsx_callee = name_node.text
 if isinstance(jsx_callee, bytes):
 jsx_callee = jsx_callee.decode("utf-8")
 if not jsx_callee or not jsx_callee[0].isupper:
 #：HTML 原生小写标签（div / span / button 等）不抽
 return None
 return CallData(
 caller_key=(ctx.file_path, caller_name, 0),
 callee_name=jsx_callee,
 call_type="JSX",
 line_number=node.start_point[0] + 1,
 )
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
 elif function_node.type == "selector_expression":
 # Go: pkg.Method
 field_node = function_node.child_by_field_name("field")
 if field_node is not None:
 callee_name = field_node.text
 if isinstance(callee_name, bytes):
 callee_name = callee_name.decode("utf-8")
 call_type = "METHOD"
 else:
 return None
 elif function_node.type == "member_expression":
 # TS / TSX：obj.method 在 tree-sitter-typescript 用 member_expression
 property_node = function_node.child_by_field_name("property")
 if property_node is not None:
 callee_name = property_node.text
 if isinstance(callee_name, bytes):
 callee_name = callee_name.decode("utf-8")
 call_type = "METHOD"
 else:
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
 # 因同一文件内同名函数不会重复定义，(file_path, name) 足以唯一定位。
 # 模块级调用 name == "<module>"，symbol map 查不到 → GraphWriter 写模块级边。
 caller_key = (ctx.file_path, caller_name, 0)
 return CallData(
 caller_key=caller_key,
 callee_name=callee_name,
 call_type=call_type,
 line_number=line_number,
 )
__all__ = ["extract_calls", "_extract_one_call"]

"""单趟 AST DFS 遍历器 —— 共享 AST tree 一次遍历，维护祖先函数/类栈。

plan 的 Orchestrator（GraphExtractor.extract_all()）调用 walk_tree()，
在一次遍历中为四个抽取器分发节点。每个 WalkerNode 携带：
- node: tree-sitter 原始节点
- ancestor_function: 当前所在的最内层函数名（None 表示模块级）
- ancestor_class: 当前所在的最内层类名（None 表示不在类内）
"""

from dataclasses import dataclass
from typing import Any, Generator

import structlog

logger = structlog.get_logger(__name__)

# =============================================================================
# 节点类型映射表 —— 结构复刻 code_parser.py:work-item significant_types
# key=语言名, value=该语言中对应维度的 node_type 列表
# =============================================================================

SYMBOL_TYPES: dict[str, list[str]] = {
    "python": ["function_definition", "class_definition"],
    "javascript": ["function_declaration", "class_declaration", "arrow_function"],
    # work item interface/type → CLASS / work item 命名 arrow / work item method
    "typescript": [
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "method_definition",
        "lexical_declaration",
    ],
    # work item：tsx 与 typescript 字段级一致（显式 dict literal，避免间接引用）
    "tsx": [
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "method_definition",
        "lexical_declaration",
    ],
    "go": ["function_declaration", "method_declaration", "type_declaration"],
    # initial implementation：HTML element 节点统一入口；script_element / style_element
    # 是 tree-sitter-html 对 <script>/<style> 的特殊节点（不归 element），
    # 显式列出让 walker yield 这些节点，便于在 helper 内做 PascalCase / id 属性判别。
    "html": ["element", "script_element", "style_element"],
    "css": ["rule_set"],
}

IMPORT_TYPES: dict[str, list[str]] = {
    "python": ["import_statement", "import_from_statement"],
    "javascript": ["import_statement"],
    # work item export_statement 重导出
    "typescript": ["import_statement", "export_statement"],
    "tsx": ["import_statement", "export_statement"],
    "go": ["import_declaration"],
    # initial implementation：HTML <link href> / <img src> 走普通 element；
    # <script src> 走 script_element，需要双节点 yield 路径。
    "html": ["element", "script_element"],
    "css": ["import_statement"],
}

CALL_TYPES: dict[str, list[str]] = {
    "python": ["call"],
    "javascript": ["call_expression"],
    # work item：TS 不含 JSX
    "typescript": ["call_expression"],
    # work item / work item：TSX 额外含 jsx_element / jsx_self_closing_element
    "tsx": ["call_expression", "jsx_element", "jsx_self_closing_element"],
    "go": ["call_expression"],
    # initial implementation：HTML / CSS 无 callable 语义，显式 [] 让 walker 跳过 call 维度
    "html": [],
    "css": [],
}


@dataclass
class WalkerNode:
    """单次 AST DFS 遍历的节点上下文。

    携带原始 tree-sitter Node 及当前所在的函数/类上下文。
    plan 的 Call 抽取器通过 ancestor_function 判定 caller 归属。
    """

    node: Any  # tree_sitter.Node
    ancestor_function: str | None = None  # 当前所在函数名，模块级为 None
    ancestor_class: str | None = None  # 当前所在类名，不在类内为 None


def walk_tree(tree: Any, language: str) -> Generator[WalkerNode, None, None]:
    """单趟 AST DFS 遍历，按深度优先次序产出 WalkerNode。

    DFS 遍历过程中维护祖先栈：
    - function_stack: 追踪当前所在函数/方法（最近进入的最内层）
    - class_stack: 追踪当前所在类

    栈维护规则（仅对 SYMBOL_TYPES[language] 中的 node_type 生效）：
    - 进入 function_definition / method_declaration → push function_stack
    - 离开 function_definition / method_declaration → pop function_stack
    - 进入 class_definition → push class_stack
    - 离开 class_definition → pop class_stack
    - method（类内 function_definition）→ push function_stack 但不改变 class_stack

    Args:
        tree: tree-sitter Tree 对象（已调用 parser.parse() 的结果）
        language: 语言标识符，用于查 SYMBOL_TYPES 映射表

    Yields:
        WalkerNode: 每次产出携带当前节点 + 祖先上下文
    """
    symbol_types = SYMBOL_TYPES.get(language, [])
    function_stack: list[str] = []
    class_stack: list[str] = []

    # 内联递归函数 —— 保持闭包访问栈变量
    def _walk(node: Any) -> Generator[WalkerNode, None, None]:
        # 判断当前节点是否为符号定义，获取符号名
        # work item：method_definition 加入函数判定（TS class 内方法）
        # work item：lexical_declaration（命名 arrow_function 容器）当函数容器，
        # 取 variable_declarator.name 作 ancestor_function（用于内层 call 归属）
        node_is_function = node.type in ("function_definition", "function_declaration",
                                         "method_declaration", "arrow_function",
                                         "method_definition", "lexical_declaration")
        # work item：interface_declaration / type_alias_declaration 当作类（CLASS 符号）
        node_is_class = node.type in ("class_definition", "class_declaration", "type_declaration",
                                      "interface_declaration", "type_alias_declaration")
        node_name: str | None = None

        if node_is_function or node_is_class:
            # 提取符号名：取 name 子节点（tree-sitter 约定）
            name_node = node.child_by_field_name("name")
            # work item：lexical_declaration 没有 name 字段，下钻 variable_declarator
            # 当且仅当 value 是 arrow_function 时取 variable_declarator.name
            if name_node is None and node.type == "lexical_declaration":
                for child in node.children:
                    if child.type == "variable_declarator":
                        value_node = child.child_by_field_name("value")
                        if value_node is not None and value_node.type == "arrow_function":
                            name_node = child.child_by_field_name("name")
                            break
            if name_node is not None:
                node_name = name_node.text
                if isinstance(node_name, bytes):
                    node_name = node_name.decode("utf-8")

        # === 进入节点时的栈操作 ===
        pushed_function = False
        pushed_class = False

        if node_is_class and node_name:
            class_stack.append(node_name)
            pushed_class = True

        if node_is_function and node_name:
            function_stack.append(node_name)
            pushed_function = True

        # === 产出当前节点 ===
        yield WalkerNode(
            node=node,
            ancestor_function=function_stack[-1] if function_stack else None,
            ancestor_class=class_stack[-1] if class_stack else None,
        )

        # === 递归遍历子节点 ===
        for child in node.children:
            yield from _walk(child)

        # === 离开节点时的栈恢复 ===
        if pushed_function:
            function_stack.pop()
        if pushed_class:
            class_stack.pop()

    if tree.root_node is not None:
        yield from _walk(tree.root_node)


__all__ = [
    "WalkerNode",
    "walk_tree",
    "SYMBOL_TYPES",
    "IMPORT_TYPES",
    "CALL_TYPES",
]

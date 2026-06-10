"""Symbol 抽取器 —— 从 AST 中提取函数/类/方法定义。

per contract: Symbol 包含 name / symbol_type / file_path / start_line / end_line / signature / is_async
系统能从代码文件中提取函数/类/接口等符号定义
per implementation / Pitfall 8：_extract_one_symbol 返回类型从 SymbolData | None 升级为
list[SymbolData]，HTML element 一节点可能同时含 PascalCase tag + id 属性，需返多个；
CSS rule_set 同理（多 selector 拆解）。既有 python / go / ts 路径机械改 [sym] / []。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from codegraph.extractors.base import FileContext, SymbolData

logger = structlog.get_logger(__name__)

# HTML id 属性值合法 identifier 守卫
_HTML_ID_IDENTIFIER_RE = re.compile(r"^[\w\-]+$")


def extract_symbols(tree: Any, source: str, ctx: "FileContext") -> "list[SymbolData]":
    """从 tree-sitter AST 提取所有函数/类/方法定义。

    Args:
        tree: tree-sitter Tree 对象
        source: 源文件完整文本（用于签名提取）
        ctx: FileContext (file_path, language, repository_id, module_path)

    Returns:
        list[SymbolData]: 符号定义列表，按代码出现顺序排列
    """
    from codegraph.extractors.base import SymbolData
    from codegraph.extractors.walker import walk_tree, SYMBOL_TYPES

    symbol_types = SYMBOL_TYPES.get(ctx.language, [])
    if not symbol_types:
        return []

    symbols: list[SymbolData] = []

    for wn in walk_tree(tree, ctx.language):
        node = wn.node
        if node.type not in symbol_types:
            continue

        try:
            syms = _extract_one_symbol(wn, source, ctx)
            if syms:
                symbols.extend(syms)
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
) -> "list[SymbolData]":
    """从单个 WalkerNode 提取 SymbolData 列表。

    处理 function_definition / class_definition / decorated_definition 等节点；
    HTML element / script_element / style_element 走 _extract_html_symbol
    分支；CSS rule_set 由 plan 加分支。返回类型 list 让 HTML 一节点可输出多个 SymbolData。

    Args:
        wn: WalkerNode（携带 node + ancestor_function + ancestor_class）
        source: 源文件完整文本
        ctx: FileContext

    Returns:
        list[SymbolData]: 0 / 1 / N 个 SymbolData
    """
    from codegraph.extractors.base import SymbolData

    node = wn.node

    # implementation / HTML 分支（element / script_element / style_element）
    if ctx.language == "html" and node.type in ("element", "script_element", "style_element"):
        return _extract_html_symbol(node, source, ctx)

    # implementation / CSS 分支（rule_set）
    if ctx.language == "css" and node.type == "rule_set":
        return _extract_css_symbol(node, source, ctx)

    # --- 处理 decorated_definition：取出内部实际定义 ---
    actual_node = node
    is_decorated = False
    if node.type == "decorated_definition":
        is_decorated = True
        for child in node.children:
            if child.type in ("function_definition", "class_definition"):
                actual_node = child
                break

    # --- 提取名称（语言适配） ---
    name_node = actual_node.child_by_field_name("name")
    # Go type_declaration 没有直接 name 字段，需找内部的 type_spec
    if name_node is None and node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                name_node = child.child_by_field_name("name")
                break
    # TS / TSX lexical_declaration 仅抽取 value 为 arrow_function 的命名 const，
    # 从 variable_declarator.name 取符号名；非 arrow value（如 const x = 5）不抽
    if name_node is None and node.type == "lexical_declaration":
        for child in node.children:
            if child.type == "variable_declarator":
                value_node = child.child_by_field_name("value")
                if value_node is not None and value_node.type == "arrow_function":
                    name_node = child.child_by_field_name("name")
                    break
        if name_node is None:
            return []
    if name_node is None:
        return []
    name = name_node.text
    if isinstance(name, bytes):
        name = name.decode("utf-8")

    # --- 确定 symbol_type（语言适配） ---
    if actual_node.type == "class_definition":
        symbol_type = "CLASS"
    elif node.type == "type_declaration":
        symbol_type = "CLASS"  # Go struct/interface
    elif node.type == "class_declaration":
        symbol_type = "CLASS"  # TS / TSX class
    elif node.type == "interface_declaration":
        symbol_type = "CLASS"  # work item
    elif node.type == "type_alias_declaration":
        symbol_type = "CLASS"  # work item
    elif node.type == "method_definition":
        symbol_type = "METHOD"  # work item TS / TSX class 内方法
    elif node.type == "lexical_declaration":
        symbol_type = "FUNCTION"  # work item 命名 arrow_function
    elif wn.ancestor_class is not None:
        symbol_type = "METHOD"
    elif node.type == "method_declaration":
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
    body_only = "\n".join(body_text.split("\n")[1:]).strip()
    if len(body_only) < 10 and symbol_type != "CLASS":
        # 空函数/方法体（如 def foo(): pass）→ 仍保留但标记
        # 不跳过，因为 GraphWriter 后续可能需要这些符号
        pass

    return [
        SymbolData(
            name=name,
            symbol_type=symbol_type,
            file_path=ctx.file_path,
            start_line=start_line,
            end_line=end_line,
            signature=signature,
            is_async=is_async,
        )
    ]


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
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("class "):
                def_line_idx = i
                break
        if def_line_idx >= 0:
            # 取装饰器行（第 0 到 def_line_idx 行）
            return "\n".join(line.strip() for line in lines[: def_line_idx + 1])
        else:
            return lines[0].strip() if lines else ""
    else:
        # 取第一行作为签名
        first_line = lines[0].strip() if lines else ""
        return first_line


def _extract_html_symbol(
    node: Any, source: str, ctx: "FileContext"
) -> "list[SymbolData]":
    """从 HTML element / script_element / style_element 节点提取 SymbolData 列表。

    per implementation / 
    - PascalCase tag (len ≥ 3 + 首字母大写) → CLASS
    - 含连字符的 custom element (len ≥ 2) → CLASS
    - id 属性（合法 identifier）→ VARIABLE
    - 小写 HTML 原生 tag / class 属性 / 其他 attribute 不抽
    """
    from codegraph.extractors.base import SymbolData

    results: list[SymbolData] = []

    # 找 start_tag 或 self_closing_tag（Pitfall 1：双兜底）
    head_tag = None
    for child in node.children:
        if child.type in ("start_tag", "self_closing_tag"):
            head_tag = child
            break
    if head_tag is None:
        return results

    # 取 tag_name
    tag_name: str | None = None
    attributes: list[Any] = []
    for child in head_tag.children:
        if child.type == "tag_name" and tag_name is None:
            raw = child.text
            tag_name = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        elif child.type == "attribute":
            attributes.append(child)

    if tag_name is None:
        return results

    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1

    # PascalCase tag：首字母大写 + 长度 >= 3（守 work item 不命中 per work item）
    is_pascal = (
        len(tag_name) >= 3 and tag_name[0].isalpha() and tag_name[0].isupper()
    )
    # custom element: kebab-case (含 -) + 长度 >= 2
    is_custom = "-" in tag_name and len(tag_name) >= 2

    if is_pascal or is_custom:
        results.append(
            SymbolData(
                name=tag_name,
                symbol_type="CLASS",
                file_path=ctx.file_path,
                start_line=start_line,
                end_line=end_line,
                signature=f"<{tag_name}>",
                is_async=False,
            )
        )

    # id 属性扫描
    for attr in attributes:
        attr_name: str | None = None
        attr_value: str | None = None
        for child in attr.children:
            if child.type == "attribute_name":
                raw = child.text
                attr_name = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            elif child.type == "quoted_attribute_value":
                # 双层结构：quoted_attribute_value -> attribute_value
                for inner in child.children:
                    if inner.type == "attribute_value":
                        raw = inner.text
                        attr_value = (
                            raw.decode("utf-8") if isinstance(raw, bytes) else raw
                        )
                        break
            elif child.type == "attribute_value":
                raw = child.text
                attr_value = raw.decode("utf-8") if isinstance(raw, bytes) else raw

        if (
            attr_name == "id"
            and attr_value
            and _HTML_ID_IDENTIFIER_RE.match(attr_value)
        ):
            results.append(
                SymbolData(
                    name=attr_value,
                    symbol_type="VARIABLE",
                    file_path=ctx.file_path,
                    start_line=start_line,
                    end_line=end_line,
                    signature=f'id="{attr_value}"',
                    is_async=False,
                )
            )

    return results


def _extract_css_symbol(
    rule_set: Any, source: str, ctx: "FileContext"
) -> "list[SymbolData]":
    """从 CSS rule_set 节点提取 SymbolData 列表。

    per implementation / work item / Pitfall 5：
    - .foo / .button-primary → SymbolData(CLASS)
    - #app / #footer → SymbolData(VARIABLE)
    - tag selector (body / *) / pseudo (:hover) / CSS variable (--var) 不抽
    - 复合选择器 .complex.modifier:hover 递归拆解 → complex + modifier
      （跳过 :hover 内 class_name='hover'，因其挂在 pseudo_class_selector 而非 class_selector 下）
    - 同 rule_set 内同名去重（seen set by (name, symbol_type)）
    """
    from codegraph.extractors.base import SymbolData

    results: list[SymbolData] = []
    seen: set[tuple[str, str]] = set()

    # 找 selectors 子节点
    selectors_node = None
    for child in rule_set.children:
        if child.type == "selectors":
            selectors_node = child
            break
    if selectors_node is None:
        return results

    def _walk_selector(sel_node: Any) -> None:
        if sel_node.type == "class_selector":
            # 处理本层 class_selector：直接子节点中查 class_name 与嵌套 class_selector
            for child in sel_node.children:
                if child.type == "class_name":
                    raw = child.text
                    name = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    name = name.strip()
                    if not name:
                        continue
                    key = (name, "CLASS")
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(
                        SymbolData(
                            name=name,
                            symbol_type="CLASS",
                            file_path=ctx.file_path,
                            start_line=sel_node.start_point[0] + 1,
                            end_line=sel_node.end_point[0] + 1,
                            signature=f".{name}",
                            is_async=False,
                        )
                    )
                elif child.type == "class_selector":
                    _walk_selector(child)
            return
        if sel_node.type == "id_selector":
            for child in sel_node.children:
                if child.type == "id_name":
                    raw = child.text
                    name = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    name = name.strip()
                    if not name:
                        continue
                    key = (name, "VARIABLE")
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(
                        SymbolData(
                            name=name,
                            symbol_type="VARIABLE",
                            file_path=ctx.file_path,
                            start_line=sel_node.start_point[0] + 1,
                            end_line=sel_node.end_point[0] + 1,
                            signature=f"#{name}",
                            is_async=False,
                        )
                    )
            return
        # 其他类型（selectors / pseudo_class_selector / universal_selector / tag_name）→ 递归
        for child in sel_node.children:
            _walk_selector(child)

    _walk_selector(selectors_node)
    return results


__all__ = [
    "extract_symbols",
    "_extract_one_symbol",
    "_extract_html_symbol",
    "_extract_css_symbol",
]

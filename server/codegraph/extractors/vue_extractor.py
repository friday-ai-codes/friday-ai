"""Vue SFC 专用抽取器 —— SFC pre-splitter + TS backend 组合。

不引入 tree-sitter-vue grammar，依赖 Python pre-splitter
（vue_sfc_splitter）+ 复用 implementation 落地的 TS / TSX backend 完成 .vue 文件抽取。

VueExtractor.extract 6 步流程（per work item）：
1. 文件名 Component Symbol（per work item）
2. SFC 拆分（split_sfc）
3. script 段 dispatch 到 TreeSitterBackend("typescript" / "tsx")，行号偏移还原
4. template 反向引用（与 script_symbol_names 集合交集，per work item）
   + 模板子组件标签 <UserCard/> / <user-card/> 抽成 TEMPLATE_REF（per implementation
   子组件来自 import，不在 script 符号集，故独立产出、不取交集）
5. style 段不处理（per work item）
6. endpoints 安全返 []

后续 implementation 切 volar 时只需在此覆写 backend 注入路径。
"""

from __future__ import annotations

import os
import re

import structlog

from codegraph.backends.protocols import TreeSitterBackend
from codegraph.extractors.base import (
    CallData,
    ExtractionBundle,
    FileContext,
    SymbolData,
)
from codegraph.extractors.vue_sfc_splitter import SfcBlock, split_sfc

logger = structlog.get_logger(__name__)


_TEMPLATE_EVENT = re.compile(r'@[\w-]+\s*=\s*"(\w+)"')
_TEMPLATE_BIND = re.compile(r':[\w-]+\s*=\s*"(\w+)"')
_TEMPLATE_MUSTACHE = re.compile(r'\{\{\s*(\w+)\s*\}\}')

# 模板子组件标签扫描（per implementation / RESEARCH Pitfall 4）。
# 匹配开标签 / 自闭合标签的标签名（lookahead 限定后接空白 / `/` / `>`，
# 避免吞掉属性、且不匹配闭标签 `</X>`，线性扫描无灾难性回溯，命中 security mitigation）。
# 过滤口径：含连字符（kebab-case 子组件）或首字母大写（PascalCase 子组件）才视为
# 组件引用；纯小写单段标签（div/span/button...）为 HTML 原生标签，排除。
_TEMPLATE_COMPONENT = re.compile(r"<([A-Za-z][A-Za-z0-9.\-]*)(?=[\s/>])")

# Vue 3 / 2.7 编译时宏（per work item / work item）
# 这些宏在 <script setup> 中以模块级 call_expression 形式出现，
# 而 calls.py 仅抽文件内（有 ancestor_function）的调用，会漏识。
# VueExtractor 内置 fallback 扫描，per Pitfall 3 / security mitigation-11。
_SETUP_MACROS = {
    "defineProps",
    "defineEmits",
    "defineExpose",
    "defineModel",
    "defineOptions",
    "defineSlots",
}


class VueExtractor:
    """Vue Single-File Component (.vue) 抽取器。

    内部组合 vue_sfc_splitter + TreeSitterBackend("typescript")/("tsx") 实现
    Vue 2 Options API + Vue 2.7+ / 3 <script setup> 全形态抽取。

    决策：暂不支持外部 backend 注入（implementation 切 volar 时若需注入则覆写）。
    """

    def extract(
        self, file_path: str, source: str, ctx: FileContext
    ) -> ExtractionBundle:
        bundle = ExtractionBundle(file_path=file_path, language=ctx.language)

        component_name = _derive_component_name(file_path)
        if component_name:
            bundle.symbols.append(
                SymbolData(
                    name=component_name,
                    symbol_type="CLASS",
                    file_path=file_path,
                    start_line=1,
                    end_line=max(1, source.count("\n") + 1),
                    signature=source.split("\n", 1)[0].strip() if source else "",
                    is_async=False,
                )
            )

        blocks = split_sfc(source)

        script_blocks = [b for b in blocks if b.kind == "script"]
        if len(script_blocks) > 1:
            logger.warning(
                "vue_sfc_multiple_script_blocks",
                file_path=file_path,
                count=len(script_blocks),
                decision="use_first_only",
            )
        script_block = script_blocks[0] if script_blocks else None

        script_symbols: list[SymbolData] = []
        if script_block is not None:
            sub_lang = _resolve_script_lang(script_block)
            if sub_lang is not None:
                ts_backend = TreeSitterBackend(sub_lang)
                sub_ctx = FileContext(
                    file_path=file_path,
                    language=sub_lang,
                    repository_id=ctx.repository_id,
                    module_path=ctx.module_path,
                )
                tree = ts_backend.parse_file(file_path, script_block.content)
                sub_symbols = ts_backend.extract_symbols(
                    tree, script_block.content, sub_ctx
                )
                sub_imports = ts_backend.extract_imports(tree, sub_ctx)
                sub_calls = ts_backend.extract_calls(tree, sub_ctx)

                offset = script_block.line_offset - 1
                for s in sub_symbols:
                    s.start_line += offset
                    s.end_line += offset
                for c in sub_calls:
                    c.line_number += offset

                script_symbols = sub_symbols
                bundle.symbols.extend(sub_symbols)
                bundle.imports.extend(sub_imports)
                bundle.calls.extend(sub_calls)

                macro_calls = _extract_setup_macro_calls(
                    tree, file_path, script_block.line_offset
                )
                bundle.calls.extend(macro_calls)

        template_block = next((b for b in blocks if b.kind == "template"), None)
        if template_block is not None and script_symbols:
            template_refs = _scan_template_identifiers(template_block.content)
            script_symbol_names = {s.name for s in script_symbols}
            for ref in sorted(template_refs & script_symbol_names):
                bundle.calls.append(
                    CallData(
                        caller_key=(file_path, "<template>", 0),
                        callee_name=ref,
                        call_type="TEMPLATE_REF",
                        line_number=template_block.line_offset,
                    )
                )

        # 子组件标签引用：独立产出，不与 script 符号集取交集（子组件来自 import，
        # 不在 script 符号集；per work item / RESEARCH Pitfall 4）。即使无 script 符号
        # 也抽，callee_name 与 _derive_component_name 同口径（PascalCase）。
        if template_block is not None:
            for component in sorted(
                _scan_template_components(template_block.content)
            ):
                bundle.calls.append(
                    CallData(
                        caller_key=(file_path, "<template>", 0),
                        callee_name=component,
                        call_type="TEMPLATE_REF",
                        line_number=template_block.line_offset,
                    )
                )

        bundle.endpoints = []
        return bundle


def _derive_component_name(file_path: str) -> str:
    basename = os.path.basename(file_path)
    if basename.endswith(".vue"):
        return basename[: -len(".vue")]
    return basename


def _resolve_script_lang(script_block: SfcBlock) -> str | None:
    lang_attr = script_block.attrs.get("lang")
    if lang_attr is None or lang_attr is True:
        return "typescript"
    lang = str(lang_attr).lower()
    if lang in ("ts", "typescript", "js", "javascript"):
        return "typescript"
    if lang in ("tsx", "jsx"):
        return "tsx"
    logger.warning(
        "vue_sfc_unsupported_script_lang",
        lang=lang,
        decision="skip",
    )
    return None


def _scan_template_identifiers(template_content: str) -> set[str]:
    refs: set[str] = set()
    for pattern in (_TEMPLATE_EVENT, _TEMPLATE_BIND, _TEMPLATE_MUSTACHE):
        for m in pattern.finditer(template_content):
            refs.add(m.group(1))
    return refs


def _kebab_to_pascal(name: str) -> str:
    """kebab-case 组件标签名归一为 PascalCase（per RESEARCH A3）。

    `user-card` → `UserCard`，与 `_derive_component_name`（文件名 PascalCase）同口径，
    供 289 work item 钉到组件文件 Symbol。
    """
    return "".join(part[:1].upper() + part[1:] for part in name.split("-") if part)


def _scan_template_components(template_content: str) -> set[str]:
    """扫描模板中的子组件标签名集合（per work item / RESEARCH Pitfall 4）。

    识别 `<PascalCase .../>` 自闭合标签、成对 `<PascalCase ...>...</PascalCase>` 开标签，
    以及 kebab-case 形式 `<user-card/>`。归一规则：含连字符 → kebab→PascalCase；
    首字母大写 → 原样保留。排除 HTML 原生小写单段标签（无连字符且首字母小写，
    如 div/span/button），它们不是子组件引用。
    """
    components: set[str] = set()
    for m in _TEMPLATE_COMPONENT.finditer(template_content):
        tag = m.group(1)
        if "-" in tag:
            normalized = _kebab_to_pascal(tag)
            if normalized:
                components.add(normalized)
        elif tag[:1].isupper():
            components.add(tag)
    return components


def _extract_setup_macro_calls(
    tree: object, file_path: str, script_line_offset: int
) -> list[CallData]:
    """扫描 <script setup> 中模块级 macro call_expression（per Pitfall 3 fallback）。

    calls.py 跳过模块级调用（无 ancestor_function），但 Vue 3/2.7 的 defineProps /
    defineEmits / defineExpose 等宏在 setup 顶层调用时正是模块级。这里专门补上
    这些 macro 的 CallData，caller 用 `<script setup>` 字面，行号用脚本块在
    .vue 中的实际行号。
    """
    calls: list[CallData] = []
    root = getattr(tree, "root_node", None)
    if root is None:
        return calls

    offset = script_line_offset - 1

    def visit(node: object) -> None:
        node_type = getattr(node, "type", None)
        if node_type == "call_expression":
            fn = node.child_by_field_name("function")  # type: ignore[attr-defined]
            if fn is not None and getattr(fn, "type", None) == "identifier":
                name = fn.text
                if isinstance(name, bytes):
                    name = name.decode("utf-8")
                if name in _SETUP_MACROS:
                    line_number = node.start_point[0] + 1 + offset  # type: ignore[attr-defined]
                    calls.append(
                        CallData(
                            caller_key=(file_path, "<script setup>", 0),
                            callee_name=name,
                            call_type="DIRECT",
                            line_number=line_number,
                        )
                    )
        for child in getattr(node, "children", []) or []:
            visit(child)

    visit(root)
    return calls


__all__ = ["VueExtractor"]

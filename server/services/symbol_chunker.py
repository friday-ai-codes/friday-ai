"""符号驱动的代码切片核心（语言无关，两阶段共享）。

输入一组符号边界 ``SymbolSpan`` + 源码文本，产出 ``CodeChunk`` 列表。设计为
**纯函数 + 不依赖 tree-sitter**：只基于行号与文本操作，因此既能被 ``code_parser``
（tree-sitter 抽出的符号）复用，也能被 ``indexer`` 第二阶段（codegraph ``SymbolData``
映射的符号）复用，让 chunk 与 codegraph ``Symbol`` 同源、可直接绑定。

切分策略（替代旧 ``CodeParser._ast_aware_chunk`` 的四阶段，修复其两个核心缺陷）：

1. **顶层归一**：按行号排序，丢弃被其它符号包含的嵌套符号（类内方法等），只留顶层。
2. **收敛合并**：仅把**相邻**且**都很小**（< ``min_merge_lines`` 行）且 kind 可合并
   （function/variable/other，**class/method 不参与**）的符号并成一个 chunk——避免旧实现
   把"类 + 多个小函数"无差别揉成一坨的 bug。
3. **大符号按行窗口二次切分**：> ``max_chars`` 的符号按行切成多个带重叠的子 chunk，
   **保证不丢尾**——区别于旧实现的 ``content[:max_chars]`` 粗暴截断（丢代码）。
4. **模块级收尾**：未被任何符号覆盖的连续行段（import / 常量 / 顶层语句）各自成
   module chunk（过滤纯空白 / 注释段）。
"""

from __future__ import annotations

from services.code_chunk import CodeChunk, SymbolSpan

__all__ = ["build_chunks_from_spans", "normalize_kind"]


# tree-sitter node.type → 规范化 kind 的映射集合
_CLASS_LIKE_TYPES: frozenset[str] = frozenset({
    "class",
    "class_definition",
    "class_declaration",
    "type_declaration",
    "interface_declaration",
    "type_alias_declaration",
    "enum_declaration",
})
_METHOD_TYPES: frozenset[str] = frozenset({
    "method",
    "method_definition",
    "method_declaration",
})
_FUNCTION_TYPES: frozenset[str] = frozenset({
    "function",
    "function_definition",
    "function_declaration",
    "arrow_function",
    "lexical_declaration",
})

# 参与"小符号合并"的 kind —— class / method 独立成块，不卷入合并组。
_MERGEABLE_KINDS: frozenset[str] = frozenset({"function", "variable", "other"})


def normalize_kind(node_type: str = "", *, symbol_type: str | None = None) -> str:
    """把 tree-sitter ``node.type`` 或 codegraph ``symbol_type`` 归一为 kind。

    Args:
        node_type: tree-sitter 节点类型（第一阶段 code_parser 来源）。
        symbol_type: codegraph ``SymbolData.symbol_type``（第二阶段来源），
            取值 ``CLASS | METHOD | FUNCTION | VARIABLE``；非 None 时优先。

    Returns:
        ``"function" | "class" | "method" | "variable" | "other"``。
    """
    if symbol_type:
        return {
            "CLASS": "class",
            "METHOD": "method",
            "FUNCTION": "function",
            "VARIABLE": "variable",
        }.get(symbol_type.upper(), "other")
    if node_type in _CLASS_LIKE_TYPES:
        return "class"
    if node_type in _METHOD_TYPES:
        return "method"
    if node_type in _FUNCTION_TYPES:
        return "function"
    return "other"


def build_chunks_from_spans(
    spans: list[SymbolSpan],
    content: str,
    *,
    file_path: str,
    file_hash: str,
    language: str,
    max_chars: int = 2000,
    min_merge_lines: int = 10,
    overlap_lines: int = 5,
) -> list[CodeChunk]:
    """从符号边界 + 源码产出 chunk 列表（核心入口）。

    Args:
        spans: 符号边界列表（行号可乱序 / 含嵌套，内部会归一）。
        content: 源文件完整文本。
        file_path / file_hash / language: 写入每个 ``CodeChunk`` 的元信息。
        max_chars: 单 chunk 字符上限；超限的符号按行窗口二次切分。
        min_merge_lines: 小符号阈值（行数 < 此值才可能参与合并）。
        overlap_lines: 大符号二次切分时相邻子 chunk 的重叠行数。

    Returns:
        按 ``(start_line, end_line)`` 升序排列的 ``CodeChunk`` 列表。
    """
    lines = content.split("\n")
    total_lines = len(lines)

    # --- 阶段 1：清洗 + 排序 + 顶层归一 ---
    cleaned: list[SymbolSpan] = []
    for s in spans:
        if s.start_line < 1 or s.end_line < s.start_line or s.start_line > total_lines:
            continue
        cleaned.append(
            SymbolSpan(
                name=s.name,
                kind=s.kind,
                start_line=s.start_line,
                end_line=min(s.end_line, total_lines),
                node_type=s.node_type,
                symbol_key=s.symbol_key,
            )
        )
    # 起始行升序；同起始行时长区间在前，便于"嵌套被包含"判定。
    cleaned.sort(key=lambda s: (s.start_line, -s.end_line))

    top: list[SymbolSpan] = []
    for s in cleaned:
        if top and s.start_line >= top[-1].start_line and s.end_line <= top[-1].end_line:
            continue  # 完全嵌套在上一个顶层符号内（如类内方法）→ 跳过
        top.append(s)

    # --- 阶段 2：收敛合并相邻小符号 ---
    merged = _merge_small_adjacent(top, min_merge_lines)

    # --- 阶段 3：每个符号 → chunk（大符号按行窗口切，保证不丢尾）---
    chunks: list[CodeChunk] = []
    for span in merged:
        seg = _join_lines(lines, span.start_line, span.end_line)
        if len(seg) <= max_chars:
            chunks.append(_make_symbol_chunk(seg, span, file_path, file_hash, language))
        else:
            chunks.extend(
                _split_large(
                    lines, span, file_path, file_hash, language, max_chars, overlap_lines
                )
            )

    # --- 阶段 4：模块级收尾（未被任何符号覆盖的行）---
    covered: set[int] = set()
    for span in merged:
        covered.update(range(span.start_line, span.end_line + 1))
    chunks.extend(
        _module_chunks(lines, covered, file_path, file_hash, language, max_chars, overlap_lines)
    )

    chunks.sort(key=lambda c: (c.start_line, c.end_line))
    return chunks


def _merge_small_adjacent(
    spans: list[SymbolSpan], min_merge_lines: int
) -> list[SymbolSpan]:
    """合并相邻的小符号（仅 function/variable/other 且 < min_merge_lines 行）。

    class / method 始终独立成块；遇到大符号或不可合并 kind 立即断开聚合。
    """
    if not spans:
        return []

    result: list[SymbolSpan] = []
    n = len(spans)
    i = 0
    while i < n:
        cur = spans[i]
        cur_lines = cur.end_line - cur.start_line + 1
        if cur.kind in _MERGEABLE_KINDS and cur_lines < min_merge_lines:
            group = [cur]
            j = i + 1
            while j < n:
                nxt = spans[j]
                nxt_lines = nxt.end_line - nxt.start_line + 1
                gap = nxt.start_line - group[-1].end_line
                if (
                    nxt.kind in _MERGEABLE_KINDS
                    and nxt_lines < min_merge_lines
                    and gap <= 2
                ):
                    group.append(nxt)
                    j += 1
                else:
                    break
            if len(group) == 1:
                result.append(cur)
            else:
                names = [g.name for g in group if g.name]
                result.append(
                    SymbolSpan(
                        name="; ".join(names) if names else None,
                        kind="merged",
                        start_line=group[0].start_line,
                        end_line=group[-1].end_line,
                        node_type="merged_group",
                        symbol_key=None,  # 合并组无单一 Symbol 绑定
                    )
                )
            i = j
        else:
            result.append(cur)
            i += 1
    return result


def _join_lines(lines: list[str], start: int, end: int) -> str:
    """取 1-based 闭区间 [start, end] 的行文本。"""
    return "\n".join(lines[start - 1 : end])


def _make_symbol_chunk(
    seg: str, span: SymbolSpan, file_path: str, file_hash: str, language: str
) -> CodeChunk:
    node_type = span.node_type or span.kind
    header = f"File: {file_path} | Language: {language} | Type: {node_type}"
    if span.name:
        header += f" | Symbol: {span.name}"
    return CodeChunk(
        content=seg,
        file_path=file_path,
        file_hash=file_hash,
        language=language,
        start_line=span.start_line,
        end_line=span.end_line,
        node_type=node_type,
        context_header=header,
        parent_symbol=span.name,
        symbol_key=span.symbol_key,
    )


def _split_large(
    lines: list[str],
    span: SymbolSpan,
    file_path: str,
    file_hash: str,
    language: str,
    max_chars: int,
    overlap_lines: int,
) -> list[CodeChunk]:
    """大符号按行窗口二次切分（带 overlap，保证覆盖到尾、不丢代码）。"""
    seg_lines = lines[span.start_line - 1 : span.end_line]
    node_type = span.node_type or span.kind
    chunks: list[CodeChunk] = []
    part = 0
    n = len(seg_lines)
    i = 0
    while i < n:
        j = i
        chars = 0
        # 至少纳入一行（j == i），避免单行超长导致死循环。
        while j < n:
            add = len(seg_lines[j]) + 1
            if chars + add > max_chars and j > i:
                break
            chars += add
            j += 1
        abs_start = span.start_line + i
        abs_end = span.start_line + j - 1
        seg = "\n".join(seg_lines[i:j])
        chunks.append(
            _make_part_chunk(
                seg, span, node_type, abs_start, abs_end, part, file_path, file_hash, language
            )
        )
        part += 1
        if j >= n:
            break
        i = max(j - overlap_lines, i + 1)  # 带重叠回退，但保证严格前进
    return chunks


def _make_part_chunk(
    seg: str,
    span: SymbolSpan,
    node_type: str,
    start_line: int,
    end_line: int,
    part: int,
    file_path: str,
    file_hash: str,
    language: str,
) -> CodeChunk:
    header = f"File: {file_path} | Language: {language} | Type: {node_type}"
    if span.name:
        header += f" | Symbol: {span.name}"
    header += f" | Part: {part}"
    return CodeChunk(
        content=seg,
        file_path=file_path,
        file_hash=file_hash,
        language=language,
        start_line=start_line,
        end_line=end_line,
        node_type=node_type,
        context_header=header,
        parent_symbol=span.name,
        symbol_key=span.symbol_key,
    )


def _module_chunks(
    lines: list[str],
    covered: set[int],
    file_path: str,
    file_hash: str,
    language: str,
    max_chars: int,
    overlap_lines: int,
) -> list[CodeChunk]:
    """未被任何符号覆盖的连续行段 → module chunk（过滤纯空白 / 注释段）。"""
    total = len(lines)
    chunks: list[CodeChunk] = []

    # 收集未覆盖的连续行段（1-based 闭区间）。
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for ln in range(1, total + 1):
        if ln not in covered:
            if start is None:
                start = ln
        elif start is not None:
            ranges.append((start, ln - 1))
            start = None
    if start is not None:
        ranges.append((start, total))

    for rs, re_ in ranges:
        seg = _join_lines(lines, rs, re_)
        meaningful = "\n".join(
            ln for ln in seg.split("\n")
            if ln.strip() and not ln.strip().startswith(("#", "//"))
        ).strip()
        if len(meaningful) < 20:
            continue  # 纯空白 / 注释 / 过短段不单独成 chunk
        if len(seg) <= max_chars:
            chunks.append(_make_module_chunk(seg, rs, re_, file_path, file_hash, language))
        else:
            span = SymbolSpan(
                name=None, kind="module", start_line=rs, end_line=re_, node_type="module"
            )
            chunks.extend(
                _split_large(
                    lines, span, file_path, file_hash, language, max_chars, overlap_lines
                )
            )
    return chunks


def _make_module_chunk(
    seg: str, start_line: int, end_line: int, file_path: str, file_hash: str, language: str
) -> CodeChunk:
    header = f"File: {file_path} | Language: {language} | Type: module"
    return CodeChunk(
        content=seg,
        file_path=file_path,
        file_hash=file_hash,
        language=language,
        start_line=start_line,
        end_line=end_line,
        node_type="module",
        context_header=header,
        parent_symbol=None,
    )

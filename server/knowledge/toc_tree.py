"""知识文档章节树（toc_tree）确定性生成（PageIndex 化）。

从 markdown 标题层级构建章节树（类似 PageIndex 的 markdown ``#`` 模式），
并把每个章节映射到 chunk index——检索命中 chunk 后可回溯"这条内容来自
《XX 方案 > 接口设计 > 鉴权》"，并支持 tree-walk 拉父/邻章节补上下文。

纯函数、零 LLM、零 I/O：同一 (title, content, chunks) 输入产出字节级一致
的树；与 chunk_knowledge_text 同源（标题行保留在所属 chunk 段首），章节
heading 行在 chunk 文本中逐字可寻，据此建立 chunk 映射。

节点结构：
    {"node_id": "t-1", "title": "接口设计", "level": 2,
     "summary": "首行正文截断", "chunk_indexes": [1, 2], "children": [...]}
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["build_toc_tree", "find_node_path_for_chunk"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_SUMMARY_MAX = 120


def _section_summary(content: str, start: int, end: int) -> str:
    """章节首个非空、非标题行截断作为 summary（确定性，零 LLM）。"""
    for line in content[start:end].splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:_SUMMARY_MAX]
    return ""


def build_toc_tree(
    title: str, content: str, chunk_texts: list[str]
) -> list[dict[str, Any]]:
    """构建章节树并映射 chunk indexes。

    Args:
        title: 实体标题。
        content: 版本全文（markdown 优先）。
        chunk_texts: chunk_knowledge_text 产出的各 chunk 文本（按 index 序）。

    Returns:
        章节树 roots 列表；content 无标题结构时返回 []（无树可建，
        检索侧自然退化为无章节路径）。
    """
    content = (content or "").strip()
    if not content:
        return []

    headings = list(_HEADING_RE.finditer(content))
    if not headings:
        return []

    # 1. 顺序建节点（带正文区间）
    flat: list[dict[str, Any]] = []
    for i, m in enumerate(headings):
        level = len(m.group(1))
        section_start = m.end()
        section_end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
        flat.append(
            {
                "node_id": f"t-{i + 1}",
                "title": m.group(2),
                "level": level,
                "summary": _section_summary(content, section_start, section_end),
                "heading_line": m.group(0).strip(),
                "chunk_indexes": [],
                "children": [],
            }
        )

    # 2. chunk 映射：heading 行在 chunk 文本中逐字可寻；
    #    无 heading 的延续 chunk 归属最近的前序章节。
    last_node: dict[str, Any] | None = None
    node_by_heading_order = flat
    for chunk_index, text in enumerate(chunk_texts):
        matched_any = False
        for node in node_by_heading_order:
            if node["heading_line"] and node["heading_line"] in text:
                node["chunk_indexes"].append(chunk_index)
                last_node = node
                matched_any = True
        if not matched_any and last_node is not None and chunk_index > 0:
            # summary chunk(0) 不强行归属章节；后续延续块归前序章节
            last_node["chunk_indexes"].append(chunk_index)

    # 3. 层级组装（标准栈算法）
    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for node in flat:
        node.pop("heading_line", None)
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)

    return roots


def find_node_path_for_chunk(
    toc_tree: list[dict[str, Any]], chunk_index: int
) -> list[str]:
    """查 chunk 所属章节的标题路径（如 ["接口设计", "鉴权"]）；无归属返回 []。

    深层节点优先（chunk 同时挂在父子节点时取最深路径）。
    """
    best: list[str] = []

    def _walk(nodes: list[dict[str, Any]], path: list[str]) -> None:
        nonlocal best
        for node in nodes:
            current = [*path, str(node.get("title", ""))]
            if chunk_index in (node.get("chunk_indexes") or []) and len(current) > len(best):
                best = current
            _walk(node.get("children", []), current)

    _walk(toc_tree, [])
    return best

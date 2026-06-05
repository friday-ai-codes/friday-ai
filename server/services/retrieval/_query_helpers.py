"""查询关键词抽取 + L3 markdown 格式化共享工具（per initial implementation contract 修复）。

历史背景：``HybridSearchService`` 复用 ``LayeredSearchService._extract_symbol_names``
/ ``_format_l3_section`` 私有方法（per plan idiom "复用 initial implementation 既有"），但
跨模块调用 ``_`` 开头方法违反 Python 强约定。LayeredSearchService 重构时这两个
hidden contract 会静默 break HybridSearchService。

本模块解耦：把两个工具迁出 LayeredSearchService 私有命名空间，让
HybridSearchService 与（即将下线的）LayeredSearchService 都从中 import；保
byte-eq 输出。
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["extract_symbol_keywords", "format_l3_section"]


_KEYWORDS: set[str] = {
    "if", "for", "while", "class", "def", "function", "var", "const", "let",
    "return", "import", "from", "package", "func", "type", "interface",
    "the", "and", "not", "or", "in", "is", "as", "with",
}
"""英文 / 编程通用停用词，避免 ``If`` / ``Class`` 这类大写 PascalCase 形态被误判
为符号名（per RESEARCH Pitfall 3）。"""


def extract_symbol_keywords(query: str) -> list[str]:
    """从查询文本中提取候选符号名（最多 10 个，去重保序）。

    匹配规则：

    - PascalCase（``UserModel`` / ``CreateUser`` 等大写开头标识符）
    - 点号分隔标识符（``django.db.models`` 等模块路径）
    - 大小写不敏感剔除 ``_KEYWORDS`` 停用词
    """
    pascal = re.findall(r"\b[A-Z][a-zA-Z0-9_]+\b", query)
    dotted = re.findall(r"\b[a-z][a-zA-Z0-9_]*\.[a-z_][a-zA-Z0-9_.]*\b", query)
    terms = [t for t in pascal + dotted if t.lower() not in _KEYWORDS]
    seen: set[str] = set()
    result: list[str] = []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            result.append(t)
    return result[:10]


def format_l3_section(items: list[dict[str, Any]]) -> str:
    """格式化 L3 混合搜索 section（``## L3 Related Code`` 头 + 每条 chunk 三段）。

    输出示例::

        ## L3 Related Code

        ### src/foo.py (score: 0.850)
        ```
        def foo(): pass
        ```

    空 ``items`` → 渲染 ``(no hybrid search results)`` 占位行。
    """
    lines = ["## L3 Related Code\n"]
    if not items:
        lines.append("(no hybrid search results)")
    else:
        for item in items:
            payload = item.get("payload", {})
            fp = payload.get("file_path", "unknown")
            score = item.get("score", 0.0)
            content = payload.get("content", "")
            lines.append(f"### {fp} (score: {score:.3f})\n```\n{content}\n```\n")
    return "\n".join(lines)

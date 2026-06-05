"""``find_related_code`` ↔ ``search_repository_code`` description 决策树语义锁
—— per initial implementation plan 03 / work-item contract。

snapshot（``test_tool_contracts.py``）锁的是字节级漂移，本文件锁**语义关键字**：
确认决策树文字真在 description 中，避免「重排序文字 / 同义词替换」绕过 snapshot
报警而丢失对 LLM 的关键引导。

判别哲学（per context contract 决策树）：

- 拿到自然语言 query → 选 ``search_repository_code``
- 拿到 file / chunk_id / symbol_name 起点 → 选 ``find_related_code``

两个 tool description **互相引用对方名字**形成对偶：让 LLM 读任一 tool description
即可发现 counterpart 工具，而不必依赖外层 system prompt 单独说明决策树。
"""

from __future__ import annotations


def test_find_related_code_description_has_decision_tree() -> None:
    """``find_related_code`` description 含 4 关键决策树锚点（per context contract）。

    - ``CONCRETE starting point``：触发条件锚点（拿到具体起点才用本工具）
    - ``DO NOT USE FOR natural language queries``：排他子句（拒绝自然语言 query）
    - ``Decision tree:``：决策树代码块头
    - ``search_repository_code``：counterpart 工具名（对偶引用）
    """
    from agents.tools.find_related_code import find_related_code

    desc = find_related_code._tool_definition.description  # type: ignore[attr-defined]
    assert "CONCRETE starting point" in desc, (
        "missing 'CONCRETE starting point' anchor —— "
        "决策树触发条件，per context contract"
    )
    assert "DO NOT USE FOR natural language queries" in desc, (
        "missing exclusion clause for natural language queries —— "
        "排他子句保护 LLM 误用，per context contract"
    )
    assert "Decision tree:" in desc, (
        "missing 'Decision tree:' header —— per context contract"
    )
    assert "search_repository_code" in desc, (
        "missing counterpart tool name —— "
        "对偶引用让 LLM 读 find_related description 即可发现 counterpart"
    )


def test_search_repository_code_description_references_find_related() -> None:
    """``search_repository_code`` description 末尾追加对偶决策树尾注。

    - ``find_related_code``：counterpart 工具名（对偶引用回 find_related）
    - ``CONCRETE starting point``：复用同一锚点关键字让两 tool description 决策树
      表述统一（LLM 不需识别两套表达）
    """
    from agents.tools.space_tools import search_repository_code

    desc = search_repository_code._tool_definition.description  # type: ignore[attr-defined]
    assert "find_related_code" in desc, (
        "missing counterpart reference back to find_related_code —— "
        "对偶决策树尾注必须出现"
    )
    assert "CONCRETE starting point" in desc, (
        "missing 'CONCRETE starting point' anchor in counterpart note —— "
        "两 tool description 锚点关键字保持统一表述"
    )

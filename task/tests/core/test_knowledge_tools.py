"""knowledge_tools 白名单：rename_preview（RENAME-01 / D-12）。"""

from __future__ import annotations

from core.knowledge_tools import KNOWLEDGE_TOOL_SCHEMAS, knowledge_allowed_tools


def test_rename_preview_in_knowledge_whitelist() -> None:
    """白名单含 rename_preview；失败不阻断交付（描述需明示）。

    （Req: RENAME-01, 决策: D-12）
    """
    names = [s["name"] for s in KNOWLEDGE_TOOL_SCHEMAS]
    assert "rename_preview" in names
    schema = next(s for s in KNOWLEDGE_TOOL_SCHEMAS if s["name"] == "rename_preview")
    assert "repository_id" in schema["input_schema"]["properties"]
    assert "new_name" in schema["input_schema"]["properties"]
    required = schema["input_schema"]["required"]
    assert "repository_id" in required
    assert "new_name" in required
    desc = schema["description"]
    assert "preview" in desc.lower() or "预览" in desc
    assert "不阻断" in desc or "继续交付" in desc
    allowed = knowledge_allowed_tools()
    assert "mcp__friday-knowledge__rename_preview" in allowed

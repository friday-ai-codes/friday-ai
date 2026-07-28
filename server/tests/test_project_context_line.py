"""项目级对话指引行：方案工具引导契约。"""

from __future__ import annotations

from types import SimpleNamespace

from chat.config import _build_project_context_line


def test_project_context_line_guides_feature_solution_tool() -> None:
    project = SimpleNamespace(
        name="高三提分专项",
        space=SimpleNamespace(name="学习工具"),
    )

    line = _build_project_context_line(project)

    assert "当前项目：高三提分专项（所属空间：学习工具）" in line
    assert "start_feature_solution" in line
    assert "get_project_overview" in line
    assert "list_project_features" in line
    assert "不能替代方案产出" in line
    assert "create_coding_plan" in line
    assert "start_plan_research" in line
    assert "成批功能点" in line or "技术方案" in line

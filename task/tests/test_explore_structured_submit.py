"""explore 链结构化提交测试（260818-pt8 Task 2）。

覆盖 blueprint_research_fitness / blueprint_repo_plan 两场景：
- 有 submit_scenario → 挂载共享 friday-submit MCP，收口只经 apply_capture_to_result；
- 已捕获 + SDK 空文本 → 仍成功并带 mcp_result；
- 未调用工具 → 明确失败（mcp_tool_not_called）；
- 无 submit_scenario → 普通 explore 零回归（不挂提交工具）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.config import TaskConfig
from core.executor import ClaudeRunner


def _make_runner(tmp_path: Path, *, submit_scenario: str = "") -> ClaudeRunner:
    config = TaskConfig(
        task_id="test-explore-submit",
        task_description="深度分析本仓适配度",
        git_repo_url="https://test.com/repo.git",
        task_mode="explore",
        submit_scenario=submit_scenario,
        session_dir=str(tmp_path / "sessions"),
    )
    return ClaudeRunner(config, tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "tool"),
    [
        ("blueprint_research_fitness", "mcp__friday-submit__submit_blueprint_fitness"),
        ("blueprint_repo_plan", "mcp__friday-submit__submit_blueprint_repo_plan"),
    ],
)
async def test_explore_mounts_scenario_tool(tmp_path, monkeypatch, scenario, tool):
    import core.executor as executor_mod
    from core.agent_submit_mcp import build_submit_mcp as real_build

    runner = _make_runner(tmp_path, submit_scenario=scenario)
    built = real_build(scenario)
    monkeypatch.setattr(executor_mod, "build_submit_mcp", lambda s: built)

    async def fake_execute(**kwargs):
        # 断言挂载信息正确
        assert tool in kwargs["extra_allowed_tools"]
        assert "friday-submit" in kwargs["extra_mcp_servers"]
        assert tool in kwargs["prompt"]
        if scenario == "blueprint_repo_plan":
            assert kwargs["max_turns"] >= 80
        built.capture.value = {"ok": True}
        return {"success": False, "error": "Claude SDK returned empty response"}

    runner._execute_claude = AsyncMock(side_effect=fake_execute)
    result = await runner.run_explore_mode()

    assert result["success"] is True
    assert result["mcp_result"] == {"ok": True}
    assert result["submit_scenario"] == scenario


@pytest.mark.asyncio
async def test_explore_scenario_not_called_fails(tmp_path):
    runner = _make_runner(tmp_path, submit_scenario="blueprint_research_fitness")
    runner._execute_claude = AsyncMock(return_value={"success": True, "output": "some free text"})

    result = await runner.run_explore_mode()

    assert result["success"] is False
    assert result["error_reason"] == "mcp_tool_not_called"
    assert "mcp_result" not in result


@pytest.mark.asyncio
async def test_explore_unknown_scenario_fails(tmp_path):
    runner = _make_runner(tmp_path, submit_scenario="not_a_scenario")
    runner._execute_claude = AsyncMock(return_value={"success": True})

    result = await runner.run_explore_mode()

    assert result["success"] is False
    assert "unknown submit scenario" in result["error"]


@pytest.mark.asyncio
async def test_explore_without_scenario_is_plain(tmp_path):
    """无 submit_scenario：普通 explore 零回归（不挂提交工具）。"""
    runner = _make_runner(tmp_path, submit_scenario="")
    captured: dict = {}

    async def fake_execute(**kwargs):
        captured.update(kwargs)
        return {"success": True, "output": "plain analysis text"}

    runner._execute_claude = AsyncMock(side_effect=fake_execute)
    result = await runner.run_explore_mode()

    assert result["success"] is True
    assert "extra_mcp_servers" not in captured or not captured.get("extra_mcp_servers")
    assert "mcp_result" not in result

"""PF-01 工具名一致性守护测试（implementation contract）。

守护 ``AIPlanGenerationNode`` 引用的检索工具名与 ``_tool_registry`` 注册名一致：

- ``get_enabled_tools(context)`` 返回的每个工具名都在 ``agents.tools.base._tool_registry``
  （防止再次出现 search_code 这类漂移名静默失效）。
- ``_PLAN_GENERATION_BASE_PROMPT`` system prompt 常量不再出现子串 ``search_code``，
  且其引用的检索工具名 ``search_repository_code`` 存在于 ``_tool_registry``。
"""

from __future__ import annotations

# 触发工具注册（search_repository_code 在 space_tools，verify_plan/send_plan_card 等）
import agents.tools  # noqa: F401
from agents.tools.base import _tool_registry
from workflows.nodes.ai.plan_generation import (
    _PLAN_GENERATION_BASE_PROMPT,
    AIPlanGenerationNode,
)
from workflows.nodes.base import ExecutionContext


def _make_context() -> ExecutionContext:
    return ExecutionContext(
        execution_id="00000000-0000-0000-0000-000000000001",
        node_id="00000000-0000-0000-0000-000000000011",
        node_config={"user_prompt": "demo"},
        input_data={},
        workflow_context={},
        previous_outputs={},
    )


def test_enabled_tools_all_registered() -> None:
    """get_enabled_tools 返回的每个工具名都在 _tool_registry。"""
    node = AIPlanGenerationNode()
    tools = node.get_enabled_tools(_make_context())

    assert tools is not None
    missing = [name for name in tools if name not in _tool_registry]
    assert not missing, f"白名单引用了未注册工具名（PF-01 漂移）：{missing}"


def test_enabled_tools_uses_registered_search_name() -> None:
    """检索工具用注册名 search_repository_code，不再出现漂移名 search_code。"""
    node = AIPlanGenerationNode()
    tools = node.get_enabled_tools(_make_context())

    assert tools is not None
    assert "search_repository_code" in tools
    assert "search_code" not in tools


def test_base_prompt_no_search_code_drift() -> None:
    """system prompt 常量不含 search_code，引用的 search_repository_code 已注册。"""
    assert "search_code" not in _PLAN_GENERATION_BASE_PROMPT
    assert "search_repository_code" in _PLAN_GENERATION_BASE_PROMPT
    assert "search_repository_code" in _tool_registry

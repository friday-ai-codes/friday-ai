"""SPINE-02 正向不变量守护 —— 「徒手编写方案正文」在结构上不可能（Phase 109 · 裁决 D-2）。

这条断言锁的是**结构上不可能**，而不是「prompt 里不建议」。SPINE-02 的字面要求是
「系统不再存在由对话模型徒手编写方案正文的产出路径」，其唯一达成手段是**从工具
schema 移除创作入参** —— schema 是 LLM 可见能力的唯一定义处，prompt 只是软约束。

未来任何把 ``tech_plan`` / ``affected_files`` 加回入参的改动都会在此变红。除两个具名
入参的否定断言外，还有一组 ``properties`` 键集合的**枚举式相等断言** —— 它让「悄悄
加一个新的正文别名入参」（如 ``plan_markdown`` / ``files``）同样变红，而不是只防住
这两个具体名字。

守护分层（三条互不替代）：

- 本文件：正向不变量（创作入参**不存在**）+ 键集合枚举。
- ``tests/agents/test_tool_contracts.py``：函数签名字节级 snapshot（109-01 baseline），
  任何增删都要求走 ``_REGENERATE_HINT`` 的显式再生成 + review 提交。
- ``tests/test_coding_tools.py``：行为断言（投影落库、无来源拒绝、跨会话拒绝）。
"""

from __future__ import annotations

import inspect

import pytest

import agents.tools.coding_tools  # noqa: F401 —— @tool 注册是 import 副作用
from agents.tools.registry import ToolRegistry

# 结构上不可能徒手编方案 —— 这两个入参一旦回归即为 SPINE-02 回退。
_AUTHORING_PARAMS = ("tech_plan", "affected_files")

# 收窄后允许的入参全集。枚举式相等断言的基准：多一个键就红，因此新增任何入参
# （包括正文的别名）都必须先在此显式登记，逼出一次「这是不是又开了创作口子」的 review。
_ALLOWED_PROPERTIES = {
    "create_coding_plan": {
        "space_id",
        "conversation_id",
        "artifact_version_id",
        "repository_id",
        "recommended_repository_ids",
    },
    "update_coding_plan": {
        "coding_plan_id",
        "session_id",
        "artifact_version_id",
    },
}

_REGRESSION_HINT = (
    "SPINE-02 回退：方案正文入参被加回。方案正文只能来自完整编排链路产出的 "
    "ArtifactVersion，经 chat.plan_projection_service 投影/re-bind 进来；"
    "工具 schema 不得重新接受任何形式的正文入参。"
)


@pytest.mark.parametrize("tool_name", sorted(_ALLOWED_PROPERTIES))
@pytest.mark.parametrize("param", _AUTHORING_PARAMS)
def test_authoring_param_absent_from_tool_schema(tool_name: str, param: str) -> None:
    tool = ToolRegistry.get_tool(tool_name)
    assert tool is not None, f"{tool_name} 未注册"
    props = tool.parameters["properties"]
    assert param not in props, f"{_REGRESSION_HINT}（{tool_name}.{param} 出现在 schema）"


@pytest.mark.parametrize("tool_name", sorted(_ALLOWED_PROPERTIES))
def test_artifact_version_id_is_required(tool_name: str) -> None:
    """必填来源：无来源的创建/更新在 schema 层就不成立。"""
    tool = ToolRegistry.get_tool(tool_name)
    assert tool is not None
    assert "artifact_version_id" in tool.parameters["properties"]
    assert "artifact_version_id" in tool.parameters["required"], (
        f"{tool_name} 必须把 artifact_version_id 列为 required，否则模型可省略来源"
    )


def test_create_coding_plan_required_is_exactly_three_keys() -> None:
    tool = ToolRegistry.get_tool("create_coding_plan")
    assert tool is not None
    assert set(tool.parameters["required"]) == {
        "space_id",
        "conversation_id",
        "artifact_version_id",
    }


@pytest.mark.parametrize("tool_name", sorted(_ALLOWED_PROPERTIES))
def test_tool_properties_match_explicit_allowlist(tool_name: str) -> None:
    """枚举式相等断言：防「换个名字的正文入参」绕过上面两条具名否定断言。"""
    tool = ToolRegistry.get_tool(tool_name)
    assert tool is not None
    assert set(tool.parameters["properties"]) == _ALLOWED_PROPERTIES[tool_name], (
        f"{_REGRESSION_HINT}（{tool_name} 的入参集合与白名单不符；"
        f"新增入参须先在 _ALLOWED_PROPERTIES 显式登记）"
    )


@pytest.mark.parametrize("tool_name", sorted(_ALLOWED_PROPERTIES))
@pytest.mark.parametrize("param", _AUTHORING_PARAMS)
def test_authoring_param_absent_from_function_signature(tool_name: str, param: str) -> None:
    """schema 与函数签名两侧都要干净 —— 只改 schema 会留下可被直接调用的后门。"""
    tool = ToolRegistry.get_tool(tool_name)
    assert tool is not None
    sig = inspect.signature(inspect.unwrap(tool.func))
    assert param not in sig.parameters, f"{_REGRESSION_HINT}（{tool_name} 函数签名含 {param}）"

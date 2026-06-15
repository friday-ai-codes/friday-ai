"""PF-02 verify_plan execution_plan 校验测试（implementation contract）。

覆盖 ``agents.tools.verify_plan.verify_plan`` 对齐到 canonical ``execution_plan``
schema（``technical_plan.py`` + DOMAIN §7 MergedPlan.execution_plan）后的：

- 合法方案 → valid=True, errors=[]
- 缺 title / 缺或空 execution_plan → 对应 field 错误
- execution_plan[i] 非对象 / 缺 repository_id / 缺 coding_instruction → 对应 field 错误
- 工具契约形状恒为 {valid, errors, warnings, summary}，success 恒 True
"""

from __future__ import annotations

from typing import Any

import pytest

from agents.tools.verify_plan import verify_plan


def _valid_plan() -> dict[str, Any]:
    return {
        "title": "支持多仓库方案编排",
        "execution_plan": [
            {
                "repository_id": "r1",
                "coding_instruction": "在 server 端实现编排 engine 骨架并补齐守护测试。",
            }
        ],
    }


@pytest.mark.asyncio
async def test_valid_plan_passes() -> None:
    result = await verify_plan(_valid_plan())
    assert result.success is True
    assert result.output["valid"] is True
    assert result.output["errors"] == []


@pytest.mark.asyncio
async def test_contract_shape_stable() -> None:
    """工具自身恒 success=True，output 形状恒为 {valid, errors, warnings, summary}。"""
    result = await verify_plan({})
    assert result.success is True
    assert set(result.output.keys()) == {"valid", "errors", "warnings", "summary"}


@pytest.mark.asyncio
async def test_missing_title() -> None:
    plan = _valid_plan()
    del plan["title"]
    result = await verify_plan(plan)
    assert result.output["valid"] is False
    assert any(e["field"] == "title" for e in result.output["errors"])


@pytest.mark.asyncio
async def test_missing_execution_plan() -> None:
    plan = {"title": "有效标题但缺 execution_plan"}
    result = await verify_plan(plan)
    assert result.output["valid"] is False
    assert any(e["field"] == "execution_plan" for e in result.output["errors"])


@pytest.mark.asyncio
async def test_empty_execution_plan() -> None:
    plan = {"title": "有效标题", "execution_plan": []}
    result = await verify_plan(plan)
    assert result.output["valid"] is False
    assert any(e["field"] == "execution_plan" for e in result.output["errors"])


@pytest.mark.asyncio
async def test_execution_plan_item_not_object() -> None:
    plan = {"title": "有效标题", "execution_plan": ["not-a-dict"]}
    result = await verify_plan(plan)
    assert result.output["valid"] is False
    assert any(e["field"] == "execution_plan[0]" for e in result.output["errors"])


@pytest.mark.asyncio
async def test_execution_plan_item_missing_repository_id() -> None:
    plan = {
        "title": "有效标题",
        "execution_plan": [{"coding_instruction": "足够长的编码指令内容用于通过校验。"}],
    }
    result = await verify_plan(plan)
    assert result.output["valid"] is False
    assert any(
        e["field"] == "execution_plan[0].repository_id" for e in result.output["errors"]
    )


@pytest.mark.asyncio
async def test_execution_plan_item_missing_coding_instruction() -> None:
    plan = {
        "title": "有效标题",
        "execution_plan": [{"repository_id": "r1"}],
    }
    result = await verify_plan(plan)
    assert result.output["valid"] is False
    assert any(
        e["field"] == "execution_plan[0].coding_instruction"
        for e in result.output["errors"]
    )


@pytest.mark.asyncio
async def test_warnings_do_not_block() -> None:
    """校验通过时可有 warnings（不阻断 valid）。"""
    plan = {
        "title": "短",  # < 5 字符 → warning
        "execution_plan": [
            {"repository_id": "r1", "coding_instruction": "够长的编码指令内容描述。"}
        ],
    }
    result = await verify_plan(plan)
    assert result.output["valid"] is True
    assert len(result.output["warnings"]) >= 1

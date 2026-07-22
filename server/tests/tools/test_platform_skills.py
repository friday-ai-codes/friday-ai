"""平台 Skill 步级 trace + 种子端到端测试（LOOP-04 / 101-04，ROADMAP 成功标准 4）。

- 步级 trace：run 可用时每步产 ToolCallRecord（tool_name 带 ``#i:step`` 前缀）；
- 顶层输入透传：skill 顶层 arguments 合并进每步（步内静态优先）；
- 首败中断：某步 ok=False → 后续步骤不执行，只留已执行步骤的记录；
- run=None 路径（内部调用）：不写步级 ledger、不抛；
- 端到端：PAT 调 /api/tools/execute/ 执行 ``pre_coding_research``（4 步 handler
  全 patch 桩）→ 200 且 result 为 4 步结果列表。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from rest_framework.test import APIClient

from interactions.models import InteractionRun, ToolCallRecord
from tools.models import RemoteTool
from tools.sources.skill import execute_skill

pytestmark = pytest.mark.django_db(transaction=True)

# 桩 handler 收到的 kwargs（模块级，供 dotted-path import + 断言）。
_received_calls: list[dict[str, Any]] = []


async def _stub_step_ok(**kwargs: Any) -> str:
    """步骤工具桩：记录收到的参数并回显 JSON。"""
    _received_calls.append(kwargs)
    return json.dumps({"echo": sorted(kwargs.keys())}, ensure_ascii=False)


async def _stub_step_boom(**kwargs: Any) -> str:
    _received_calls.append(kwargs)
    raise RuntimeError("step exploded")


@pytest.fixture(autouse=True)
def _reset_received() -> None:
    _received_calls.clear()


async def _make_step_tool(name: str, handler_fn: str) -> RemoteTool:
    return await RemoteTool.objects.acreate(
        name=name,
        description="test step tool",
        source="builtin",
        input_schema={"type": "object", "properties": {}},
        timeout=10,
        is_active=True,
        config={"handler": f"tests.tools.test_platform_skills.{handler_fn}"},
    )


async def _make_skill(name: str, step_names: list[str]) -> RemoteTool:
    return await RemoteTool.objects.acreate(
        name=name,
        description="test skill",
        source="skill",
        input_schema={"type": "object", "properties": {}},
        timeout=60,
        is_active=True,
        config={"steps": [{"tool_name": s, "arguments": {}} for s in step_names]},
    )


# ---------------------------------------------------------------------------
# 步级 trace + 顶层透传
# ---------------------------------------------------------------------------


async def test_step_level_tool_call_records_and_passthrough() -> None:
    """run 非 None：每步一条 ToolCallRecord、tool_name 带 #i: 前缀、顶层透传生效。"""
    await _make_step_tool("t-step-a", "_stub_step_ok")
    await _make_step_tool("t-step-b", "_stub_step_ok")
    skill = await _make_skill("t-skill", ["t-step-a", "t-step-b"])
    run = await InteractionRun.objects.acreate(source="tool")

    results = await execute_skill(skill, {"query": "q"}, run=run)

    assert len(results) == 2
    assert all(r["ok"] for r in results)
    # 顶层透传：两个桩都收到了 query。
    assert [c.get("query") for c in _received_calls] == ["q", "q"]

    records = [r async for r in ToolCallRecord.objects.filter(run=run).order_by("created_at")]
    assert len(records) == 2
    assert records[0].tool_name == "t-skill#0:t-step-a"
    assert records[1].tool_name == "t-skill#1:t-step-b"
    assert records[0].status == "ok"
    assert records[0].input.get("query") == "q"


async def test_step_static_arguments_take_precedence() -> None:
    """步内静态 arguments 优先于顶层透传（{**arguments, **step_args}）。"""
    await _make_step_tool("t-step-static", "_stub_step_ok")
    skill = await RemoteTool.objects.acreate(
        name="t-skill-static",
        description="test skill",
        source="skill",
        input_schema={"type": "object", "properties": {}},
        timeout=60,
        is_active=True,
        config={"steps": [{"tool_name": "t-step-static", "arguments": {"query": "static"}}]},
    )

    results = await execute_skill(skill, {"query": "top", "extra": "e"})

    assert len(results) == 1
    assert _received_calls[0]["query"] == "static"  # 静态优先
    assert _received_calls[0]["extra"] == "e"  # 顶层键仍透传


async def test_first_failure_aborts_with_single_record() -> None:
    """首败中断：第 1 步失败 → results 长度 1 + 只 1 条步级记录。"""
    await _make_step_tool("t-step-boom", "_stub_step_boom")
    await _make_step_tool("t-step-never", "_stub_step_ok")
    skill = await _make_skill("t-skill-fail", ["t-step-boom", "t-step-never"])
    run = await InteractionRun.objects.acreate(source="tool")

    results = await execute_skill(skill, {"query": "q"}, run=run)

    assert len(results) == 1
    assert results[0]["ok"] is False
    records = [r async for r in ToolCallRecord.objects.filter(run=run)]
    assert len(records) == 1
    assert records[0].tool_name == "t-skill-fail#0:t-step-boom"
    assert records[0].status == "error"
    # 第 2 步从未执行。
    assert len(_received_calls) == 1


async def test_run_none_path_no_ledger_no_raise() -> None:
    """run=None（内部调用）：不写步级 ledger、正常返回不抛。"""
    await _make_step_tool("t-step-noledger", "_stub_step_ok")
    skill = await _make_skill("t-skill-noledger", ["t-step-noledger"])

    results = await execute_skill(skill, {"query": "q"})

    assert len(results) == 1
    assert results[0]["ok"] is True
    assert await ToolCallRecord.objects.acount() == 0


# ---------------------------------------------------------------------------
# 端到端：/api/tools/execute/ 调种子 skill
# ---------------------------------------------------------------------------

_HANDLER_BASE = "tools.handlers.skill_steps"
_PRE_CODING_STEPS = [
    "route_repositories",
    "search_rag_chunks",
    "search_delivery_knowledge",
    "search_learning_cases",
]


@pytest.fixture()
def _reseed_platform_skills(db: Any) -> None:
    """transaction=True 用例 flush 会清掉 migration 种子——幂等重播 0005 种子。"""
    import importlib

    from django.apps import apps

    mod = importlib.import_module("tools.migrations.0005_seed_platform_skills")
    mod.seed_platform_skills(apps, None)


def test_execute_endpoint_runs_pre_coding_research(
    make_access_token: Any, _reseed_platform_skills: None
) -> None:
    """PAT 调 /api/tools/execute/ 执行 pre_coding_research → 200 + 4 步结果列表。"""
    _token, plaintext = make_access_token(name="skill-e2e-token")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    stub = AsyncMock(return_value=json.dumps({"stub": True}, ensure_ascii=False))
    with (
        patch(f"{_HANDLER_BASE}.route_repositories", new=stub),
        patch(f"{_HANDLER_BASE}.search_rag_chunks", new=stub),
        patch(f"{_HANDLER_BASE}.search_delivery_knowledge", new=stub),
        patch(f"{_HANDLER_BASE}.search_learning_cases", new=stub),
    ):
        response = client.post(
            "/api/tools/execute/",
            {"name": "pre_coding_research", "arguments": {"query": "登录改造"}},
            format="json",
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert isinstance(body["result"], list)
    assert len(body["result"]) == 4
    assert all(step["ok"] for step in body["result"])
    # 顶层透传：每步桩都收到了 query。
    assert stub.await_count == 4
    for call in stub.await_args_list:
        assert call.kwargs.get("query") == "登录改造"

    # 步级 ledger：顶层 run 下 4 条步级记录 + 1 条顶层记录（views.py 既有审计）。
    run = InteractionRun.objects.order_by("-created_at").first()
    assert run is not None
    step_records = ToolCallRecord.objects.filter(run=run, tool_name__contains="#")
    assert step_records.count() == 4
    names = sorted(r.tool_name for r in step_records)
    assert names == [f"pre_coding_research#{i}:{s}" for i, s in enumerate(_PRE_CODING_STEPS)]

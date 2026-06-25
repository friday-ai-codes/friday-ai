"""FeishuEventHandler 专属端点 token 路由契约测试。

验证 per-workflow 专属端点模式：
- `metadata["trigger_token"]` 命中活跃 trigger → 直接返回其工作流（不做 event_type/filter 匹配）；
- 未知 / 已停用 token → 返回空；
- token 模式下 validate 不再强制要求 event_type。
"""

import pytest

from projects.models import Space
from workflows.models import Workflow, WorkflowTrigger
from workflows.triggers.context import TriggerContext
from workflows.triggers.handlers.feishu import FeishuEventHandler

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


async def _make_workflow(name: str = "Token Route WF", is_active: bool = True) -> Workflow:
    project = await Space.objects.acreate(name=f"{name} Space")
    return await Workflow.objects.acreate(name=name, space=project, trigger_type="event")


async def test_token_routes_directly_to_workflow():
    """trigger_token 命中活跃 trigger → 直达其工作流，忽略 event_type/filter。"""
    workflow = await _make_workflow()
    trigger = await WorkflowTrigger.objects.acreate(workflow=workflow, is_active=True)

    handler = FeishuEventHandler()
    context = TriggerContext(
        trigger_type="feishu",
        raw_payload={"id": "1"},
        event_type="WorkitemStatusEvent",
        space=workflow.space,
        metadata={"trigger_token": trigger.token},
    )

    workflows = await handler.find_workflows(context)
    assert [w.id for w in workflows] == [workflow.id]


async def test_unknown_token_returns_empty():
    """未知 token → 返回空。"""
    handler = FeishuEventHandler()
    context = TriggerContext(
        trigger_type="feishu",
        raw_payload={},
        metadata={"trigger_token": "nonexistent-token"},
    )
    assert await handler.find_workflows(context) == []


async def test_inactive_trigger_token_returns_empty():
    """已停用 trigger 的 token → 返回空。"""
    workflow = await _make_workflow("Inactive Trigger WF")
    trigger = await WorkflowTrigger.objects.acreate(workflow=workflow, is_active=False)

    handler = FeishuEventHandler()
    context = TriggerContext(
        trigger_type="feishu",
        raw_payload={},
        space=workflow.space,
        metadata={"trigger_token": trigger.token},
    )
    assert await handler.find_workflows(context) == []


async def test_validate_token_mode_skips_event_type_requirement():
    """token 模式下 validate 不要求 event_type（飞书侧已决定触发时机）。"""
    workflow = await _make_workflow("Validate Token WF")
    trigger = await WorkflowTrigger.objects.acreate(workflow=workflow, is_active=True)

    handler = FeishuEventHandler()
    context = TriggerContext(
        trigger_type="feishu",
        raw_payload={},
        event_type="",  # 无事件类型
        space=workflow.space,
        metadata={"trigger_token": trigger.token},
    )
    errors = await handler.validate(context)
    assert errors == []

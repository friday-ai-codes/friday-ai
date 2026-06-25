"""chat CodingPlan 创建入口 eager 投影守护测试（PLAN-03，DOMAIN §5.3）。

经 chat 创建入口（``create_coding_plan`` @tool）建 CodingPlan → 自动 eager 投影
canonical + 回填 canonical_plan_id；投影失败（best-effort）不阻断 CodingPlan 创建。
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from delivery.models import TechnicalPlan, TechnicalPlanOrigin


@pytest.fixture
def conversation(project):
    from chat.models import Conversation

    return Conversation.objects.create(space=project, title="eager 投影测试对话")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_chat_create_entry_eager_projects_canonical(project, conversation) -> None:
    from agents.tools.coding_tools import create_coding_plan
    from chat.models import CodingPlan

    result = await create_coding_plan(
        space_id=str(project.id),
        conversation_id=str(conversation.id),
        tech_plan="## 技术方案\n- 改 main.py",
        affected_files=[{"path": "src/main.py", "change_type": "modify"}],
    )
    assert result.success is True
    plan_id = result.output["coding_plan_id"]

    reloaded = await CodingPlan.objects.aget(id=plan_id)
    assert reloaded.canonical_plan_id is not None

    canonical = await TechnicalPlan.objects.aget(id=reloaded.canonical_plan_id)
    assert canonical.origin == TechnicalPlanOrigin.CHAT
    assert canonical.work_item_id is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_eager_projection_best_effort_does_not_block(
    project, conversation, monkeypatch
) -> None:
    """投影抛错 → CodingPlan 仍创建成功（best-effort 守护，不阻断）。"""
    from agents.tools.coding_tools import create_coding_plan
    from chat.models import CodingPlan
    from delivery.services import TechnicalPlanService

    async def _boom(self, *args, **kwargs):
        raise RuntimeError("projection boom")

    monkeypatch.setattr(TechnicalPlanService, "create_from", _boom)

    result = await create_coding_plan(
        space_id=str(project.id),
        conversation_id=str(conversation.id),
        tech_plan="## 技术方案\n- 改 utils.py",
        affected_files=[{"path": "src/utils.py", "change_type": "modify"}],
    )
    assert result.success is True
    plan_id = result.output["coding_plan_id"]

    reloaded = await CodingPlan.objects.aget(id=plan_id)
    # 投影失败 → 软链未回填，但 CodingPlan 正常创建
    assert reloaded.canonical_plan_id is None
    count = await sync_to_async(TechnicalPlan.objects.count)()
    assert count == 0

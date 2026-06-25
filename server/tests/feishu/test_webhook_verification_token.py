"""飞书事件触发「节点专属校验 token」契约测试。

覆盖：
- `_get_node_verification_token` 读取节点 config.verification_token；无节点/无字段 → 空。
- 专属端点模式下，header.token 与节点 verification_token 不匹配 → 401 拒绝触发。
- 节点未配置 verification_token（旧节点）→ 跳过校验，不返回 401（向后兼容）。
"""

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from projects.models import Space
from workflows.models import Workflow, WorkflowNode, WorkflowTrigger


@pytest.fixture
def api_client():
    return APIClient()


def _make_trigger(verification_token: str = "") -> WorkflowTrigger:
    """创建 active 工作流 + feishu_event_trigger 节点（可带校验 token）+ 专属端点 trigger。"""
    project = Space.objects.create(name="VT Space")
    wf = Workflow.objects.create(
        name="VT WF", space=project, is_active=True, trigger_type="event",
    )
    node = WorkflowNode.objects.create(
        workflow=wf,
        node_type="feishu_event_trigger",
        name="飞书事件触发",
        config={"verification_token": verification_token} if verification_token else {},
    )
    return WorkflowTrigger.objects.create(
        workflow=wf,
        node_id=node.id,
        is_active=True,
        token="endpoint-tok-aaaaaaaaaaaaaaaa",
    )


# ===== 静态 helper：_get_node_verification_token =====


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_node_verification_token_reads_config():
    from asgiref.sync import sync_to_async

    from feishu.views import FeishuWebhookView

    trigger = await sync_to_async(_make_trigger)("secret-vtok-bbbbbbbbbbbb")
    trigger = await WorkflowTrigger.objects.aget(id=trigger.id)
    token = await FeishuWebhookView._get_node_verification_token(trigger)
    assert token == "secret-vtok-bbbbbbbbbbbb"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_get_node_verification_token_empty_when_unset():
    from asgiref.sync import sync_to_async

    from feishu.views import FeishuWebhookView

    trigger = await sync_to_async(_make_trigger)("")  # 节点无 verification_token
    trigger = await WorkflowTrigger.objects.aget(id=trigger.id)
    token = await FeishuWebhookView._get_node_verification_token(trigger)
    assert token == ""


# ===== Webhook 端到端：校验 token 不匹配拒绝 / 无配置跳过 =====


@pytest.mark.django_db
def test_webhook_rejects_mismatched_verification_token(api_client):
    trigger = _make_trigger("right-vtok-cccccccccccc")
    resp = api_client.post(
        f"/api/feishu/webhook/{trigger.token}/",
        data={
            "header": {
                "event_type": "WorkitemStatusEvent",
                "uuid": "evt-mismatch-1",
                "token": "WRONG-TOKEN",
            },
            "payload": {"id": 1, "project_key": "pk"},
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_webhook_skips_when_no_verification_token(api_client):
    trigger = _make_trigger("")  # 旧节点：未配置校验 token
    resp = api_client.post(
        f"/api/feishu/webhook/{trigger.token}/",
        data={
            "header": {
                "event_type": "PingEvent",
                "uuid": "evt-skip-1",
                "token": "anything",
            },
            "payload": {"id": 1, "project_key": "pk"},
        },
        format="json",
    )
    # 未配置校验 token → 不因 token 被拒（不返回 401）
    assert resp.status_code != status.HTTP_401_UNAUTHORIZED

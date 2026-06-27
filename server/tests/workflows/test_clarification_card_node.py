"""ClarificationCardNode 节点单测（SLOT-02，92-03 Task 1）。

覆盖（mirror test_plan_research_node / test_chat_question 范式，IO 边界 mock）：
- Test 1 注册：NodeRegistry.get("clarification_card") 非空 + get_schema 端口 shape 契约暴露。
- Test 2 发卡 + 挂起（有 clarification_id）：真实轮（2 子题）→ 取轮按 order → 发卡 →
  建 ClarifyCardCallback 订阅 → waiting_event。
- Test 3 raw questions 透传（无 clarification_id）：用 raw questions 渲染卡、waiting_event、persisted=False。
- Test 4 发卡失败 best-effort：send 抛异常 → 仍 waiting_event、card_sent=False（不反噬挂起）。
- Test 5 缺内容：缺 chat_id 且缺 questions/clarification_id → failed + next_handle="error"。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflows.nodes.base import ExecutionContext, NodeCategory
from workflows.nodes.registry import NodeRegistry

_MOD = "workflows.nodes.integrations.clarification_card"


def _ctx(
    *,
    request_payload: dict | None,
    config: dict | None = None,
    with_execution: bool = False,
) -> ExecutionContext:
    workflow_execution = None
    node_execution = None
    if with_execution:
        workflow_execution = MagicMock()
        workflow_execution.id = uuid.uuid4()
        workflow_execution.triggered_by_id = None
        node_execution = MagicMock()
        node_execution.id = uuid.uuid4()
    return ExecutionContext(
        execution_id="exec-cc-001",
        node_id="node-cc-001",
        node_config=config or {},
        input_data={"clarification_request": request_payload}
        if request_payload is not None
        else {},
        workflow_context={},
        previous_outputs={},
        workflow_execution=workflow_execution,
        node_execution=node_execution,
    )


# ---------------------------------------------------------------------------
# Test 1：注册 + get_schema 端口 shape 契约
# ---------------------------------------------------------------------------


def test_registration_and_schema_shapes() -> None:
    node_cls = NodeRegistry.get("clarification_card")
    assert node_cls is not None

    schema = node_cls.get_schema()
    assert schema["category"] == NodeCategory.INTEGRATION.value
    assert schema["is_blocking"] is True

    inputs = {p["name"]: p for p in schema["inputs"]}
    outputs = {p["name"]: p for p in schema["outputs"]}
    assert inputs["clarification_request"]["shape"] == "clarification_request"
    assert outputs["clarification_answer"]["shape"] == "clarification_answer"
    assert outputs["feishu_message"]["shape"] == "feishu_message"


# ---------------------------------------------------------------------------
# Test 2：有 clarification_id → 取轮发卡 + 订阅 + waiting_event
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_persisted_round_sends_card_and_suspends() -> None:
    from delivery.models import PlanSession, PlanSessionStatus
    from delivery.services.clarification_service import ClarificationService
    from workflows.nodes.integrations.clarification_card import ClarificationCardNode

    session = await PlanSession.objects.acreate(
        entrypoint="workflow",
        status=PlanSessionStatus.CLARIFYING,
        decomposition={"requirement_text": "需求"},
    )
    clar = await ClarificationService().create_round(
        session,
        [
            {
                "question": "实验组用户？",
                "type": "single",
                "options": ["A", "B"],
                "recommended": ["A"],
            },
            {"question": "命中策略？", "type": "multi", "options": ["X", "Y"], "recommended": []},
        ],
    )
    assert clar is not None

    ctx = _ctx(
        request_payload={"clarification_id": str(clar.id), "chat_id": "oc_chat"},
        with_execution=True,
    )

    im_client = MagicMock()
    im_client.send_card = AsyncMock(return_value="msg-1")
    sub_mgr = MagicMock()
    sub_mgr.objects.acreate = AsyncMock()

    with (
        patch(f"{_MOD}._get_feishu_credentials", AsyncMock(return_value=("app", "secret"))),
        patch(f"{_MOD}.FeishuIMClient", return_value=im_client),
        patch(f"{_MOD}.WorkflowEventSubscription", sub_mgr),
        patch(f"{_MOD}.build_clarification_card", return_value={"card": "x"}) as mock_card,
    ):
        result = await ClarificationCardNode().execute(ctx)

    assert result.status == "waiting_event"
    assert result.output["clarification_id"] == str(clar.id)
    assert result.output["chat_id"] == "oc_chat"
    assert result.output["question_count"] == 2
    assert result.output["persisted"] is True
    assert result.output["card_sent"] is True
    # 发卡传 action 前缀隔离 91
    assert mock_card.call_args.kwargs["action"] == "clarify_card_answer"
    assert mock_card.call_args.kwargs["clarification_id"] == str(clar.id)
    # 订阅事件键
    sub_mgr.objects.acreate.assert_awaited_once()
    assert sub_mgr.objects.acreate.await_args.kwargs["event_type"] == "ClarifyCardCallback"
    # questions_meta 按 order
    meta = result.output["questions_meta"]
    assert [m["order"] for m in meta] == [0, 1]


# ---------------------------------------------------------------------------
# Test 3：无 clarification_id → raw questions 透传 + waiting_event（persisted=False）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raw_questions_transient_suspends() -> None:
    from workflows.nodes.integrations.clarification_card import ClarificationCardNode

    ctx = _ctx(
        request_payload={
            "questions": [
                {"question": "Q1", "type": "single", "options": ["A"]},
                {"question": "Q2", "type": "single", "options": ["B"]},
            ],
            "chat_id": "oc_chat",
        },
    )

    im_client = MagicMock()
    im_client.send_card = AsyncMock(return_value="msg-1")

    with (
        patch(f"{_MOD}._get_feishu_credentials", AsyncMock(return_value=("app", "secret"))),
        patch(f"{_MOD}.FeishuIMClient", return_value=im_client),
        patch(f"{_MOD}.build_clarification_card", return_value={"card": "x"}),
    ):
        result = await ClarificationCardNode().execute(ctx)

    assert result.status == "waiting_event"
    assert result.output["persisted"] is False
    assert result.output["question_count"] == 2
    assert len(result.output["questions_meta"]) == 2


# ---------------------------------------------------------------------------
# Test 3b：发卡问题正文脱敏（WR-01，与镜像 ai_plan_research 发卡脱敏一致）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_card_question_text_is_redacted() -> None:
    from workflows.nodes.integrations.clarification_card import ClarificationCardNode

    secret = "sk-ant-abcdefghijklmnopqrstuvwxyz0123456789"
    ctx = _ctx(
        request_payload={
            "questions": [
                {"question": f"用哪个密钥？{secret}", "type": "single", "options": ["A"]},
            ],
            "chat_id": "oc_chat",
        },
    )

    im_client = MagicMock()
    im_client.send_card = AsyncMock(return_value="msg-1")

    with (
        patch(f"{_MOD}._get_feishu_credentials", AsyncMock(return_value=("app", "secret"))),
        patch(f"{_MOD}.FeishuIMClient", return_value=im_client),
        patch(f"{_MOD}.build_clarification_card", return_value={"card": "x"}) as mock_card,
    ):
        result = await ClarificationCardNode().execute(ctx)

    assert result.status == "waiting_event"
    card_questions = mock_card.call_args.args[0]
    question_text = card_questions[0]["question"]
    assert secret not in question_text
    assert "***REDACTED***" in question_text


# ---------------------------------------------------------------------------
# Test 4：发卡失败 best-effort → 仍 waiting_event、card_sent=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_card_send_failure_still_suspends() -> None:
    from workflows.nodes.integrations.clarification_card import ClarificationCardNode

    ctx = _ctx(
        request_payload={
            "questions": [{"question": "Q1", "type": "single", "options": ["A"]}],
            "chat_id": "oc_chat",
        },
    )

    with (
        patch(f"{_MOD}._get_feishu_credentials", AsyncMock(side_effect=RuntimeError("no creds"))),
        patch(f"{_MOD}.build_clarification_card", return_value={"card": "x"}),
    ):
        result = await ClarificationCardNode().execute(ctx)

    assert result.status == "waiting_event"
    assert result.output["card_sent"] is False


# ---------------------------------------------------------------------------
# Test 5：缺内容 → failed + next_handle="error"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_content_fails_to_error() -> None:
    from workflows.nodes.integrations.clarification_card import ClarificationCardNode

    # 缺 chat_id 且缺 questions/clarification_id
    ctx = _ctx(request_payload={})
    result = await ClarificationCardNode().execute(ctx)
    assert result.status == "failed"
    assert result.next_handle == "error"

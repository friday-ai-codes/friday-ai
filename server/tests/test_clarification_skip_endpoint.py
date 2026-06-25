"""``POST /api/chat/conversations/<id>/clarification/skip/`` endpoint 测试。

跳过是「等待澄清」卡死态的兜底出口（卡片漏发 / 用户不想答），按 conversation
维度定位等待中的 run，不依赖前端持有 clarification_id。覆盖：

- 无等待 run → 200 {"status": "no_pending"}（幂等，不误触 resume）
- 有 trace 的正常跳过 → 200 skipped + trace.answered_at 写入 +
  Message(role=user, kind=clarification_skip) + resume 以 skip payload 触发
- 无 trace 的退化态（waiting_clarification_without_clarification_id）→ 仍可跳过
- 孤儿态 ``status=running, phase=waiting_clarification`` → 仍可跳过（回归保护：
  dev reload / SSE 异常断开后台 finalizer 被回收导致 run 停在 running）
- 跨 user 越权 → 404 隐藏存在性
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from chat.models import Conversation, ConversationIntentTrace, Message
from orchestration.models import OrchestrationRun


@pytest.fixture
def conversation(project, user) -> Conversation:
    return Conversation.objects.create(
        space=project,
        title="跳过澄清测试",
        created_by=user,
        status=Conversation.Status.RUNNING,
    )


def _make_waiting_run(
    conversation: Conversation,
    *,
    status: str = OrchestrationRun.Status.WAITING,
) -> OrchestrationRun:
    return OrchestrationRun.objects.create(
        conversation=conversation,
        thread_id=str(conversation.id),
        status=status,
        phase=OrchestrationRun.Phase.WAITING_CLARIFICATION,
    )


def _make_trace(conversation: Conversation) -> ConversationIntentTrace:
    return ConversationIntentTrace.objects.create(
        conversation=conversation,
        clarification_id=uuid.uuid4().hex,
        question="想改哪个仓库？",
        options=[{"id": "opt-A", "label": "后端"}],
    )


@pytest.fixture
def authed_client(api_client: APIClient, user, project_memberships) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


def _url(conversation_id: Any) -> str:
    return f"/api/chat/conversations/{conversation_id}/clarification/skip/"


@pytest.fixture(autouse=True)
def _mock_resume_graph(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """打桩 resume_clarification_run 避免真起 graph，只捕获触发参数。"""
    captured: dict[str, Any] = {"resume_calls": []}

    async def _fake_resume(
        conversation_id: str, resume_payload: dict[str, Any],
    ) -> None:
        captured["resume_calls"].append({
            "conversation_id": conversation_id,
            "resume_payload": resume_payload,
        })

    monkeypatch.setattr(
        "chat.conversation_service.ConversationService.resume_clarification_run",
        staticmethod(_fake_resume),
    )
    return captured


@pytest.mark.django_db(transaction=True)
class TestClarificationSkipEndpoint:
    def test_no_pending_when_no_waiting_run(
        self,
        authed_client: APIClient,
        conversation: Conversation,
    ) -> None:
        resp = authed_client.post(_url(conversation.id), data={}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["status"] == "no_pending"

    def test_skip_with_trace(
        self,
        authed_client: APIClient,
        conversation: Conversation,
    ) -> None:
        _make_waiting_run(conversation)
        trace = _make_trace(conversation)

        resp = authed_client.post(_url(conversation.id), data={}, format="json")
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["status"] == "skipped"
        assert body["clarification_id"] == trace.clarification_id

        trace.refresh_from_db()
        assert trace.answered_at is not None

        msg = Message.objects.filter(
            conversation=conversation,
            metadata__kind="clarification_skip",
        ).first()
        assert msg is not None
        assert msg.role == Message.Role.USER

    def test_skip_triggers_resume_with_skip_payload(
        self,
        authed_client: APIClient,
        conversation: Conversation,
        _mock_resume_graph: dict[str, Any],
    ) -> None:
        _make_waiting_run(conversation)
        _make_trace(conversation)

        resp = authed_client.post(_url(conversation.id), data={}, format="json")
        assert resp.status_code == 200, resp.content

        calls = _mock_resume_graph["resume_calls"]
        assert len(calls) == 1
        payload = calls[0]["resume_payload"]
        assert payload["skipped"] is True
        # freeform_text 携带「跳过」指令，作为 resume 后的 user turn 让 LLM 直接作答
        assert payload["freeform_text"]
        assert payload["selected_option_id"] is None

    def test_skip_without_trace_degenerate(
        self,
        authed_client: APIClient,
        conversation: Conversation,
        _mock_resume_graph: dict[str, Any],
    ) -> None:
        """无 ConversationIntentTrace 的退化态：仍能跳过并 resume。"""
        _make_waiting_run(conversation)

        resp = authed_client.post(_url(conversation.id), data={}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["status"] == "skipped"
        assert len(_mock_resume_graph["resume_calls"]) == 1

    def test_skip_orphan_running_status(
        self,
        authed_client: APIClient,
        conversation: Conversation,
        _mock_resume_graph: dict[str, Any],
    ) -> None:
        """孤儿态 status=running（后台 finalizer 被回收）也必须能跳过。"""
        _make_waiting_run(conversation, status=OrchestrationRun.Status.RUNNING)

        resp = authed_client.post(_url(conversation.id), data={}, format="json")
        assert resp.status_code == 200, resp.content
        assert resp.json()["status"] == "skipped"
        assert len(_mock_resume_graph["resume_calls"]) == 1

    def test_cross_user_returns_404(
        self,
        api_client: APIClient,
        other_user,
        conversation: Conversation,
    ) -> None:
        _make_waiting_run(conversation)
        api_client.force_authenticate(user=other_user)
        resp = api_client.post(_url(conversation.id), data={}, format="json")
        assert resp.status_code == 404

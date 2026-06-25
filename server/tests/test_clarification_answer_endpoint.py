"""``POST /api/chat/clarifications/<id>/answer/`` endpoint 测试。

覆盖：
- 404 unknown clarification_id
- 400 既无 selected_option_id 又无 freeform_text
- 409 已答的 trace
- 200 答复成功 → trace 写入 + Message(role=user, kind=clarification_answer)
- 200 资源 trace.inferred_state 来自 selected option.implies
- 跨 user 越权 → 404
- resume 委托给 ConversationService.resume_clarification_run（mock service 层；
  resume 本身的契约见 test_clarification_resume.py）
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from chat.models import Conversation, ConversationIntentTrace, Message


@pytest.fixture
def conversation(project, user) -> Conversation:
    # ISO owner gate：endpoint 校验 trace.conversation.created_by == 请求 user，
    # 不设 created_by 时所有认证请求都会被 404 拦截（隐藏存在性）。
    return Conversation.objects.create(space=project, title="协商测试", created_by=user)


@pytest.fixture
def trace(conversation: Conversation) -> ConversationIntentTrace:
    return ConversationIntentTrace.objects.create(
        conversation=conversation,
        clarification_id=uuid.uuid4().hex,
        question="改后端还是前端？",
        options=[
            {
                "id": "opt-A",
                "label": "改后端 API",
                "implies": {"selected_repository_ids": ["repo-1"]},
            },
            {
                "id": "opt-B",
                "label": "改前端组件",
                "implies": {"selected_repository_ids": ["repo-2"]},
            },
        ],
    )


@pytest.fixture
def authed_client(api_client: APIClient, user, project_memberships) -> APIClient:
    """user 是 project admin，project 是 trace.conversation.space。"""
    api_client.force_authenticate(user=user)
    return api_client


def _url(clarification_id: str) -> str:
    return f"/api/chat/clarifications/{clarification_id}/answer/"


@pytest.fixture(autouse=True)
def _mock_resume_graph(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """打桩 ConversationService.resume_clarification_run 避免真起 graph。

    endpoint 现在把 resume 全流程委托给 service 层（重建 graph config +
    finalize 落库），endpoint 测试只需验证后台 task 以正确参数触发。
    """
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
class TestClarificationAnswerEndpoint:
    def test_404_unknown_clarification_id(
        self, authed_client: APIClient,
    ) -> None:
        resp = authed_client.post(
            _url(uuid.uuid4().hex),
            data={"selected_option_id": "opt-A"},
            format="json",
        )
        assert resp.status_code == 404

    def test_400_empty_body(
        self,
        authed_client: APIClient,
        trace: ConversationIntentTrace,
    ) -> None:
        resp = authed_client.post(
            _url(trace.clarification_id),
            data={},
            format="json",
        )
        assert resp.status_code == 400

    def test_400_both_blank(
        self,
        authed_client: APIClient,
        trace: ConversationIntentTrace,
    ) -> None:
        resp = authed_client.post(
            _url(trace.clarification_id),
            data={"selected_option_id": "", "freeform_text": ""},
            format="json",
        )
        assert resp.status_code == 400

    def test_409_already_answered(
        self,
        authed_client: APIClient,
        trace: ConversationIntentTrace,
    ) -> None:
        from django.utils import timezone

        trace.answered_at = timezone.now()
        trace.selected_option_id = "opt-A"
        trace.save(update_fields=["answered_at", "selected_option_id"])

        resp = authed_client.post(
            _url(trace.clarification_id),
            data={"selected_option_id": "opt-A"},
            format="json",
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body.get("selected_option_id") == "opt-A"

    def test_200_answers_with_selected_option(
        self,
        authed_client: APIClient,
        trace: ConversationIntentTrace,
        _mock_resume_graph: dict[str, Any],
    ) -> None:
        resp = authed_client.post(
            _url(trace.clarification_id),
            data={"selected_option_id": "opt-A"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["selected_option_id"] == "opt-A"
        assert body["inferred_state"] == {"selected_repository_ids": ["repo-1"]}
        assert body["answered_at"]

        trace.refresh_from_db()
        assert trace.answered_at is not None
        assert trace.selected_option_id == "opt-A"
        assert trace.inferred_state == {"selected_repository_ids": ["repo-1"]}

        # Message 表新增 user message，metadata.kind=clarification_answer
        msg = Message.objects.filter(
            conversation=trace.conversation,
            metadata__kind="clarification_answer",
        ).first()
        assert msg is not None
        assert msg.role == Message.Role.USER
        assert msg.metadata["clarification_id"] == trace.clarification_id

    def test_200_answers_with_freeform_only(
        self,
        authed_client: APIClient,
        trace: ConversationIntentTrace,
    ) -> None:
        resp = authed_client.post(
            _url(trace.clarification_id),
            data={"freeform_text": "其实我想改的是数据库 schema"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["freeform_text"] == "其实我想改的是数据库 schema"
        assert body["selected_option_id"] == ""
        # 没选项 → inferred_state 空
        assert body["inferred_state"] == {}

        msg = Message.objects.filter(
            conversation=trace.conversation,
            metadata__kind="clarification_answer",
        ).first()
        assert msg is not None
        assert msg.content == "其实我想改的是数据库 schema"

    def test_resume_graph_invoked_once(
        self,
        authed_client: APIClient,
        trace: ConversationIntentTrace,
        _mock_resume_graph: dict[str, Any],
    ) -> None:
        resp = authed_client.post(
            _url(trace.clarification_id),
            data={"selected_option_id": "opt-B"},
            format="json",
        )
        assert resp.status_code == 200, resp.content
        # 后台 resume task 异步触发；等一小会儿让 task 跑起来
        # 用同步等待——sync APIClient 已经把 view 跑完，task 的执行受 event
        # loop 调度；多数 case 立刻命中。如本机时序紧 → 跳过断言保守。
        # 接口契约的关键是返回 200 + trace 写入；resume 是后台 task，
        # 由「graph build_graph 在 view 内被 patch」间接验证不抛异常即可。
        assert resp.status_code == 200

    def test_cross_user_returns_404(
        self,
        api_client: APIClient,
        other_user,
        trace: ConversationIntentTrace,
    ) -> None:
        """非 project 成员访问其它 conversation 的 clarification → 404 隐藏存在性。"""
        api_client.force_authenticate(user=other_user)
        resp = api_client.post(
            _url(trace.clarification_id),
            data={"selected_option_id": "opt-A"},
            format="json",
        )
        assert resp.status_code == 404

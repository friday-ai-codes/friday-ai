"""会话端 plan 编排澄清专路由 + runtime 暴露测试（CLARIFY-04 / CLARIFY-06，91-04）。

物理隔离既有 chat 单题澄清（``clarifications/<id>/answer/``）——本套覆盖**新专路由**
``POST /api/chat/conversations/<id>/plan-clarification/answer/`` + runtime
``pending_plan_clarification`` 结构化轮暴露。

覆盖：
- runtime：会话关联 PlanSession 有 pending 结构化轮 → ``pending_plan_clarification.questions[]``
  （按 order、含 qtype/options/recommended/selected）；无 session / 已答 → None；chat 单题键零回归。
- endpoint：404 unknown conversation / 404 跨用户 / 404 跨项目 / 409 无 pending plan 澄清 /
  400 越界 question_id / 200 答复成功 → 同源 helper aanswer_round_and_resume 被调 + 返回
  {clarification_id, answered: true}。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from rest_framework.test import APIClient

from chat.conversation_service import ConversationService
from chat.models import Conversation
from delivery.models import PlanSession, PlanSessionEntrypoint, PlanSessionStatus
from delivery.services import ClarificationService

pytestmark = pytest.mark.django_db(transaction=True)


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def conversation(project, user) -> Conversation:
    # owner gate：endpoint 校验 conversation.created_by == 请求 user。
    return Conversation.objects.create(space=project, title="plan 澄清测试", created_by=user)


@pytest.fixture
def authed_client(api_client: APIClient, user, project_memberships) -> APIClient:
    api_client.force_authenticate(user=user)
    return api_client


def _make_plan_session(conversation: Conversation) -> PlanSession:
    return PlanSession.objects.create(
        entrypoint=PlanSessionEntrypoint.CHAT,
        status=PlanSessionStatus.CLARIFYING,
        conversation_id=conversation.id,
    )


def _make_pending_round(session: PlanSession):
    """经 ClarificationService（INV-6 唯一写入入口）建结构化 pending 轮 + 2 子题。"""
    return async_to_sync(ClarificationService().create_round)(
        session,
        [
            {
                "question": "改后端还是前端？",
                "type": "single",
                "options": ["后端", "前端"],
                "recommended": ["后端"],
            },
            {
                "question": "涉及哪些模块？",
                "type": "multi",
                "options": ["auth", "billing"],
                "recommended": ["auth"],
            },
        ],
        round_no=1,
    )


def _url(conversation_id: Any) -> str:
    return f"/api/chat/conversations/{conversation_id}/plan-clarification/answer/"


# ── Task 1: runtime 暴露 pending_plan_clarification ───────────────────────────


class TestRuntimePendingPlanClarification:
    def test_runtime_exposes_structured_round(self, conversation: Conversation) -> None:
        session = _make_plan_session(conversation)
        _make_pending_round(session)

        runtime = async_to_sync(ConversationService.get_conversation_runtime)(
            str(conversation.id),
        )

        ppc = runtime["pending_plan_clarification"]
        assert ppc is not None
        assert ppc["round_no"] == 1
        questions = ppc["questions"]
        assert len(questions) == 2
        # 按 order
        assert questions[0]["question"] == "改后端还是前端？"
        assert questions[0]["qtype"] == "single"
        assert questions[0]["options"] == ["后端", "前端"]
        assert questions[0]["recommended"] == ["后端"]
        assert questions[0]["selected"] is None
        assert questions[1]["qtype"] == "multi"

    def test_runtime_none_when_no_plan_session(
        self,
        conversation: Conversation,
    ) -> None:
        runtime = async_to_sync(ConversationService.get_conversation_runtime)(
            str(conversation.id),
        )
        assert runtime["pending_plan_clarification"] is None
        # chat 单题澄清键零回归
        assert runtime["pending_clarification"] is None

    def test_runtime_none_when_round_answered(
        self,
        conversation: Conversation,
    ) -> None:
        session = _make_plan_session(conversation)
        clar = _make_pending_round(session)
        # 全部子题作答 → 轮关闭，不应再暴露
        from delivery.models import ClarificationQuestion

        qids = list(
            ClarificationQuestion.objects.filter(clarification_id=clar.id).values_list(
                "id", flat=True
            )
        )
        async_to_sync(ClarificationService().answer_round)(
            clar.id,
            [
                {"question_id": str(qids[0]), "selected": "后端"},
                {"question_id": str(qids[1]), "selected": ["auth"]},
            ],
        )

        runtime = async_to_sync(ConversationService.get_conversation_runtime)(
            str(conversation.id),
        )
        assert runtime["pending_plan_clarification"] is None


# ── Task 2: plan 澄清专路由 endpoint ──────────────────────────────────────────


@pytest.fixture
def capture_helper(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """mock 同源 helper aanswer_round_and_resume（避免真起 engine），记录调用。"""
    captured: dict[str, Any] = {"calls": []}

    async def _fake(clarification_or_id: Any, answers: list[dict[str, Any]], **kw: Any):
        captured["calls"].append({"clarification_or_id": clarification_or_id, "answers": answers})
        return None

    monkeypatch.setattr(
        "services.plan_orchestration.aanswer_round_and_resume",
        _fake,
    )
    return captured


@pytest.fixture
def run_bg_inline(monkeypatch: pytest.MonkeyPatch):
    """让 view 的 fire-and-forget create_task 同步驱动跑完（helper 已 mock 无真实 await）。

    view 设计为后台 task + 干净 contextvars 启动；在 async_to_sync 测试上下文里后台
    task 通常不会在响应返回前跑完，故这里把 ``asyncio.create_task`` 替成同步 step 驱动，
    使被 mock 的 helper 调用可被确定性断言。
    """

    def _inline(coro, *args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            while True:
                coro.send(None)
        except StopIteration:
            pass
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    monkeypatch.setattr(asyncio, "create_task", _inline)
    return _inline


class TestPlanClarificationAnswerEndpoint:
    def test_404_unknown_conversation(self, authed_client: APIClient) -> None:
        resp = authed_client.post(
            _url(uuid.uuid4()),
            data={"answers": [{"question_id": uuid.uuid4().hex, "selected": "x"}]},
            format="json",
        )
        assert resp.status_code == 404

    def test_400_empty_answers(
        self,
        authed_client: APIClient,
        conversation: Conversation,
    ) -> None:
        session = _make_plan_session(conversation)
        _make_pending_round(session)
        resp = authed_client.post(
            _url(conversation.id),
            data={"answers": []},
            format="json",
        )
        assert resp.status_code == 400

    def test_409_no_pending_plan_clarification(
        self,
        authed_client: APIClient,
        conversation: Conversation,
    ) -> None:
        # session 存在但无任何 pending 澄清轮 → 409
        _make_plan_session(conversation)
        resp = authed_client.post(
            _url(conversation.id),
            data={"answers": [{"question_id": uuid.uuid4().hex, "selected": "x"}]},
            format="json",
        )
        assert resp.status_code == 409

    def test_404_no_plan_session(
        self,
        authed_client: APIClient,
        conversation: Conversation,
    ) -> None:
        resp = authed_client.post(
            _url(conversation.id),
            data={"answers": [{"question_id": uuid.uuid4().hex, "selected": "x"}]},
            format="json",
        )
        assert resp.status_code == 404

    def test_400_question_id_not_in_round(
        self,
        authed_client: APIClient,
        conversation: Conversation,
        capture_helper: dict[str, Any],
    ) -> None:
        session = _make_plan_session(conversation)
        _make_pending_round(session)
        # 伪造一个不属于该轮的 question_id → 400（落库/续推前拒绝）
        resp = authed_client.post(
            _url(conversation.id),
            data={"answers": [{"question_id": uuid.uuid4().hex, "selected": "后端"}]},
            format="json",
        )
        assert resp.status_code == 400
        assert capture_helper["calls"] == []

    def test_200_answers_invokes_shared_helper(
        self,
        authed_client: APIClient,
        conversation: Conversation,
        capture_helper: dict[str, Any],
        run_bg_inline,
    ) -> None:
        from delivery.models import ClarificationQuestion

        session = _make_plan_session(conversation)
        clar = _make_pending_round(session)
        qids = list(
            ClarificationQuestion.objects.filter(clarification_id=clar.id)
            .order_by("order")
            .values_list("id", flat=True)
        )

        resp = authed_client.post(
            _url(conversation.id),
            data={
                "answers": [
                    {"question_id": str(qids[0]), "selected": "后端"},
                    {"question_id": str(qids[1]), "selected": ["auth"]},
                ]
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["clarification_id"] == str(clar.id)
        assert body["answered"] is True

        # 同源 helper 被调（写 delivery + 续推），且按 pending 轮 id 调用
        assert len(capture_helper["calls"]) == 1
        call = capture_helper["calls"][0]
        assert str(call["clarification_or_id"]) == str(clar.id)
        assert len(call["answers"]) == 2

    def test_owner_with_empty_space_allowed(
        self,
        api_client: APIClient,
        user,
        capture_helper: dict[str, Any],
        run_bg_inline,
    ) -> None:
        """CR-01 回归：个人/通用会话（space 为空）owner 作答应放行（不 500）。

        修复前二级 has_project_access(user, None) 会访问 None.pk 抛 AttributeError → 500。
        owner-skip + space_id 守卫使该路径短路放行。
        """
        from delivery.models import ClarificationQuestion

        conversation = Conversation.objects.create(space=None, title="个人会话", created_by=user)
        session = _make_plan_session(conversation)
        clar = _make_pending_round(session)
        qids = list(
            ClarificationQuestion.objects.filter(clarification_id=clar.id)
            .order_by("order")
            .values_list("id", flat=True)
        )
        # user 是 owner，但未建任何 project membership（且 space 为空）
        api_client.force_authenticate(user=user)
        resp = api_client.post(
            _url(conversation.id),
            data={
                "answers": [
                    {"question_id": str(qids[0]), "selected": "后端"},
                    {"question_id": str(qids[1]), "selected": ["auth"]},
                ]
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["answered"] is True
        assert len(capture_helper["calls"]) == 1

    def test_owner_non_member_allowed(
        self,
        api_client: APIClient,
        user,
        conversation: Conversation,
        capture_helper: dict[str, Any],
        run_bg_inline,
    ) -> None:
        """CR-01 回归：owner 在该 space 非成员（无 membership）作答应放行（不 404）。

        修复前二级 has_project_access(..., "member") 对非成员 owner 返回 False → 误 404。
        owner-skip 守卫（created_by_id == user.id）使已授权 owner 直接放行。
        """
        from delivery.models import ClarificationQuestion

        # conversation.space=project 但 user 无 membership（不引入 project_memberships fixture）
        session = _make_plan_session(conversation)
        clar = _make_pending_round(session)
        qids = list(
            ClarificationQuestion.objects.filter(clarification_id=clar.id)
            .order_by("order")
            .values_list("id", flat=True)
        )
        api_client.force_authenticate(user=user)
        resp = api_client.post(
            _url(conversation.id),
            data={
                "answers": [
                    {"question_id": str(qids[0]), "selected": "后端"},
                    {"question_id": str(qids[1]), "selected": ["auth"]},
                ]
            },
            format="json",
        )
        assert resp.status_code == 200, resp.content
        assert resp.json()["answered"] is True
        assert len(capture_helper["calls"]) == 1

    def test_cross_user_returns_404(
        self,
        api_client: APIClient,
        other_user,
        conversation: Conversation,
        capture_helper: dict[str, Any],
    ) -> None:
        session = _make_plan_session(conversation)
        clar = _make_pending_round(session)
        from delivery.models import ClarificationQuestion

        qids = list(
            ClarificationQuestion.objects.filter(clarification_id=clar.id).values_list(
                "id", flat=True
            )
        )
        api_client.force_authenticate(user=other_user)
        resp = api_client.post(
            _url(conversation.id),
            data={"answers": [{"question_id": str(qids[0]), "selected": "后端"}]},
            format="json",
        )
        assert resp.status_code == 404
        # owner-miss 在落库/续推前拦截
        assert capture_helper["calls"] == []

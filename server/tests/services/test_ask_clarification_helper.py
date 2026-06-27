"""plan_orchestration 入口无关 ``ask_clarification`` helper 守护测试（CLARIFY-03，90-04）。

**这是 ``services.plan_orchestration`` 的编排 helper，不是 chat agent tool**。仓内另有同名
chat tool ``agents/tools/clarification.py:ask_clarification``（写 ``chat.ConversationIntentTrace``
走 LangGraph interrupt），其测试在 ``tests/test_ask_clarification_tool.py``——本文件经文件名 /
导入路径与之**显式区分**，断言对象为 ``from services.plan_orchestration import ask_clarification``。

覆盖：helper 写 ``delivery.Clarification`` 轮 + 多子题 / 携带 origin_repo / 调用不改
``session.status``（不驱动 advance、不挂起）/ 模块路径与 chat tool 区分。helper 写入只经 service
→ INV-6 由 90-02 grep 守护覆盖（本测试聚焦行为，不重复 grep）。
"""

from __future__ import annotations

import pytest

from delivery.models import (
    Clarification,
    ClarificationQuestion,
    PlanSession,
    PlanSessionEntrypoint,
    PlanSessionStatus,
)
from services.plan_orchestration import ask_clarification

# transaction=True：async 用例经 acreate 在独立线程连接写库，普通 django_db（rollback）
# 无法回滚跨线程连接的提交。TransactionTestCase teardown TRUNCATE 全表确保清理。
pytestmark = pytest.mark.django_db(transaction=True)


def _round_questions() -> list[dict]:
    return [
        {"question": "用哪个仓？", "type": "single", "options": ["A", "B"], "recommended": "A"},
        {
            "question": "涉及哪些层？",
            "type": "multi",
            "options": ["X", "Y", "Z"],
            "recommended": ["X", "Y"],
        },
    ]


async def _clarifying_session() -> PlanSession:
    return await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.WORKFLOW, status=PlanSessionStatus.CLARIFYING
    )


@pytest.mark.asyncio
async def test_ask_clarification_writes_delivery_round() -> None:
    """helper → 经 service 落 1 个 delivery.Clarification 容器 + N 个子题（非 chat trace）。"""
    session = await _clarifying_session()
    questions = _round_questions()

    clar = await ask_clarification(session, questions)

    reloaded = await Clarification.objects.aget(id=clar.id)
    assert reloaded.session_id == session.id
    assert reloaded.question == ""  # 结构化真身在子题，容器占位
    assert reloaded.container_status == "pending"

    rows = [
        q async for q in ClarificationQuestion.objects.filter(clarification=clar).order_by("order")
    ]
    assert len(rows) == len(questions)
    assert [r.order for r in rows] == [0, 1]
    assert rows[0].qtype == "single"
    assert rows[0].options == ["A", "B"]
    assert rows[1].qtype == "multi"
    assert rows[1].recommended == ["X", "Y"]


@pytest.mark.asyncio
async def test_ask_clarification_carries_origin_repo() -> None:
    """helper 传 origin_repo → 容器与各子题携带来源仓标注。"""
    session = await _clarifying_session()

    clar = await ask_clarification(session, _round_questions(), origin_repo="repo-x")

    reloaded = await Clarification.objects.aget(id=clar.id)
    assert reloaded.origin_repo == "repo-x"
    rows = [q async for q in ClarificationQuestion.objects.filter(clarification=clar)]
    assert rows and all(r.origin_repo == "repo-x" for r in rows)


@pytest.mark.asyncio
async def test_ask_clarification_does_not_drive_or_suspend() -> None:
    """helper 不驱动 advance / 不挂起：调用前后 session.status 不被 helper 改动。"""
    session = await _clarifying_session()
    status_before = session.status

    await ask_clarification(session, _round_questions())

    # helper 不写 status——内存实例与库内行都应保持原状态
    assert session.status == status_before
    reloaded = await PlanSession.objects.aget(id=session.id)
    assert reloaded.status == status_before


@pytest.mark.asyncio
async def test_ask_clarification_accepts_injected_service() -> None:
    """注入既有 ClarificationService 实例 → helper 复用之写入（不新建第二实例）。"""
    from delivery.services import ClarificationService

    session = await _clarifying_session()
    svc = ClarificationService()

    clar = await ask_clarification(session, _round_questions(), clarification_service=svc)

    assert await Clarification.objects.filter(id=clar.id).aexists()


def test_ask_clarification_is_plan_orchestration_not_chat_tool() -> None:
    """命名撞车防护：本 helper 模块路径与 chat tool 区分，是 plan_orchestration 资产。"""
    assert ask_clarification.__module__ == "services.plan_orchestration.ask_clarification"
    # chat tool 同名但语义不同（写 ConversationIntentTrace），靠模块路径区分，绝不混用
    assert "agents.tools" not in ask_clarification.__module__

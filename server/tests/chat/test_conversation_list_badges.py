"""会话列表 SDD / 技术方案 / 编码徽标 annotate 守护测试（quick task）。

覆盖 list_conversations 的三个聚合布尔：
- has_coding_plan：会话存在 CodingPlan
- has_coding_session：会话存在 CodingSession
- has_sdd_spec：会话 → PlanSession(软引用) → current_plan_version 命中某 SddSpec.plan_version

异步 + sync_to_async 跨线程写库 → transaction=True。
"""

from __future__ import annotations

import uuid

import pytest

from chat.conversation_service import ConversationService
from chat.models import CodingPlan, CodingSession, Conversation
from delivery.models import (
    PlanSession,
    PlanSessionEntrypoint,
    PlanVersion,
    SddSpec,
    TechnicalPlan,
    TechnicalPlanOrigin,
)
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)


async def _make_conversation(title: str = "c") -> Conversation:
    return await Conversation.objects.acreate(title=title)


async def _make_repo() -> Repository:
    return await Repository.objects.acreate(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/test/{uuid.uuid4().hex[:6]}.git",
        git_platform="github",
        default_branch="main",
        index_status="indexed",
    )


async def _make_plan_version() -> PlanVersion:
    plan = await TechnicalPlan.objects.acreate(origin=TechnicalPlanOrigin.CHAT)
    return await PlanVersion.objects.acreate(
        plan=plan, version=1, content={}, content_hash="h"
    )


async def _row_for(conv_id) -> Conversation:
    rows = await ConversationService.list_conversations(limit=50)
    return next(c for c in rows if c.id == conv_id)


async def test_bare_conversation_all_flags_false() -> None:
    conv = await _make_conversation()
    row = await _row_for(conv.id)
    assert row.has_coding_plan is False
    assert row.has_coding_session is False
    assert row.has_sdd_spec is False


async def test_coding_plan_flag_true() -> None:
    conv = await _make_conversation()
    await CodingPlan.objects.acreate(conversation=conv, tech_plan="x")
    row = await _row_for(conv.id)
    assert row.has_coding_plan is True
    assert row.has_coding_session is False


async def test_coding_session_flag_true() -> None:
    conv = await _make_conversation()
    repo = await _make_repo()
    await CodingSession.objects.acreate(conversation=conv, repository=repo, tech_plan="x")
    row = await _row_for(conv.id)
    assert row.has_coding_session is True


async def test_sdd_spec_flag_via_plan_session() -> None:
    conv = await _make_conversation()
    repo = await _make_repo()
    pv = await _make_plan_version()
    await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        conversation_id=conv.id,
        current_plan_version=pv.id,
    )
    await SddSpec.objects.acreate(repository=repo, plan_version=pv)
    row = await _row_for(conv.id)
    assert row.has_sdd_spec is True


async def test_sdd_spec_not_leaked_across_conversations() -> None:
    """spec 挂在 A 会话的 PlanSession 上，不得污染 B 会话。"""
    conv_a = await _make_conversation("a")
    conv_b = await _make_conversation("b")
    repo = await _make_repo()
    pv = await _make_plan_version()
    await PlanSession.objects.acreate(
        entrypoint=PlanSessionEntrypoint.CHAT,
        conversation_id=conv_a.id,
        current_plan_version=pv.id,
    )
    await SddSpec.objects.acreate(repository=repo, plan_version=pv)

    assert (await _row_for(conv_a.id)).has_sdd_spec is True
    assert (await _row_for(conv_b.id)).has_sdd_spec is False

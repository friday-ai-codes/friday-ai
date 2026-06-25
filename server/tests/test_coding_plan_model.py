"""CodingPlan 模型测试 — 工厂去重 / property 回退 / 异步更新（implementation）。"""

from __future__ import annotations

import pytest

from chat.models import CodingPlan, CodingSession, Conversation

# ---------------------------------------------------------------------------
# 辅助 fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def conversation(db, project):
    """创建测试对话。"""
    return Conversation.objects.create(space=project, title="测试对话")


@pytest.fixture
def second_conversation(db, project):
    """同一 project 下的另一个对话（跨 conversation 不去重场景）。"""
    return Conversation.objects.create(space=project, title="第二对话")


# ---------------------------------------------------------------------------
# CodingPlan 模型基础
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_coding_plan_acreate_basic(conversation):
    """直接 acreate 落库成功，字段回读一致。"""
    plan = await CodingPlan.objects.acreate(
        conversation=conversation,
        tech_plan="## 方案 A",
        affected_files=[{"file_path": "a.py", "change_type": "modify"}],
        title="方案 A",
    )
    loaded = await CodingPlan.objects.aget(id=plan.id)
    assert loaded.tech_plan == "## 方案 A"
    assert loaded.affected_files == [{"file_path": "a.py", "change_type": "modify"}]
    assert loaded.title == "方案 A"
    assert loaded.feishu_doc_token == ""
    assert loaded.feishu_doc_url == ""


# ---------------------------------------------------------------------------
# 工厂方法：sha256 去重
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_aget_or_create_for_conversation_dedup(conversation):
    """同一 conversation + 相同 tech_plan 第二次返回 created=False，DB 计数 == 1。"""
    tech_plan = "## 方案 A\n- step 1"
    plan1, created1 = await CodingPlan.aget_or_create_for_conversation(
        conversation=conversation,
        tech_plan=tech_plan,
        affected_files=[{"file_path": "a.py", "change_type": "modify"}],
    )
    plan2, created2 = await CodingPlan.aget_or_create_for_conversation(
        conversation=conversation,
        tech_plan=tech_plan,
        affected_files=[{"file_path": "a.py", "change_type": "modify"}],
    )
    assert created1 is True
    assert created2 is False
    assert plan1.id == plan2.id
    count = await CodingPlan.objects.filter(conversation=conversation).acount()
    assert count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_aget_or_create_for_conversation_different_plans(conversation):
    """同一 conversation 不同 tech_plan 产出 2 条独立记录。"""
    plan1, c1 = await CodingPlan.aget_or_create_for_conversation(
        conversation=conversation,
        tech_plan="## 方案 A",
        affected_files=[],
    )
    plan2, c2 = await CodingPlan.aget_or_create_for_conversation(
        conversation=conversation,
        tech_plan="## 方案 B",
        affected_files=[],
    )
    assert c1 is True
    assert c2 is True
    assert plan1.id != plan2.id
    count = await CodingPlan.objects.filter(conversation=conversation).acount()
    assert count == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_aget_or_create_for_conversation_cross_conversation(
    conversation, second_conversation
):
    """两个 conversation 即使 tech_plan 完全一样，也产出 2 条独立记录。"""
    plan1, c1 = await CodingPlan.aget_or_create_for_conversation(
        conversation=conversation,
        tech_plan="## 同样方案",
        affected_files=[],
    )
    plan2, c2 = await CodingPlan.aget_or_create_for_conversation(
        conversation=second_conversation,
        tech_plan="## 同样方案",
        affected_files=[],
    )
    assert c1 is True
    assert c2 is True
    assert plan1.id != plan2.id
    total = await CodingPlan.objects.acount()
    assert total == 2


# ---------------------------------------------------------------------------
# CodingSession 的 property 包装
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_coding_session_property_falls_back_when_no_plan(conversation, repository):
    """无 coding_plan 关联时，property 回退到 session 本字段。"""
    session = await CodingSession.objects.acreate(
        conversation=conversation,
        repository=repository,
        tech_plan="legacy plan text",
        affected_files=[{"file_path": "x.py", "change_type": "add"}],
    )
    assert session.coding_plan_id is None
    assert session.tech_plan_effective == "legacy plan text"
    assert session.affected_files_effective == [
        {"file_path": "x.py", "change_type": "add"}
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_coding_session_property_prefers_plan_when_linked(
    conversation, repository
):
    """关联 coding_plan 后 property 优先返回 plan 字段，与 session 本字段隔离。"""
    plan = await CodingPlan.objects.acreate(
        conversation=conversation,
        tech_plan="plan-authoritative",
        affected_files=[{"file_path": "p.py", "change_type": "modify"}],
    )
    session = await CodingSession.objects.acreate(
        conversation=conversation,
        repository=repository,
        coding_plan=plan,
        tech_plan="session-legacy-text",
        affected_files=[{"file_path": "legacy.py", "change_type": "modify"}],
    )

    # 重新 select_related 拉取（避免 lazy 加载漏 plan）
    loaded = await CodingSession.objects.select_related("coding_plan").aget(
        id=session.id
    )
    assert loaded.tech_plan_effective == "plan-authoritative"
    assert loaded.affected_files_effective == [
        {"file_path": "p.py", "change_type": "modify"}
    ]
    # 本字段不变（兼容期未删）
    assert loaded.tech_plan == "session-legacy-text"


# ---------------------------------------------------------------------------
# aupdate_plan
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_coding_plan_aupdate_plan(conversation):
    """aupdate_plan 写入 tech_plan / affected_files / updated_at 字段。"""
    plan = await CodingPlan.objects.acreate(
        conversation=conversation,
        tech_plan="old",
        affected_files=[{"file_path": "old.py", "change_type": "modify"}],
    )
    await plan.aupdate_plan(
        tech_plan="new",
        affected_files=[{"file_path": "new.py", "change_type": "add"}],
    )
    loaded = await CodingPlan.objects.aget(id=plan.id)
    assert loaded.tech_plan == "new"
    assert loaded.affected_files == [{"file_path": "new.py", "change_type": "add"}]

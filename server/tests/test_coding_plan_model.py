"""CodingPlan 模型测试 — 工厂去重 / property 回退 / 异步更新（implementation）。

另含 Phase 109 / SPINE-01 的投影幂等键约束断言（见文件末尾两个用例）。
"""

from __future__ import annotations

import uuid

import pytest
from django.db import IntegrityError, connection, transaction

from chat.models import (
    CodingPlan,
    CodingPlanProvenance,
    CodingSession,
    Conversation,
)

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


# ---------------------------------------------------------------------------
# 投影幂等键：uniq_codingplan_source_artifact_version（Phase 109 / SPINE-01）
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_source_artifact_version_unique_constraint_exists_on_backend():
    """约束在**当前 DB 后端确实存在**（防 AddConstraint 被静默跳过）。

    这条断言存在的唯一理由：`UniqueConstraint` 一旦带 `condition=`，
    `django/db/backends/base/schema.py::_unique_supported()` 会在
    `supports_partial_indexes = False` 的后端（MySQL / MariaDB）返回 False ⇒
    `AddConstraint` 被**静默跳过**，不报错也不告警。没有这条断言，「约束不存在」
    与「约束存在」在测试上的表现完全一致 —— 多 NULL 行共存在无约束时同样通过，
    幂等用例是顺序调用而非并发，因此都检不出来。

    按**列集合**而非按名字断言：部分后端会改写约束/索引名。若后端保留了原名，
    则一并断言该名条目的形状。
    """
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(
            cursor, CodingPlan._meta.db_table
        )

    expected_columns = ["source_artifact_version_id"]
    matched = {
        name: meta
        for name, meta in constraints.items()
        if meta.get("unique") and list(meta.get("columns") or []) == expected_columns
    }
    assert matched, (
        "coding_plans 表上没有 source_artifact_version_id 的唯一约束 —— "
        "AddConstraint 可能被后端静默跳过（检查约束是否误加了 condition=）。"
        f"实得约束：{sorted(constraints)}"
    )

    named = constraints.get("uniq_codingplan_source_artifact_version")
    if named is not None:  # 后端保留了原约束名
        assert named.get("unique") is True
        assert list(named.get("columns") or []) == expected_columns


@pytest.mark.django_db(transaction=True)
def test_source_artifact_version_constraint_allows_nulls_but_blocks_duplicates(
    conversation,
):
    """无条件唯一约束不误伤 NULL 草稿行，但真值重复会被 DB 挡下。

    与上一条互补：上一条证明约束**存在**，本条证明它挡真值、且不挡 NULL
    （PostgreSQL / MySQL / SQLite 的唯一索引都把 NULL 视为互不相等，
    因此无需 `condition` 即可让多条草稿行共存）。
    """
    draft_a = CodingPlan.objects.create(
        conversation=conversation, tech_plan="## 草稿 A", affected_files=[]
    )
    draft_b = CodingPlan.objects.create(
        conversation=conversation, tech_plan="## 草稿 B", affected_files=[]
    )
    assert draft_a.source_artifact_version_id is None
    assert draft_b.source_artifact_version_id is None
    # 存量与所有既有写入路径都走 DB default
    assert draft_a.provenance == CodingPlanProvenance.DRAFT
    assert draft_b.provenance == CodingPlanProvenance.DRAFT

    version_id = uuid.uuid4()
    CodingPlan.objects.create(
        conversation=conversation,
        tech_plan="## 投影 1",
        affected_files=[],
        provenance=CodingPlanProvenance.ORCHESTRATED,
        source_artifact_version_id=version_id,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CodingPlan.objects.create(
                conversation=conversation,
                tech_plan="## 投影 2（同一方案版本）",
                affected_files=[],
                provenance=CodingPlanProvenance.ORCHESTRATED,
                source_artifact_version_id=version_id,
            )

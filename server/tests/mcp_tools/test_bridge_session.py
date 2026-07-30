"""MCP 桥接三对象直接断言 —— Phase 109 / SPINE-02 的「MCP 零回归」直接锁。

``mcp_tools.execution_service._create_bridge_session`` 用**裸 ORM**（
``objects.create()``）一次建成 Conversation + chat CodingPlan + CodingSession。
MCP 执行链从不调用 chat ``@tool``，所以 SPINE-02 收窄工具 schema 对 MCP 的行为
耦合面为零 —— 真正要保的是**这三个模型的字段形状**：

    给 ``CodingPlan`` / ``CodingSession`` / ``Conversation`` 新增列时若忘了
    ``default``，裸 ``objects.create()`` 会直接崩，本文件必红。

既有 ``test_execution_tools.py`` 走 HTTP + ``execute_coding_plan`` 全链，断言了
``CodingSession`` 却没有显式断言桥接出来的 chat ``CodingPlan``；本文件绕开 HTTP
与 dispatch，直接调桥接函数，把三对象的字段形状钉死。

注：本文件断言的是**当前**字段形状。后续 phase 给 CodingPlan 加列时，新字段的
默认值断言在本文件内追加。
"""

from __future__ import annotations

import uuid

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model

from chat.models import CodingPlan, CodingSession, Conversation
from interactions.models import InteractionRun
from mcp_tools.execution_service import _create_bridge_session
from mcp_tools.models import McpCodingPlan, McpCodingPlanVersion
from projects.models import Space
from repositories.models import Repository

User = get_user_model()

_BRANCH_NAME = "feat/2026-07-30.bridge"

# 最小 plan_body 形状（_plan_body_to_markdown 消费的键集）。
_PLAN_BODY = {
    "title": "MCP 桥接最小方案",
    "requirement": "在 src/main.py 增加入口日志",
    "steps": [{"order": 1, "title": "改 main", "detail": "补一行 logger"}],
    "test_plan": ["pytest tests/test_main.py"],
    "risks": ["无"],
}


@pytest.fixture
def bridge_user(db):
    return User.objects.create_user(
        username=f"bridge_{uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:6]}@bridge.local",
        password="testpass123",
    )


@pytest.fixture
def bridge_space(db) -> Space:
    suffix = uuid.uuid4().hex[:8]
    return Space.objects.create(
        name=f"MCP 桥接测试空间-{suffix}",
        feishu_project_key=f"bridge-{suffix}",
    )


@pytest.fixture
def bridge_repository(db, bridge_space: Space) -> Repository:
    repo = Repository.objects.create(
        name="bridge-repo",
        git_url="https://gitlab.com/bridge/bridge-repo.git",
        git_platform="gitlab",
        default_branch="main",
    )
    bridge_space.repositories.add(repo)
    return repo


@pytest.fixture
def bridge_plan(db, bridge_repository: Repository) -> McpCodingPlan:
    run = InteractionRun.objects.create(source="mcp")
    return McpCodingPlan.objects.create(
        run=run,
        repository=bridge_repository,
        requirement=_PLAN_BODY["requirement"],
        title="MCP 桥接最小方案",
    )


@pytest.fixture
def bridge_version(db, bridge_plan: McpCodingPlan) -> McpCodingPlanVersion:
    return McpCodingPlanVersion.objects.create(
        plan=bridge_plan,
        run=bridge_plan.run,
        version=1,
        plan_body=_PLAN_BODY,
        affected_files=[{"file_path": "src/main.py", "change_type": "modify"}],
    )


@pytest.mark.django_db(transaction=True)
def test_create_bridge_session_builds_three_objects(
    bridge_space: Space,
    bridge_plan: McpCodingPlan,
    bridge_version: McpCodingPlanVersion,
    bridge_user,
) -> None:
    """一次调用建成 Conversation / CodingPlan / CodingSession，且字段形状不变。"""
    before = (
        Conversation.objects.count(),
        CodingPlan.objects.count(),
        CodingSession.objects.count(),
    )

    conversation, chat_plan, coding_session = async_to_sync(_create_bridge_session)(
        project=bridge_space,
        plan=bridge_plan,
        version=bridge_version,
        branch_name=_BRANCH_NAME,
        created_by=bridge_user,
    )

    # —— Conversation ——
    assert conversation.space_id == bridge_space.id
    assert conversation.status == Conversation.Status.RUNNING
    assert conversation.created_by_id == bridge_user.id
    assert conversation.title.startswith("MCP execution: ")

    # —— chat CodingPlan（既有 e2e 未显式断言的那一环）——
    assert chat_plan.conversation_id == conversation.id
    assert chat_plan.tech_plan
    assert isinstance(chat_plan.affected_files, list)
    assert chat_plan.recommended_repository_ids == [str(bridge_plan.repository_id)]

    # —— CodingSession ——
    assert coding_session.coding_plan_id == chat_plan.id
    assert coding_session.repository_id == bridge_plan.repository_id
    assert coding_session.branch_name == _BRANCH_NAME
    assert coding_session.status == CodingSession.Status.DRAFT

    # —— 计数：三张表各恰好 +1（防止未来把桥接拆成多写）——
    after = (
        Conversation.objects.count(),
        CodingPlan.objects.count(),
        CodingSession.objects.count(),
    )
    assert after == tuple(n + 1 for n in before)

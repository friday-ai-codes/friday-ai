"""Chat 项目召回接入守护测试（Phase 80，RECALL-02/03）：

- search_delivery_knowledge 等已接入 chat runner 工具白名单（_INDEXED_TOOL_NAMES）
- 会话绑定项目 + 成员 → build_sdk_config 注入打包上下文
- 非成员 / 未绑定 → 不注入（fail-closed）
"""

from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from chat.config import _maybe_pack_project_context
from chat.models import Conversation
from initiatives.models import ProjectVisibility
from initiatives.services import MemoryService, ProjectService
from knowledge.access_scope import resolve_allowed_project_ids
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


def test_delivery_knowledge_tools_in_chat_whitelist():
    from agents.chat_runner import _DEEP_ANALYSIS_TOOL_NAMES, _INDEXED_TOOL_NAMES

    for name in (
        "search_delivery_knowledge",
        "get_entity_timeline",
        "get_related_entities",
    ):
        assert name in _INDEXED_TOOL_NAMES
    # deep_analysis 列表是 indexed 的超集（零回归命门）。
    assert set(_INDEXED_TOOL_NAMES).issubset(set(_DEEP_ANALYSIS_TOOL_NAMES))


@sync_to_async
def _make_user(username):
    return User.objects.create_user(username=username, password="x")


async def _make_project_with_member(*, key="recall-k", visibility=ProjectVisibility.PUBLIC_ORG):
    """建项目并显式设 visibility（夹具直写，仅测试用，不进生产写路径）。"""
    space = await sync_to_async(Space.objects.create)(name="S")
    owner = await _make_user(f"owner-{key}")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=key, created_by=owner
    )
    if visibility != ProjectVisibility.PUBLIC_ORG:
        project.visibility = visibility
        await project.asave(update_fields=["visibility"])
    return project, owner


async def test_bound_project_member_context_injected():
    project, owner = await _make_project_with_member()
    await MemoryService().append(
        project_id=project.id, content="召回记忆条目", contributor=owner
    )
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", bound_project=project, created_by=owner
    )
    text = await _maybe_pack_project_context(conversation)
    assert "召回记忆条目" in text


async def test_bound_project_members_only_non_member_no_injection_fail_closed():
    """members_only 非成员经 chat 绑定 → 零注入（维持 fail-closed）。"""
    project, _owner = await _make_project_with_member(
        key="recall-mo", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    stranger = await _make_user("stranger")
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", bound_project=project, created_by=stranger
    )
    text = await _maybe_pack_project_context(conversation)
    assert text == ""


async def test_bound_project_public_org_non_member_recall():
    """public_org 非成员经 chat 绑定 → 端到端可召回（读放行）。"""
    project, owner = await _make_project_with_member(
        key="recall-po", visibility=ProjectVisibility.PUBLIC_ORG
    )
    await MemoryService().append(
        project_id=project.id, content="公开召回条目", contributor=owner
    )
    stranger = await _make_user("stranger-po")
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", bound_project=project, created_by=stranger
    )
    text = await _maybe_pack_project_context(conversation)
    assert "公开召回条目" in text


async def test_bound_project_member_members_only_recall():
    """成员 + members_only 经 chat 绑定 → 仍可召回（不回退）。"""
    project, owner = await _make_project_with_member(
        key="recall-mo-mem", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    await MemoryService().append(
        project_id=project.id, content="成员召回条目", contributor=owner
    )
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", bound_project=project, created_by=owner
    )
    text = await _maybe_pack_project_context(conversation)
    assert "成员召回条目" in text


async def test_unbound_conversation_no_injection():
    owner = await _make_user("solo")
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", created_by=owner
    )
    text = await _maybe_pack_project_context(conversation)
    assert text == ""


async def test_access_scope_includes_public_org_project():
    """access_scope：public_org 项目并入普通用户可读集合（非成员也可见）。"""
    project, _owner = await _make_project_with_member(
        key="scope-po", visibility=ProjectVisibility.PUBLIC_ORG
    )
    stranger = await _make_user("scope-stranger")
    allowed = await resolve_allowed_project_ids(stranger)
    assert str(project.id) in allowed


async def test_access_scope_members_only_caller_narrowing_preserved():
    """access_scope：caller 传 members_only 非成员项目 id → []（收窄语义未被破坏）。"""
    project, _owner = await _make_project_with_member(
        key="scope-mo", visibility=ProjectVisibility.MEMBERS_ONLY
    )
    stranger = await _make_user("scope-stranger-mo")
    allowed = await resolve_allowed_project_ids(
        stranger, project_ids=[str(project.id)]
    )
    assert allowed == []

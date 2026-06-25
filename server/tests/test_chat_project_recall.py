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
from initiatives.services import MemoryService, ProjectService
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


async def _make_project_with_member():
    space = await sync_to_async(Space.objects.create)(name="S")
    owner = await _make_user("owner")
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key="recall-k", created_by=owner
    )
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


async def test_bound_project_non_member_no_injection_fail_closed():
    project, _owner = await _make_project_with_member()
    stranger = await _make_user("stranger")
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", bound_project=project, created_by=stranger
    )
    text = await _maybe_pack_project_context(conversation)
    assert text == ""


async def test_unbound_conversation_no_injection():
    owner = await _make_user("solo")
    conversation = await sync_to_async(Conversation.objects.create)(
        title="t", created_by=owner
    )
    text = await _maybe_pack_project_context(conversation)
    assert text == ""

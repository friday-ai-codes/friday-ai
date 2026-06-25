"""对话 API 集成测试。

测试 Conversation CRUD 端点。
鉴权开关默认关闭，无需认证即可访问。
"""

from __future__ import annotations

import pytest
from rest_framework import status

from chat.models import Conversation, Message
from projects.models import Space

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def test_project(db):
    """创建测试项目（不依赖 repository）。"""
    return Space.objects.create(
        name="Test Chat Space",
        description="项目用于对话测试",
    )


@pytest.fixture
def conversation(db, test_project):
    """创建测试对话。"""
    return Conversation.objects.create(
        space=test_project,
        title="测试对话",
    )


@pytest.fixture
def messages(db, conversation):
    """创建测试消息。"""
    msg1 = Message.objects.create(
        conversation=conversation,
        role=Message.Role.USER,
        content="你好",
    )
    msg2 = Message.objects.create(
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content="你好！有什么可以帮助你的？",
    )
    return [msg1, msg2]


# ============================================================================
# 创建对话测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestCreateConversation:
    """POST /api/chat/conversations/ 测试。"""

    def test_create_conversation_success(self, api_client, test_project):
        """创建对话成功，返回 201。"""
        response = api_client.post(
            "/api/chat/conversations/",
            {"space_id": str(test_project.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["space_id"] == str(test_project.id)
        assert response.data["title"] == "新对话"
        assert "id" in response.data

    def test_create_conversation_with_title(self, api_client, test_project):
        """创建对话时指定标题。"""
        response = api_client.post(
            "/api/chat/conversations/",
            {"space_id": str(test_project.id), "title": "我的对话"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["title"] == "我的对话"

    def test_create_conversation_invalid_project(self, api_client):
        """space_id 不存在时返回 400。"""
        response = api_client.post(
            "/api/chat/conversations/",
            {"space_id": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_conversation_without_space_creates_general_conversation(
        self, api_client
    ):
        """缺少 space_id 时创建不绑定空间的通用对话（space_id=null）。

        行为变更：原契约是缺 space_id → 400；现在允许无空间对话，
        任务涉及空间知识时由 system prompt 引导用户选择空间。
        """
        response = api_client.post(
            "/api/chat/conversations/",
            {},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["space_id"] is None

    def test_create_conversation_with_null_space_id(self, api_client):
        """显式传 space_id=null 同样创建通用对话。"""
        response = api_client.post(
            "/api/chat/conversations/",
            {"space_id": None},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["space_id"] is None


# ============================================================================
# 对话列表测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestConversationList:
    """GET /api/chat/conversations/ 测试。"""

    def test_list_conversations(self, api_client, conversation):
        """返回对话列表。"""
        response = api_client.get("/api/chat/conversations/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["title"] == "测试对话"

    def test_list_conversations_excludes_deleted(self, api_client, conversation):
        """已删除的对话不显示。"""
        conversation.is_deleted = True
        conversation.save()

        response = api_client.get("/api/chat/conversations/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0

    def test_list_conversations_ordering(self, api_client, test_project):
        """对话按 updated_at 降序排列。"""
        _conv1 = Conversation.objects.create(space=test_project, title="对话 1")
        _conv2 = Conversation.objects.create(space=test_project, title="对话 2")

        response = api_client.get("/api/chat/conversations/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        # 最新创建的排在前面
        assert response.data[0]["title"] == "对话 2"

    def test_list_defaults_to_top_50(self, api_client, test_project):
        """默认仅返回最近 50 条（top N）。"""
        for i in range(55):
            Conversation.objects.create(space=test_project, title=f"对话 {i}")

        response = api_client.get("/api/chat/conversations/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 50

    def test_list_custom_limit(self, api_client, test_project):
        """支持 ?limit= 自定义条数。"""
        for i in range(10):
            Conversation.objects.create(space=test_project, title=f"对话 {i}")

        response = api_client.get("/api/chat/conversations/?limit=3")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 3

    def test_list_search_by_title(self, api_client, test_project):
        """?q= 命中标题。"""
        Conversation.objects.create(space=test_project, title="研发周报")
        Conversation.objects.create(space=test_project, title="刷题需求")

        response = api_client.get("/api/chat/conversations/?q=周报")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["title"] == "研发周报"

    def test_list_search_by_message_content(self, api_client, test_project):
        """?q= 命中消息内容（标题不含关键词也能搜到）。"""
        hit = Conversation.objects.create(space=test_project, title="无关标题")
        Message.objects.create(
            conversation=hit,
            role=Message.Role.ASSISTANT,
            content="思维培优的判断依据是 isThinking 查询参数",
        )
        Conversation.objects.create(space=test_project, title="另一个对话")

        response = api_client.get("/api/chat/conversations/?q=isThinking")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["id"] == str(hit.id)

    def test_list_search_dedups_multiple_message_hits(self, api_client, test_project):
        """同一会话多条消息命中关键词时不重复返回。"""
        conv = Conversation.objects.create(space=test_project, title="标题含关键词abc")
        Message.objects.create(conversation=conv, role=Message.Role.USER, content="abc 1")
        Message.objects.create(conversation=conv, role=Message.Role.ASSISTANT, content="abc 2")

        response = api_client.get("/api/chat/conversations/?q=abc")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_list_excludes_archived(self, api_client, test_project):
        """归档的对话默认不出现在列表。"""
        Conversation.objects.create(space=test_project, title="正常对话")
        Conversation.objects.create(
            space=test_project, title="归档对话", is_archived=True,
        )

        response = api_client.get("/api/chat/conversations/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["title"] == "正常对话"

    def test_list_archived_only(self, api_client, test_project):
        """?archived=1 仅返回已归档会话。"""
        Conversation.objects.create(space=test_project, title="正常对话")
        Conversation.objects.create(
            space=test_project, title="归档对话", is_archived=True,
        )

        response = api_client.get("/api/chat/conversations/?archived=1")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["title"] == "归档对话"
        assert response.data[0]["is_archived"] is True


@pytest.mark.django_db(transaction=True)
class TestConversationPatchTitleArchive:
    """PATCH /api/chat/conversations/{id}/ 改名 / 归档。"""

    def test_patch_rename(self, api_client, conversation):
        """改标题成功并落库。"""
        response = api_client.patch(
            f"/api/chat/conversations/{conversation.id}/",
            {"title": "新标题"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == "新标题"
        conversation.refresh_from_db()
        assert conversation.title == "新标题"

    def test_patch_archive_then_excluded_from_list(self, api_client, conversation):
        """归档后从列表消失，但记录仍在（未软删）。"""
        response = api_client.patch(
            f"/api/chat/conversations/{conversation.id}/",
            {"is_archived": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_archived"] is True
        conversation.refresh_from_db()
        assert conversation.is_archived is True
        assert conversation.is_deleted is False

        list_resp = api_client.get("/api/chat/conversations/")
        assert len(list_resp.data) == 0

    def test_patch_unarchive(self, api_client, conversation):
        """取消归档后重新出现在列表。"""
        conversation.is_archived = True
        conversation.save(update_fields=["is_archived"])

        response = api_client.patch(
            f"/api/chat/conversations/{conversation.id}/",
            {"is_archived": False},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_archived"] is False
        list_resp = api_client.get("/api/chat/conversations/")
        assert len(list_resp.data) == 1


# ============================================================================
# 对话详情测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestConversationDetail:
    """GET /api/chat/conversations/{id}/ 测试。"""

    def test_get_conversation_detail(self, api_client, conversation, messages):
        """返回对话详情含消息。"""
        response = api_client.get(f"/api/chat/conversations/{conversation.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["title"] == "测试对话"
        assert len(response.data["messages"]) == 2
        assert response.data["messages"][0]["role"] == "user"
        assert response.data["messages"][1]["role"] == "assistant"

    def test_get_conversation_not_found(self, api_client):
        """对话不存在返回 404。"""
        response = api_client.get(
            "/api/chat/conversations/00000000-0000-0000-0000-000000000000/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_get_deleted_conversation_returns_404(self, api_client, conversation):
        """已删除的对话返回 404。"""
        conversation.is_deleted = True
        conversation.save()

        response = api_client.get(f"/api/chat/conversations/{conversation.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 删除对话测试
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestDeleteConversation:
    """DELETE /api/chat/conversations/{id}/ 测试。"""

    def test_delete_conversation(self, api_client, conversation):
        """软删除对话，返回 204。"""
        response = api_client.delete(f"/api/chat/conversations/{conversation.id}/")

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # 验证软删除
        conversation.refresh_from_db()
        assert conversation.is_deleted is True

    def test_delete_nonexistent_conversation(self, api_client):
        """删除不存在的对话返回 404。"""
        response = api_client.delete(
            "/api/chat/conversations/00000000-0000-0000-0000-000000000000/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_already_deleted(self, api_client, conversation):
        """已删除的对话不可再删，返回 404。"""
        conversation.is_deleted = True
        conversation.save()

        response = api_client.delete(f"/api/chat/conversations/{conversation.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

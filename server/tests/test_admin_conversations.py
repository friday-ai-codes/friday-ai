"""Phase 09 — 管理员只读会话管理后台 RED 验证脚手架（ADMVW-01/02/03）。

本文件钉死 Phase 9 的行为契约：在 Phase 8 把普通 `/api/chat/conversations/`
锁成「只看自己」之后，给管理员一组**物理分离、显式 superuser 授权**的只读
会话管理端点 `/api/admin/conversations/`：

    - ADMVW-01：管理员可跨用户浏览所有会话（list 含他人 owner）；非管理员 403；
      匿名拒绝（401/403）。
    - ADMVW-02：后台只读——admin 端点不提供 patch/delete/post-send/stream 写操作，
      非法写方法由 DRF 自动 405；管理员**不能**在他人会话上续聊。
    - ADMVW-03：管理员可 fork 任意会话为一份归属自己（`created_by=admin`、
      `status=DRAFT`）的整份副本，源会话不变。

执行约定（Wave 0，RED-first）：
    - 生产代码（admin views/urls/service/serializer）尚未实现，端点不存在，
      故本文件断言**预期全部 RED**（GET/POST 命中 404，写方法断言因 404 != 405 失败）；
      Wave 1（09-02 后端）落地后转 GREEN。
    - 文件仅 import 既有 `chat.models`（无未实现的生产模块顶层 import），
      保证 `pytest --co` 可被收集。
    - admin gate 语义遵循 09-RESEARCH Pitfall 3：非管理员 → **403**（非 404-everything，
      与 accounts admin 端点一致），管理员取不存在会话 → 404（普通 not-found）。

端点前缀 `/api/admin/conversations/`，沿用 settings 默认认证类（要求登录、拒匿名），
绝不复用 chat 路径的 OptionalJWTAuthentication（09-RESEARCH Pitfall 2）。
本文件 **不** 改写任何 `/api/chat/` 普通路径断言（Phase 8 隔离基线由
test_conversation_isolation.py 单独守护，必须保持全绿）。
"""

from __future__ import annotations

import json

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.models import Conversation, Message

User = get_user_model()

ADMIN_LIST_URL = "/api/admin/conversations/"


# ============================================================================
# Helpers — owner 可注入的 async 创建工具（仿 test_conversation_isolation.py 范式）
# ============================================================================


async def _acreate_conversation(project, *, owner, title="admin-conv", **kwargs):
    """async 创建会话并写入 created_by（owner）。"""
    return await Conversation.objects.acreate(
        project=project,
        title=title,
        model=kwargs.pop("model", ""),
        created_by=owner,
        **kwargs,
    )


async def _acreate_message(conversation, *, role=Message.Role.USER, content="hello"):
    """async 创建一条消息。"""
    return await Message.objects.acreate(
        conversation=conversation,
        role=role,
        content=content,
    )


async def _acreate_conversation_with_messages(project, *, owner, title, n=3):
    """创建一个带 n 条消息的会话，返回 (conversation, message_count)。"""
    conv = await _acreate_conversation(project, owner=owner, title=title)
    for i in range(n):
        role = Message.Role.USER if i % 2 == 0 else Message.Role.ASSISTANT
        await _acreate_message(conv, role=role, content=f"{title}-msg-{i}")
    return conv, n


# ============================================================================
# Fixtures — admin（superuser）+ 两个普通用户 user_a / user_b
# ============================================================================


@pytest.fixture
async def admin_and_token(db):
    """管理员（superuser）+ JWT access token。"""
    user = await User.objects.acreate_superuser(
        username="admvw_admin",
        email="admvw_admin@example.com",
        password="admvw-admin-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


@pytest.fixture
def admin_headers(admin_and_token):
    """管理员 Bearer Authorization 头。"""
    _, access_token = admin_and_token
    return {"authorization": f"Bearer {access_token}"}


@pytest.fixture
async def user_a_and_token(db):
    """普通用户 A（会话 owner）+ JWT。"""
    user = await User.objects.acreate_user(
        username="admvw_user_a",
        password="admvw-a-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


@pytest.fixture
def user_a_headers(user_a_and_token):
    """普通用户 A 的 Bearer Authorization 头。"""
    _, access_token = user_a_and_token
    return {"authorization": f"Bearer {access_token}"}


@pytest.fixture
async def user_b_and_token(db):
    """普通用户 B（第二 owner）+ JWT。"""
    user = await User.objects.acreate_user(
        username="admvw_user_b",
        password="admvw-b-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


# ============================================================================
# ADMVW-01：管理员跨用户浏览 / 非管理员 403 / 匿名拒绝
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestAdminListAccess:
    """ADMVW-01：admin 看全部、非 admin 403、匿名拒绝。"""

    async def test_admin_list_sees_all_users(
        self, admin_and_token, admin_headers, user_a_and_token, user_b_and_token, project
    ):
        """admin GET 列表 → 200，且响应覆盖 user_a 与 user_b 两个不同 owner 的会话。"""
        user_a, _ = user_a_and_token
        user_b, _ = user_b_and_token
        conv_a = await _acreate_conversation(project, owner=user_a, title="A-conv")
        conv_b = await _acreate_conversation(project, owner=user_b, title="B-conv")

        client = AsyncClient()
        resp = await client.get(ADMIN_LIST_URL, headers=admin_headers)
        assert resp.status_code == 200, (
            f"admin 列表应 200（拿到 {resp.status_code}；Wave 0 端点未实现 → RED）"
        )

        items = resp.json()
        conv_ids = {item["id"] for item in items}
        assert str(conv_a.id) in conv_ids
        assert str(conv_b.id) in conv_ids
        # 跨用户：owner.id 集合必须覆盖两个不同用户
        owner_ids = {
            (item.get("owner") or {}).get("id")
            for item in items
            if item.get("owner")
        }
        assert str(user_a.id) in owner_ids
        assert str(user_b.id) in owner_ids

    async def test_non_admin_list_403(self, user_a_and_token, user_a_headers, project):
        """非管理员（user_a）GET admin 列表 → 403（IsSuperUser，明确 403 而非 404）。"""
        client = AsyncClient()
        resp = await client.get(ADMIN_LIST_URL, headers=user_a_headers)
        assert resp.status_code == 403, (
            f"非管理员访问 admin 列表应 403（拿到 {resp.status_code}）"
        )

    async def test_anonymous_denied(self, db):
        """匿名（无 Authorization）GET admin 列表 → 拒绝（401 或 403）。"""
        client = AsyncClient()
        resp = await client.get(ADMIN_LIST_URL)
        assert resp.status_code in {401, 403}, (
            f"匿名访问 admin 列表应被拒（401/403），拿到 {resp.status_code}"
        )

    async def test_admin_detail_other_user(
        self, admin_and_token, admin_headers, user_a_and_token, project
    ):
        """admin GET 他人（user_a）会话 detail → 200，响应含 messages 列表。"""
        user_a, _ = user_a_and_token
        conv, n = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-detail", n=2
        )

        client = AsyncClient()
        resp = await client.get(f"{ADMIN_LIST_URL}{conv.id}/", headers=admin_headers)
        assert resp.status_code == 200, (
            f"admin 看他人会话 detail 应 200（拿到 {resp.status_code}）"
        )
        body = resp.json()
        assert "messages" in body
        assert len(body["messages"]) == n


# ============================================================================
# ADMVW-02：只读——写方法 405 + 管理员不可续聊
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestAdminReadOnly:
    """ADMVW-02：admin 端点只读，写方法 405；管理员不能在他人会话续聊。"""

    async def test_admin_readonly_no_write(
        self, admin_and_token, admin_headers, user_a_and_token, project
    ):
        """admin 对 detail 路径 PATCH 与 DELETE → 405（只读，未实现写方法）。"""
        user_a, _ = user_a_and_token
        conv = await _acreate_conversation(project, owner=user_a, title="A-ro")
        detail_url = f"{ADMIN_LIST_URL}{conv.id}/"

        client = AsyncClient()
        patch_resp = await client.patch(
            detail_url,
            data=json.dumps({"title": "hacked by admin"}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert patch_resp.status_code == 405, (
            f"admin detail PATCH 应 405 只读（拿到 {patch_resp.status_code}）"
        )

        delete_resp = await client.delete(detail_url, headers=admin_headers)
        assert delete_resp.status_code == 405, (
            f"admin detail DELETE 应 405 只读（拿到 {delete_resp.status_code}）"
        )

    async def test_admin_readonly_no_continue(
        self, admin_and_token, admin_headers, user_a_and_token, project
    ):
        """plan-checker #2 显式断言：管理员不能在他人会话「续聊/发送」。

        对 admin detail 路径 POST（模拟在该会话发送消息）→ 405（端点不接受 POST
        send，只读）。这与 ADMVW-02「不可续聊」1:1 对应：admin 后台没有任何
        在他人会话上写入的入口。
        """
        user_a, _ = user_a_and_token
        conv = await _acreate_conversation(project, owner=user_a, title="A-nocontinue")

        client = AsyncClient()
        resp = await client.post(
            f"{ADMIN_LIST_URL}{conv.id}/",
            data=json.dumps({"content": "admin trying to continue"}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert resp.status_code == 405, (
            f"admin detail POST（续聊）应 405——admin 后台不可在他人会话写入"
            f"（拿到 {resp.status_code}）"
        )

    async def test_admin_no_stream_route(
        self, admin_and_token, admin_headers, user_a_and_token, project
    ):
        """plan-checker #2 显式断言（路由层）：admin 端点**不存在** stream 子路径。

        访问 `/api/admin/conversations/<id>/stream/` → 404（路由未挂载），固化
        「admin 后台没有流式续聊通道」的契约，杜绝后续误加 stream 端点。
        """
        user_a, _ = user_a_and_token
        conv = await _acreate_conversation(project, owner=user_a, title="A-nostream")

        client = AsyncClient()
        resp = await client.post(
            f"{ADMIN_LIST_URL}{conv.id}/stream/",
            data=json.dumps({"content": "admin stream attempt"}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert resp.status_code == 404, (
            f"admin stream 子路径应 404（路由不存在），拿到 {resp.status_code}"
        )


# ============================================================================
# ADMVW-03：fork 到管理员名下（深拷贝 + 改归属 + status=DRAFT，源会话不变）
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestAdminForkToOwn:
    """ADMVW-03：admin fork 任意会话为归属自己的整份副本。"""

    async def test_admin_fork_creates_admin_owned_copy(
        self, admin_and_token, admin_headers, user_a_and_token, project
    ):
        """admin POST fork 他人（user_a，含 N 条消息）会话 → 新会话
        `created_by == admin` 且消息条数 == N。"""
        admin, _ = admin_and_token
        user_a, _ = user_a_and_token
        conv, n = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-fork-src", n=3
        )

        client = AsyncClient()
        resp = await client.post(
            f"{ADMIN_LIST_URL}{conv.id}/fork/",
            data=json.dumps({}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert resp.status_code in {200, 201}, (
            f"admin fork 应 200/201（拿到 {resp.status_code}；Wave 0 端点未实现 → RED）"
        )

        new_id = resp.json()["conversation_id"]
        forked = await Conversation.objects.aget(id=new_id)
        assert forked.created_by_id == admin.id, "fork 副本应归属发起的管理员"

        msg_count = await Message.objects.filter(conversation_id=new_id).acount()
        assert msg_count == n, f"fork 副本应复制全部 {n} 条消息（拿到 {msg_count}）"

    async def test_admin_fork_status_and_source_intact(
        self, admin_and_token, admin_headers, user_a_and_token, project
    ):
        """fork 副本 status == DRAFT，且源会话 created_by / 消息条数不变。"""
        user_a, _ = user_a_and_token
        conv, n = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-fork-intact", n=2
        )

        client = AsyncClient()
        resp = await client.post(
            f"{ADMIN_LIST_URL}{conv.id}/fork/",
            data=json.dumps({}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert resp.status_code in {200, 201}, (
            f"admin fork 应 200/201（拿到 {resp.status_code}）"
        )

        new_id = resp.json()["conversation_id"]
        forked = await Conversation.objects.aget(id=new_id)
        assert forked.status == Conversation.Status.DRAFT, "fork 副本 status 应为 DRAFT"

        # 源会话不变
        source = await Conversation.objects.aget(id=conv.id)
        assert source.created_by_id == user_a.id, "源会话 owner 不应被改动"
        source_msgs = await Message.objects.filter(conversation_id=conv.id).acount()
        assert source_msgs == n, "源会话消息条数不应被改动"

    async def test_non_admin_fork_403(
        self, user_a_and_token, user_a_headers, project
    ):
        """非管理员（user_a）POST fork → 403。"""
        user_a, _ = user_a_and_token
        conv = await _acreate_conversation(project, owner=user_a, title="A-fork-403")

        client = AsyncClient()
        resp = await client.post(
            f"{ADMIN_LIST_URL}{conv.id}/fork/",
            data=json.dumps({}),
            content_type="application/json",
            headers=user_a_headers,
        )
        assert resp.status_code == 403, (
            f"非管理员调 admin fork 应 403（拿到 {resp.status_code}）"
        )

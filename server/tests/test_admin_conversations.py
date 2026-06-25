"""Phase 09 — 管理员只读会话后台 RED 验证脚手架（ADMVW-01/02/03）。

本文件钉死 Phase 9「独立、物理分离的只读会话管理后台」的可验证行为契约：

    - ADMVW-01：管理员（superuser）经 /api/admin/conversations/ 跨用户看到**全部**
      会话；非管理员 → 403；匿名 → 401/403。
    - ADMVW-02：admin 端点**只读**——detail 路径的写方法（PATCH/DELETE/POST-send）
      → 405；不存在 stream/send 子路由（不可在他人会话续聊）。
    - ADMVW-03：admin fork 把任意会话整份复制为一份归属当前管理员
      （created_by=admin、status=DRAFT、复制全部消息）的新会话；非管理员 fork → 403。

执行约定（Wave 0，RED-first）：
    - 生产代码（chat/admin_views.py + admin_urls.py + ConversationService.admin_* +
      AdminConversationListSerializer + /api/admin/ 挂载）**尚未实现**，故本文件的
      正向断言**预期全部 RED**——路由缺失时 Django 返回 404，断言期望的
      200/201/403/405 均落空。Wave 1（09-02 后端）落地后转 GREEN。
    - 文件必须可被 pytest 收集（``--co`` 通过）：仅 import 既有 chat.models，无
      对未实现模块的顶层依赖。
    - 403 vs 404 语义（09-RESEARCH §Pitfall 3）：admin gate 用 **403**（"仅超级管理员"，
      与 accounts admin 端点一致），不套用 Phase 8 普通用户越权的 404-everything。

回归基线：Phase 8 隔离套件 tests/test_conversation_isolation.py 不在本 plan 改动，
必须保持全绿（admin 端点是平行入口，不得削弱普通路径 owner 过滤，ISO-03）。

端点契约（09-RESEARCH §Architecture Patterns）：
    GET  /api/admin/conversations/                 列表（跨用户）
    GET  /api/admin/conversations/<uuid>/          只读详情 + 消息
    POST /api/admin/conversations/<uuid>/fork/     fork-to-own → {conversation_id}
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

pytestmark = pytest.mark.django_db


# ============================================================================
# Helpers — owner 可注入的 async 创建工具（仿 test_conversation_isolation.py）
# ============================================================================


def _conversation_has_created_by() -> bool:
    """探测 Conversation 是否已落地 created_by 字段（Phase 8 之后为 True）。"""
    return "created_by" in {f.name for f in Conversation._meta.get_fields()}


async def _acreate_conversation(project, *, owner=None, **kwargs):
    """async 创建会话；owner 不为空且字段已落地时写入 created_by。"""
    fields: dict = {
        "space": project,
        "title": kwargs.pop("title", "admvw-conv"),
        "model": kwargs.pop("model", ""),
    }
    if owner is not None and _conversation_has_created_by():
        fields["created_by"] = owner
    fields.update(kwargs)
    return await Conversation.objects.acreate(**fields)


async def _acreate_message(conversation, **kwargs):
    """async 创建一条消息（fork 复制计数用）。"""
    return await Message.objects.acreate(
        conversation=conversation,
        role=kwargs.pop("role", Message.Role.USER),
        content=kwargs.pop("content", "hello from owner"),
        **kwargs,
    )


async def _acreate_conversation_with_messages(project, *, owner, n=3, title="admvw"):
    """创建一个带 n 条消息的会话，返回 (conversation, n)。"""
    conv = await _acreate_conversation(project, owner=owner, title=title)
    for i in range(n):
        role = Message.Role.USER if i % 2 == 0 else Message.Role.ASSISTANT
        await _acreate_message(conv, role=role, content=f"msg-{i}")
    return conv, n


# ============================================================================
# Fixtures — admin（superuser）/ user_a / user_b（普通用户）各带 JWT
#
# 自包含定义（async 创建用户 + sync_to_async(RefreshToken.for_user) 铸 JWT），
# 形态与 conftest 既有 second_user_and_token / superuser_and_token 一致；
# 不依赖仅存在于 test_conversation_isolation.py 的 owner_* fixture。
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
def admin_user(admin_and_token):
    """管理员（superuser）模型实例。"""
    return admin_and_token[0]


@pytest.fixture
def admin_headers(admin_and_token):
    """管理员 Bearer Authorization 头。"""
    return {"authorization": f"Bearer {admin_and_token[1]}"}


@pytest.fixture
async def user_a_and_token(db):
    """普通用户 A + JWT access token。"""
    user = await User.objects.acreate_user(
        username="admvw_user_a",
        password="admvw-a-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


@pytest.fixture
def user_a(user_a_and_token):
    """普通用户 A。"""
    return user_a_and_token[0]


@pytest.fixture
def user_a_headers(user_a_and_token):
    """普通用户 A 的 Bearer 头。"""
    return {"authorization": f"Bearer {user_a_and_token[1]}"}


@pytest.fixture
async def user_b_and_token(db):
    """普通用户 B + JWT access token（另一 owner，跨用户可见性样本）。"""
    user = await User.objects.acreate_user(
        username="admvw_user_b",
        password="admvw-b-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


@pytest.fixture
def user_b(user_b_and_token):
    """普通用户 B。"""
    return user_b_and_token[0]


@pytest.fixture
def user_b_headers(user_b_and_token):
    """普通用户 B 的 Bearer 头。"""
    return {"authorization": f"Bearer {user_b_and_token[1]}"}


# ============================================================================
# ADMVW-01：管理员跨用户列表 / 鉴权
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestAdminList:
    """ADMVW-01：admin 看全部；非 admin 403；匿名拒绝。"""

    async def test_admin_list_sees_all_users(
        self, admin_headers, user_a, user_b, project
    ):
        """admin GET 列表 → 200，且响应覆盖 user_a 与 user_b 两个不同 owner。"""
        conv_a, _ = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-conv"
        )
        conv_b, _ = await _acreate_conversation_with_messages(
            project, owner=user_b, title="B-conv"
        )

        client = AsyncClient()
        resp = await client.get("/api/admin/conversations/", headers=admin_headers)
        assert resp.status_code == 200, (
            f"admin 列表应 200（拿到 {resp.status_code}；Wave 0 端点未实现 → 预期 RED）"
        )

        data = resp.json()
        items = data["results"] if isinstance(data, dict) and "results" in data else data
        conv_ids = {str(item["id"]) for item in items}
        assert str(conv_a.id) in conv_ids
        assert str(conv_b.id) in conv_ids

        # owner 集合应覆盖两个不同用户（跨用户可见）
        owner_ids = set()
        for item in items:
            owner = item.get("owner")
            if isinstance(owner, dict) and owner.get("id"):
                owner_ids.add(str(owner["id"]))
        assert str(user_a.id) in owner_ids
        assert str(user_b.id) in owner_ids

    async def test_non_admin_list_403(self, user_a_headers, user_a, project):
        """非管理员 GET admin 列表 → 403（IsSuperUser；明确 403，非 404）。"""
        await _acreate_conversation(project, owner=user_a, title="A-conv")

        client = AsyncClient()
        resp = await client.get("/api/admin/conversations/", headers=user_a_headers)
        assert resp.status_code == 403, (
            f"非管理员访问 admin 列表必须 403（拿到 {resp.status_code}）"
        )

    async def test_anonymous_denied(self, project):
        """匿名（无 Authorization）GET admin 列表 → 401/403（拒绝）。"""
        await _acreate_conversation(project, owner=None, title="open-conv")

        client = AsyncClient()
        resp = await client.get("/api/admin/conversations/")
        assert resp.status_code in {401, 403}, (
            f"匿名访问 admin 列表必须被拒（401/403），拿到 {resp.status_code}"
        )

    async def test_admin_list_invalid_owner_id_400(self, admin_headers, project):
        """非法 ?owner_id=garbage → 400（WR-01），而非 ORM 求值阶段 500。

        User.id 为 UUIDField，未校验的非 UUID owner_id 会在 filter 求值时抛
        ValueError 穿透成 500。view 层显式校验后应返回 400 清晰报错。
        """
        client = AsyncClient()
        resp = await client.get(
            "/api/admin/conversations/?owner_id=garbage", headers=admin_headers
        )
        assert resp.status_code == 400, (
            f"非法 owner_id 必须 400 而非 500（拿到 {resp.status_code}）"
        )

    async def test_admin_list_valid_owner_id_filters(
        self, admin_headers, user_a, user_b, project
    ):
        """合法 ?owner_id=<user_a.id> → 200，且仅返回该 owner 的会话（WR-01 不误伤正常路径）。"""
        conv_a, _ = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-filter"
        )
        await _acreate_conversation_with_messages(
            project, owner=user_b, title="B-filter"
        )

        client = AsyncClient()
        resp = await client.get(
            f"/api/admin/conversations/?owner_id={user_a.id}", headers=admin_headers
        )
        assert resp.status_code == 200, (
            f"合法 owner_id 应 200（拿到 {resp.status_code}）"
        )
        data = resp.json()
        items = data["results"] if isinstance(data, dict) and "results" in data else data
        conv_ids = {str(item["id"]) for item in items}
        assert str(conv_a.id) in conv_ids
        owner_ids = {
            str(item["owner"]["id"])
            for item in items
            if isinstance(item.get("owner"), dict) and item["owner"].get("id")
        }
        assert owner_ids == {str(user_a.id)}

    async def test_admin_detail_other_user(self, admin_headers, user_a, project):
        """admin GET 他人会话详情 → 200，响应含 messages 列表。"""
        conv, n = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-detail", n=2
        )

        client = AsyncClient()
        resp = await client.get(
            f"/api/admin/conversations/{conv.id}/", headers=admin_headers
        )
        assert resp.status_code == 200, (
            f"admin 看他人会话详情应 200（拿到 {resp.status_code}）"
        )
        body = resp.json()
        assert "messages" in body
        assert len(body["messages"]) == n


# ============================================================================
# ADMVW-02：只读 —— 写方法 405、无续聊/发送路径
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestAdminReadOnly:
    """ADMVW-02：admin 端点只读，不能在他人会话续聊/交互。"""

    async def test_admin_readonly_no_write(self, admin_headers, user_a, project):
        """admin 对 detail 路径 PATCH / DELETE → 405（未实现写方法，DRF 自动 405）。"""
        conv = await _acreate_conversation(project, owner=user_a, title="A-ro")

        client = AsyncClient()
        patch_resp = await client.patch(
            f"/api/admin/conversations/{conv.id}/",
            data=json.dumps({"title": "admin tried to edit"}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert patch_resp.status_code == 405, (
            f"admin PATCH 只读详情必须 405（拿到 {patch_resp.status_code}）"
        )

        delete_resp = await client.delete(
            f"/api/admin/conversations/{conv.id}/", headers=admin_headers
        )
        assert delete_resp.status_code == 405, (
            f"admin DELETE 只读详情必须 405（拿到 {delete_resp.status_code}）"
        )

    async def test_admin_cannot_continue_send(self, admin_headers, user_a, project):
        """ADMVW-02「不可续聊」显式钉死（plan-checker 警告 #2）：

        - POST 到 admin detail 路径（模拟「在他人会话直接发消息续聊」）→ 405
          （detail view 只实现 get，不接受 post-send）。
        - admin 端点**不存在** stream/send 子路由 → 404（路由层即无续聊入口）。
        """
        conv = await _acreate_conversation(project, owner=user_a, title="A-nosend")

        client = AsyncClient()
        # (a) 在 detail 路径 POST 一条消息（模拟续聊）→ 405（方法不允许）
        send_resp = await client.post(
            f"/api/admin/conversations/{conv.id}/",
            data=json.dumps({"content": "admin trying to continue chat"}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert send_resp.status_code == 405, (
            f"admin 在他人会话 detail POST 续聊必须 405（拿到 {send_resp.status_code}）"
        )

        # (b) admin 端点无 stream 子路由（续聊入口在路由层即不存在）→ 404
        stream_resp = await client.post(
            f"/api/admin/conversations/{conv.id}/stream/",
            data=json.dumps({"content": "stream from admin"}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert stream_resp.status_code == 404, (
            f"admin 端点不应存在 stream 续聊子路由（应 404，拿到 {stream_resp.status_code}）"
        )


# ============================================================================
# ADMVW-03：fork-to-own —— 归属管理员 + status=DRAFT + 复制消息 + 源不变
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestAdminFork:
    """ADMVW-03：admin fork 把他人会话整份复制为归属自己的新会话。"""

    async def test_admin_fork_creates_admin_owned_copy(
        self, admin_headers, admin_user, user_a, project
    ):
        """admin POST fork 他人会话 → 新会话 created_by==admin 且消息条数 == N。"""
        conv, n = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-fork-src", n=3
        )

        client = AsyncClient()
        resp = await client.post(
            f"/api/admin/conversations/{conv.id}/fork/",
            data=json.dumps({}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert resp.status_code in {200, 201}, (
            f"admin fork 应 200/201（拿到 {resp.status_code}）"
        )

        new_id = resp.json()["conversation_id"]
        forked = await Conversation.objects.aget(id=new_id)
        assert forked.created_by_id == admin_user.id, (
            "fork 副本必须归属发起的管理员（created_by=admin）"
        )

        forked_msg_count = await Message.objects.filter(conversation=forked).acount()
        assert forked_msg_count == n, (
            f"fork 副本应复制全部 {n} 条消息（拿到 {forked_msg_count}）"
        )

    async def test_admin_fork_status_and_source_intact(
        self, admin_headers, user_a, project
    ):
        """fork 副本 status==DRAFT；源会话 created_by 与消息条数不变。"""
        conv, n = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-fork-intact", n=2
        )
        source_owner_id = conv.created_by_id

        client = AsyncClient()
        resp = await client.post(
            f"/api/admin/conversations/{conv.id}/fork/",
            data=json.dumps({}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert resp.status_code in {200, 201}, (
            f"admin fork 应 200/201（拿到 {resp.status_code}）"
        )

        new_id = resp.json()["conversation_id"]
        forked = await Conversation.objects.aget(id=new_id)
        assert forked.status == Conversation.Status.DRAFT, (
            f"fork 副本 status 必须为 DRAFT（拿到 {forked.status}）"
        )

        # 源会话不受影响（owner 与消息条数不变）
        source = await Conversation.objects.aget(id=conv.id)
        assert source.created_by_id == source_owner_id
        source_msg_count = await Message.objects.filter(conversation=source).acount()
        assert source_msg_count == n

    async def test_admin_fork_copies_all_messages_consistently(
        self, admin_headers, user_a, project
    ):
        """WR-02：fork 原子复制后，副本消息与源在条数 / 顺序 / 内容上完全一致。"""
        conv, n = await _acreate_conversation_with_messages(
            project, owner=user_a, title="A-fork-consistent", n=4
        )

        client = AsyncClient()
        resp = await client.post(
            f"/api/admin/conversations/{conv.id}/fork/",
            data=json.dumps({}),
            content_type="application/json",
            headers=admin_headers,
        )
        assert resp.status_code in {200, 201}, (
            f"admin fork 应 200/201（拿到 {resp.status_code}）"
        )

        new_id = resp.json()["conversation_id"]
        forked = await Conversation.objects.aget(id=new_id)

        source_msgs = [
            (m.role, m.content)
            async for m in Message.objects.filter(conversation=conv).order_by("created_at")
        ]
        forked_msgs = [
            (m.role, m.content)
            async for m in Message.objects.filter(conversation=forked).order_by("created_at")
        ]
        assert len(forked_msgs) == n
        assert forked_msgs == source_msgs, (
            "fork 副本消息应与源在顺序 + 内容上逐条一致（原子整份复制）"
        )

    async def test_non_admin_fork_403(self, user_a_headers, user_a, project):
        """非管理员调 admin fork → 403。"""
        conv = await _acreate_conversation(project, owner=user_a, title="A-fork-403")

        client = AsyncClient()
        resp = await client.post(
            f"/api/admin/conversations/{conv.id}/fork/",
            data=json.dumps({}),
            content_type="application/json",
            headers=user_a_headers,
        )
        assert resp.status_code == 403, (
            f"非管理员调 admin fork 必须 403（拿到 {resp.status_code}）"
        )


# ============================================================================
# 回归保障显式声明：Phase 8 隔离套件是本期回归基线（不在本文件改动）。
# 此处不重复 25 路径断言（见 tests/test_conversation_isolation.py），仅以一条
# 轻量回归用例固化「普通路径 owner 隔离仍成立」的最小信号——admin 端点上线后
# 普通用户经 /api/chat/conversations/ 仍只看自己。
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestNormalPathIsolationRegression:
    """回归：admin 端点存在不削弱普通路径 owner 过滤（ISO-03 最小信号）。"""

    async def test_normal_list_still_owner_scoped(
        self, user_a_headers, user_a, user_b, project
    ):
        """普通 /api/chat/conversations/ 下 user_a 仍只看自己，不含 user_b。"""
        conv_a = await _acreate_conversation(project, owner=user_a, title="A-own")
        conv_b = await _acreate_conversation(project, owner=user_b, title="B-own")

        client = AsyncClient()
        resp = await client.get("/api/chat/conversations/", headers=user_a_headers)
        assert resp.status_code == 200
        ids = {str(item["id"]) for item in resp.json()}
        assert str(conv_a.id) in ids
        assert str(conv_b.id) not in ids

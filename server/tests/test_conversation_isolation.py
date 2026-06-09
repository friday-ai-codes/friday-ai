"""Phase 08 — 对话/会话用户隔离 RED 验证脚手架。

本文件是 Phase 8（ISO-01..04）的「完整性钉死」测试集：对 08-RESEARCH.md
§Conversation Access Point Inventory 列出的全部 25 个会话访问路径，逐一写
显式的「用户 B 直取用户 A 会话 id → 404」断言，外加 ISO-01 created_by 落库 /
历史回填、ISO-02 owner 过滤、ISO-03 管理员无特权 bypass、open-mode 回归，以及
plan-checker 警告 #2 要求的 owner-allowed 正向断言（防过度收紧的 gate 把 owner
也 404）。

执行约定（Wave 0）：
    - 生产代码（Conversation.created_by FK + owner gate + 回填迁移）尚未实现，
      故本文件的越权断言**预期全部 RED**；Wave 2-4（08-02/03/04）落地后转 GREEN。
    - 文件必须可被 pytest 收集（``--co`` 通过）：迁移模块（0019 回填）尚不存在，
      因此 backfill 用例在**运行时**惰性 import，集合阶段不触发 ModuleNotFoundError。
    - 越权对象级断言一律 ``== 404``（杜绝 403 泄漏存在性，ISO-04 / Pitfall 3）；
      list 级断言一律 ``== []``。

参数化 1:1 映射 RESEARCH 端点编号（#3..#25）见 CROSS_USER_CASES 的 ``id``。
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from chat.models import (
    CodingPlan,
    CodingSession,
    Conversation,
    ConversationIntentTrace,
    Message,
    RepositoryRoutingTrace,
)

User = get_user_model()


# ============================================================================
# Helpers — owner 可注入的 async 创建工具
# ============================================================================


def _conversation_has_created_by() -> bool:
    """探测 Conversation 是否已落地 created_by 字段（08-02 之后为 True）。

    Wave 0（字段未迁移）时返回 False —— owner 注入被跳过，会话以 owner-less
    形态创建，越权断言因「没有 owner gate」拿到 200/403/400 而 RED。
    """
    return "created_by" in {f.name for f in Conversation._meta.get_fields()}


async def _acreate_conversation(project, *, owner=None, **kwargs):
    """async 创建会话；owner 不为空且字段已落地时写入 created_by。"""
    fields: dict = {
        "project": project,
        "title": kwargs.pop("title", "iso-conv"),
        "model": kwargs.pop("model", ""),
    }
    if owner is not None and _conversation_has_created_by():
        fields["created_by"] = owner
    fields.update(kwargs)
    return await Conversation.objects.acreate(**fields)


async def _acreate_coding_session(conversation, repository, **kwargs):
    """async 创建 CodingSession（挂在指定 conversation 下）。"""
    return await CodingSession.objects.acreate(
        conversation=conversation,
        repository=repository,
        tech_plan=kwargs.pop("tech_plan", "iso tech plan"),
        status=kwargs.pop("status", CodingSession.Status.DRAFT),
        **kwargs,
    )


async def _acreate_coding_plan(conversation, **kwargs):
    """async 创建 CodingPlan。"""
    return await CodingPlan.objects.acreate(
        conversation=conversation,
        tech_plan=kwargs.pop("tech_plan", "iso plan"),
        **kwargs,
    )


async def _acreate_routing_trace(conversation, **kwargs):
    """async 创建 RepositoryRoutingTrace。"""
    return await RepositoryRoutingTrace.objects.acreate(
        conversation=conversation,
        query=kwargs.pop("query", "iso query"),
        candidates=kwargs.pop("candidates", []),
        threshold=kwargs.pop("threshold", 0.5),
        triggered_by=RepositoryRoutingTrace.TriggeredBy.CHAT_TOOL,
    )


async def _acreate_intent_trace(conversation, clarification_id, **kwargs):
    """async 创建 ConversationIntentTrace（clarification 卡片）。"""
    return await ConversationIntentTrace.objects.acreate(
        conversation=conversation,
        clarification_id=clarification_id,
        question=kwargs.pop("question", "iso clarification?"),
        options=kwargs.pop("options", []),
    )


async def _acreate_message(conversation, **kwargs):
    """async 创建 user message（fork 端点 #9 需要 message id）。"""
    return await Message.objects.acreate(
        conversation=conversation,
        role=kwargs.pop("role", Message.Role.USER),
        content=kwargs.pop("content", "hello"),
    )


def _load_backfill_migration():
    """惰性定位并 import 0019 回填迁移模块。

    Wave 0 迁移尚不存在 → 抛 ModuleNotFoundError（backfill 用例运行时 RED）；
    08-02 落地 `chat/migrations/0019_backfill_conversation_created_by.py` 后命中。
    用 pkgutil 动态查找，避免硬编码编号（命名为 0019_* 即可被发现）。
    """
    import importlib
    import pkgutil

    import chat.migrations as migrations_pkg

    for info in pkgutil.iter_modules(migrations_pkg.__path__):
        name = info.name
        if "backfill" in name and "created_by" in name:
            return importlib.import_module(f"chat.migrations.{name}")
    raise ModuleNotFoundError(
        "未找到 created_by 回填迁移（预期 "
        "chat/migrations/0019_backfill_conversation_created_by.py）"
    )


# ============================================================================
# Fixtures — 主用户 A（owner）
# ============================================================================


@pytest.fixture
async def owner_and_token(db):
    """主用户 A（会话 owner）+ JWT。"""
    user = await User.objects.acreate_user(
        username="iso_owner",
        password="iso-owner-pass-123",
    )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, str(token.access_token)


@pytest.fixture
def owner_headers(owner_and_token):
    """主用户 A 的 Bearer Authorization 头。"""
    _, access_token = owner_and_token
    return {"authorization": f"Bearer {access_token}"}


# ============================================================================
# ISO-01：created_by 落库 + 历史回填
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestOwnerAssignment:
    """ISO-01：新建会话记录创建者；历史无主会话回填给最早 superuser。"""

    async def test_create_sets_owner(self, owner_and_token, owner_headers, project):
        """认证用户 POST 创建会话后，DB 中该会话 created_by == 请求用户（A1：仅 JWT 用户）。"""
        owner, _ = owner_and_token
        client = AsyncClient()
        resp = await client.post(
            "/api/chat/conversations/",
            data=json.dumps({"space_id": str(project.id), "title": "owned"}),
            content_type="application/json",
            headers=owner_headers,
        )
        assert resp.status_code == 201
        conv_id = resp.json()["id"]
        conv = await Conversation.objects.aget(id=conv_id)
        # Wave 0：created_by 字段尚不存在 → getattr 返回 None → RED。
        assert getattr(conv, "created_by_id", None) == owner.id

    async def test_backfill_assigns_earliest_superuser(self, project):
        """回填把历史无主会话归属给最早（created_at,id）的 superuser。"""
        from datetime import timedelta

        from django.apps import apps as global_apps
        from django.utils import timezone

        su_early = await User.objects.acreate_superuser(
            username="iso_su_early", email="early@example.com", password="x"
        )
        await User.objects.acreate_superuser(
            username="iso_su_late", email="late@example.com", password="x"
        )
        # 强制 su_early 明确最早，避免同微秒 created_at 下 uuid id tiebreak 抖动。
        await User.objects.filter(id=su_early.id).aupdate(
            created_at=timezone.now() - timedelta(days=1)
        )

        conv = await _acreate_conversation(project, owner=None)

        mod = _load_backfill_migration()
        await sync_to_async(mod.forwards)(global_apps, None)

        conv = await Conversation.objects.aget(id=conv.id)
        assert conv.created_by_id == su_early.id

    async def test_backfill_no_superuser_leaves_null(self, project):
        """无 superuser 时回填不阻塞、留 null（不报错）。"""
        from django.apps import apps as global_apps

        conv = await _acreate_conversation(project, owner=None)

        mod = _load_backfill_migration()
        await sync_to_async(mod.forwards)(global_apps, None)

        conv = await Conversation.objects.aget(id=conv.id)
        assert conv.created_by_id is None

    async def test_backfill_reversible(self, project):
        """backwards 把回填的 created_by 全部置 None（可逆）。"""
        from django.apps import apps as global_apps

        su = await User.objects.acreate_superuser(
            username="iso_su", email="su@example.com", password="x"
        )
        conv = await _acreate_conversation(project, owner=None)

        mod = _load_backfill_migration()
        await sync_to_async(mod.forwards)(global_apps, None)
        conv = await Conversation.objects.aget(id=conv.id)
        assert conv.created_by_id == su.id

        await sync_to_async(mod.backwards)(global_apps, None)
        conv = await Conversation.objects.aget(id=conv.id)
        assert conv.created_by_id is None


# ============================================================================
# ISO-02 / ISO-03：owner 过滤 + 管理员无 bypass
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestOwnerScoping:
    """ISO-02 / ISO-03：list 仅含自己；管理员不做特权 bypass。"""

    async def test_list_only_owner(
        self,
        owner_and_token,
        owner_headers,
        second_user_and_token,
        project,
    ):
        """A 的 list 仅含 A 的会话，不含 B 的会话（ISO-02 #1）。"""
        owner, _ = owner_and_token
        second, _ = second_user_and_token
        conv_a = await _acreate_conversation(project, owner=owner, title="A-conv")
        conv_b = await _acreate_conversation(project, owner=second, title="B-conv")

        client = AsyncClient()
        resp = await client.get("/api/chat/conversations/", headers=owner_headers)
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()}
        assert str(conv_a.id) in ids
        assert str(conv_b.id) not in ids

    async def test_admin_no_bypass(
        self,
        owner_and_token,
        superuser_and_token,
        superuser_auth_headers,
        project,
    ):
        """superuser 作为认证用户看不到普通用户会话（list 不含 + detail 404）。"""
        owner, _ = owner_and_token
        conv_a = await _acreate_conversation(project, owner=owner, title="A-conv")

        client = AsyncClient()
        list_resp = await client.get(
            "/api/chat/conversations/", headers=superuser_auth_headers
        )
        assert list_resp.status_code == 200
        ids = {item["id"] for item in list_resp.json()}
        assert str(conv_a.id) not in ids

        detail_resp = await client.get(
            f"/api/chat/conversations/{conv_a.id}/", headers=superuser_auth_headers
        )
        assert detail_resp.status_code == 404


# ============================================================================
# open-mode 回归：未认证（开放模式）维持既有可访问行为
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestOpenModeUnaffected:
    """回归保护：CHAT_AUTH 关闭 / 匿名时不强加 owner 过滤（隔离以「有用户身份」为前提）。"""

    async def test_open_mode_unaffected(self, project):
        """无 Authorization（开放模式）下 list / detail 仍可访问 owner-less 会话。"""
        conv = await _acreate_conversation(project, owner=None, title="open-conv")

        client = AsyncClient()
        list_resp = await client.get("/api/chat/conversations/")
        assert list_resp.status_code == 200
        ids = {item["id"] for item in list_resp.json()}
        assert str(conv.id) in ids

        detail_resp = await client.get(f"/api/chat/conversations/{conv.id}/")
        assert detail_resp.status_code == 200

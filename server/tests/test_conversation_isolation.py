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
        "space": project,
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
        """回填把历史无主会话归属给最早（created_at,id）的 superuser。

        注意：accounts/0006 以 partial unique index 约束「最多一个 superuser」，
        故 DB 层只可能存在单个 superuser——「最早」在本系统中即「该唯一 superuser」；
        回填迁移按 order_by("created_at","id")（与 accounts/0005 字段一致，见 A2）取它。
        """
        from django.apps import apps as global_apps

        su = await User.objects.acreate_superuser(
            username="iso_su_earliest", email="earliest@example.com", password="x"
        )
        conv = await _acreate_conversation(project, owner=None)

        mod = _load_backfill_migration()
        await sync_to_async(mod.forwards)(global_apps, None)

        conv = await Conversation.objects.aget(id=conv.id)
        assert conv.created_by_id == su.id

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


# ============================================================================
# ISO-04：全 25 路径 cross-user-denied（404）
#
# CROSS_USER_CASES 与 08-RESEARCH.md §Conversation Access Point Inventory
# 1:1 映射（id 标注端点编号 #3..#25），供审计核对完整性。对象级越权一律
# 断言 == 404（杜绝 403，ISO-04 / Pitfall 3）。
#
# 编号分布：
#   A 直接会话端点  #3-#12（#1 list、#2 create 见 ISO-02/ISO-01 用例）
#   B SSE 流式      #10′（test_stream_cross_user_404 单列：流打开前 404）
#   C coding 关联   #13-#23（#13/#20 list-scoping 单列断言 []）
#   D trace/澄清    #24-#25（当前已 404；加 owner gate 后仍 404）
# 说明：#11 interrupt / #24 override / #25 clarification 在 Wave 0 即返回 404
#   （无活跃 run / 既有 has_project_access 跨用户 404），其余 Wave 0 RED。
# ============================================================================


# (id, kind, method, path, body)
# body 取值：dict 直传；{} 空体；None 无体；"<...>" 运行时按 repository 填充。
CROSS_USER_CASES = [
    # --- A. 直接会话端点 ---
    {"id": "#3 conversation-detail GET", "kind": "conversation", "method": "get",
     "path": "/api/chat/conversations/{cid}/", "body": None},
    {"id": "#4 conversation-detail DELETE", "kind": "conversation", "method": "delete",
     "path": "/api/chat/conversations/{cid}/", "body": None},
    {"id": "#5 conversation-detail PATCH", "kind": "conversation", "method": "patch",
     "path": "/api/chat/conversations/{cid}/", "body": {"title": "hacked"}},
    {"id": "#6 conversation-preflight GET", "kind": "conversation", "method": "get",
     "path": "/api/chat/conversations/{cid}/preflight/", "body": None},
    {"id": "#7 conversation-runtime GET", "kind": "conversation", "method": "get",
     "path": "/api/chat/conversations/{cid}/runtime/", "body": None},
    {"id": "#8 conversation-messages-delete DELETE", "kind": "conversation", "method": "delete",
     "path": "/api/chat/conversations/{cid}/messages/?before_id={bid}", "body": None},
    {"id": "#9 conversation-message-fork POST", "kind": "fork", "method": "post",
     "path": "/api/chat/conversations/{cid}/messages/{mid}/fork/", "body": {"content": "edited by B"}},
    {"id": "#10 conversation-stream POST", "kind": "conversation", "method": "post",
     "path": "/api/chat/conversations/{cid}/stream/", "body": {"content": "hi from B"}},
    {"id": "#11 conversation-interrupt POST", "kind": "conversation", "method": "post",
     "path": "/api/chat/conversations/{cid}/interrupt/", "body": {}},
    {"id": "#12 conversation-export-to-feishu POST", "kind": "conversation", "method": "post",
     "path": "/api/chat/conversations/{cid}/export-to-feishu/", "body": "<message_ids>"},
    # --- C. coding-session / coding-plan 关联端点 ---
    {"id": "#14 coding-session-detail GET", "kind": "coding_session", "method": "get",
     "path": "/api/chat/coding-sessions/{sid}/", "body": None},
    {"id": "#15 coding-session-confirm POST", "kind": "coding_session", "method": "post",
     "path": "/api/chat/coding-sessions/{sid}/confirm/", "body": {}},
    {"id": "#16 coding-session-commit-confirm GET", "kind": "coding_session", "method": "get",
     "path": "/api/chat/coding-sessions/{sid}/commit-confirm/", "body": None},
    {"id": "#17 coding-session-pr-confirm GET", "kind": "coding_session", "method": "get",
     "path": "/api/chat/coding-sessions/{sid}/pr-confirm/", "body": None},
    {"id": "#18 coding-session-conflict-check GET", "kind": "coding_session", "method": "get",
     "path": "/api/chat/coding-sessions/{sid}/conflict-check/", "body": None},
    {"id": "#19 coding-session-diff-summary GET", "kind": "coding_session", "method": "get",
     "path": "/api/chat/coding-sessions/{sid}/diff-summary/", "body": None},
    {"id": "#21 coding-plan-detail GET", "kind": "coding_plan", "method": "get",
     "path": "/api/chat/coding-plans/{pid}/", "body": None},
    {"id": "#22 coding-plan-sessions-batch POST", "kind": "coding_plan", "method": "post",
     "path": "/api/chat/coding-plans/{pid}/sessions/", "body": "<repo_ids>"},
    {"id": "#23 coding-plan-export-to-feishu POST", "kind": "coding_plan", "method": "post",
     "path": "/api/chat/coding-plans/{pid}/export-to-feishu/", "body": {}},
    # --- D. trace / clarification 关联端点 ---
    {"id": "#24 routing-trace-manual-override POST", "kind": "routing_trace", "method": "post",
     "path": "/api/chat/routing-traces/{tid}/override/", "body": "<candidates>"},
    {"id": "#25 clarification-answer POST", "kind": "clarification", "method": "post",
     "path": "/api/chat/clarifications/{clar}/answer/", "body": {"freeform_text": "B answer"}},
]


def _resolve_body(body, repository):
    """把 CROSS_USER_CASES 里的 body 占位符按 repository 填充为合法请求体。

    合法请求体很关键：若 body 非法导致序列化 400，本意（owner gate 404）会被
    400 掩盖——Wave 0 仍 RED（非 404），但实现落地后 owner gate 必须在序列化
    通过后命中 404，故 body 必须能过序列化校验。
    """
    if body == "<message_ids>":
        return {"message_ids": [str(uuid4())], "title": "iso export"}
    if body == "<repo_ids>":
        return {"repository_ids": [str(repository.id)]}
    if body == "<candidates>":
        return {"candidates": [{"repository_id": str(repository.id), "selected": True}]}
    return body


@pytest.mark.django_db(transaction=True)
class TestCrossUserDenied:
    """ISO-04：用户 B 直取用户 A 的会话/关联资源 id → 404（全 25 路径）。"""

    @pytest.mark.parametrize(
        "case", CROSS_USER_CASES, ids=[c["id"] for c in CROSS_USER_CASES]
    )
    async def test_cross_user_denied(
        self, case, owner_and_token, second_auth_headers, project, repository
    ):
        """A 建资源，B 携带自己的 JWT 访问该 id → 必须 404（不可为 403/200）。"""
        owner, _ = owner_and_token
        conv = await _acreate_conversation(project, owner=owner)
        fmt: dict = {"cid": conv.id, "bid": uuid4()}

        kind = case["kind"]
        if kind == "coding_session":
            sess = await _acreate_coding_session(conv, repository)
            fmt["sid"] = sess.id
        elif kind == "coding_plan":
            plan = await _acreate_coding_plan(conv)
            fmt["pid"] = plan.id
        elif kind == "routing_trace":
            trace = await _acreate_routing_trace(conv)
            fmt["tid"] = trace.id
        elif kind == "clarification":
            clar_id = uuid4().hex
            await _acreate_intent_trace(conv, clar_id)
            fmt["clar"] = clar_id
        elif kind == "fork":
            msg = await _acreate_message(conv)
            fmt["mid"] = msg.id

        url = case["path"].format(**fmt)
        body = _resolve_body(case["body"], repository)

        client = AsyncClient()
        method = getattr(client, case["method"])
        kwargs: dict = {"headers": second_auth_headers}
        if body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = "application/json"
        resp = await method(url, **kwargs)

        assert resp.status_code == 404, (
            f"{case['id']}: 跨用户访问必须返回 404（拿到 {resp.status_code}）"
        )

    async def test_stream_cross_user_404(
        self, owner_and_token, second_auth_headers, project
    ):
        """#10′ SSE：B POST A 会话 stream → 在流打开前返回 HTTP 404，而非 200 流内 error。"""
        owner, _ = owner_and_token
        conv = await _acreate_conversation(project, owner=owner)

        client = AsyncClient()
        resp = await client.post(
            f"/api/chat/conversations/{conv.id}/stream/",
            data=json.dumps({"content": "hi from B"}),
            content_type="application/json",
            headers=second_auth_headers,
        )
        # 必须是干净的 HTTP 404，而非 200 的 text/event-stream
        assert resp.status_code == 404
        assert not getattr(resp, "streaming", False)

    async def test_404_indistinguishable(
        self, owner_and_token, second_auth_headers, project
    ):
        """ISO-04：B 访问 A 真实会话 id 与不存在随机 uuid，状态码/响应体一致（不泄漏存在性）。"""
        owner, _ = owner_and_token
        conv = await _acreate_conversation(project, owner=owner)

        client = AsyncClient()
        real = await client.get(
            f"/api/chat/conversations/{conv.id}/", headers=second_auth_headers
        )
        missing = await client.get(
            f"/api/chat/conversations/{uuid4()}/", headers=second_auth_headers
        )
        assert real.status_code == 404
        assert missing.status_code == 404
        assert real.json() == missing.json()

    async def test_list_scoping_coding(
        self, owner_and_token, second_auth_headers, project, repository
    ):
        """#13 / #20 list-scoping：B 传 A 的 conversation_id → 返回 []（不列他人）。"""
        owner, _ = owner_and_token
        conv = await _acreate_conversation(project, owner=owner)
        await _acreate_coding_session(conv, repository)
        await _acreate_coding_plan(conv)

        client = AsyncClient()
        sess_resp = await client.get(
            f"/api/chat/coding-sessions/?conversation_id={conv.id}",
            headers=second_auth_headers,
        )
        assert sess_resp.status_code == 200
        assert sess_resp.json() == []

        plan_resp = await client.get(
            f"/api/chat/coding-plans/?conversation_id={conv.id}",
            headers=second_auth_headers,
        )
        assert plan_resp.status_code == 200
        assert plan_resp.json() == []


# ============================================================================
# owner-allowed 正向断言（plan-checker 警告 #2）
#
# 对象级主路径（detail/runtime/patch/delete/stream/fork）owner 访问自己会话
# 不应被 owner gate 误伤成 404 —— 断言 != 404，从而「过度收紧把 owner 也 404」
# 的实现会在此处被抓住，而非仅靠回归套件。
# ============================================================================


OWNER_ALLOWED_CASES = [
    {"id": "#3 detail owner-allowed", "kind": "conversation", "method": "get",
     "path": "/api/chat/conversations/{cid}/", "body": None},
    {"id": "#7 runtime owner-allowed", "kind": "conversation", "method": "get",
     "path": "/api/chat/conversations/{cid}/runtime/", "body": None},
    {"id": "#5 patch owner-allowed", "kind": "conversation", "method": "patch",
     "path": "/api/chat/conversations/{cid}/", "body": {"title": "renamed by owner"}},
    {"id": "#4 delete owner-allowed", "kind": "conversation", "method": "delete",
     "path": "/api/chat/conversations/{cid}/", "body": None},
    {"id": "#10 stream owner-allowed", "kind": "conversation", "method": "post",
     "path": "/api/chat/conversations/{cid}/stream/", "body": {"content": "hi"}},
    {"id": "#9 fork owner-allowed", "kind": "fork", "method": "post",
     "path": "/api/chat/conversations/{cid}/messages/{mid}/fork/", "body": {"content": "edited by owner"}},
]


@pytest.mark.django_db(transaction=True)
class TestOwnerCanAccess:
    """ISO-02 正向：owner 访问自己会话的对象级主路径不被 owner gate 误伤成 404。"""

    @pytest.mark.parametrize(
        "case", OWNER_ALLOWED_CASES, ids=[c["id"] for c in OWNER_ALLOWED_CASES]
    )
    async def test_owner_can_access(self, case, owner_and_token, owner_headers, project):
        """owner 自己的会话主路径不应返回 404（防过度收紧的 gate）。"""
        owner, _ = owner_and_token
        conv = await _acreate_conversation(project, owner=owner)
        fmt: dict = {"cid": conv.id}
        if case["kind"] == "fork":
            msg = await _acreate_message(conv)
            fmt["mid"] = msg.id

        url = case["path"].format(**fmt)
        client = AsyncClient()
        method = getattr(client, case["method"])
        kwargs: dict = {"headers": owner_headers}
        if case["body"] is not None:
            kwargs["data"] = json.dumps(case["body"])
            kwargs["content_type"] = "application/json"
        resp = await method(url, **kwargs)

        assert resp.status_code != 404, (
            f"{case['id']}: owner 自己的会话不应返回 404（拿到 {resp.status_code}）"
        )


# ============================================================================
# CR-01 回归：fork 必须继承源对话 owner，避免 fork 出 null-owner 孤儿
#
# 既有 #9 fork owner-allowed 仅断言 fork POST != 404，未覆盖「fork 出的新会话
# 后续是否可被 owner 访问」。这里钉死：owner fork 自己会话后，
#   - 同一 owner 能在 list 看到该 fork，且 GET detail == 200；
#   - 另一用户 GET 该 fork == 404（隔离仍成立）。
# 修复前（fork 不写 created_by）该 fork 是 null-owner，owner 自己 detail 404 → RED。
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestForkInheritsOwner:
    """CR-01：fork 继承源对话 owner，owner 可访问自己的 fork，他人 404。"""

    async def _create_fork(self, client, conv, headers):
        """owner 通过 fork 端点对自己会话的 user message 派生分支，返回 fork id。"""
        msg = await _acreate_message(conv)
        resp = await client.post(
            f"/api/chat/conversations/{conv.id}/messages/{msg.id}/fork/",
            data=json.dumps({"content": "edited by owner"}),
            content_type="application/json",
            headers=headers,
        )
        assert resp.status_code == 201, (
            f"owner fork 自己会话应 201（拿到 {resp.status_code}）"
        )
        return resp.json()["id"]

    async def test_owner_can_access_own_fork(
        self, owner_and_token, owner_headers, project
    ):
        """owner fork 自己会话后，DB 中 fork.created_by == owner，
        且 owner 能在 list 看到并 GET detail 200（CR-01 修复核心）。"""
        owner, _ = owner_and_token
        conv = await _acreate_conversation(project, owner=owner)

        client = AsyncClient()
        forked_id = await self._create_fork(client, conv, owner_headers)

        # 落库 owner 继承自源会话
        forked = await Conversation.objects.aget(id=forked_id)
        assert forked.created_by_id == owner.id

        # owner 的 list 含该 fork
        list_resp = await client.get("/api/chat/conversations/", headers=owner_headers)
        assert list_resp.status_code == 200
        ids = {item["id"] for item in list_resp.json()}
        assert forked_id in ids

        # owner GET fork detail == 200（修复前为 404）
        detail_resp = await client.get(
            f"/api/chat/conversations/{forked_id}/", headers=owner_headers
        )
        assert detail_resp.status_code == 200

    async def test_other_user_cannot_access_fork(
        self, owner_and_token, owner_headers, second_auth_headers, project
    ):
        """owner fork 自己会话后，另一用户 GET 该 fork == 404（隔离仍成立）。"""
        owner, _ = owner_and_token
        conv = await _acreate_conversation(project, owner=owner)

        client = AsyncClient()
        forked_id = await self._create_fork(client, conv, owner_headers)

        detail_resp = await client.get(
            f"/api/chat/conversations/{forked_id}/", headers=second_auth_headers
        )
        assert detail_resp.status_code == 404

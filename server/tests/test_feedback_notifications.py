"""反馈 + 站内信模块测试。

覆盖：
- 反馈创建 / owner-scoped 列表 / 详情越权 404；
- 管理端 IsSuperUser 守卫、回复触发站内信、状态变更触发站内信 + resolved_at；
- 站内信列表 / 未读数 / 标记已读 / 全部已读 / owner 隔离；
- 附件校验（图片/视频 magic-bytes、超限、非法类型）与本地存储；
- WS JWTCookieAuthMiddleware 从 cookie 解析 access_token 填充 scope["user"]。

端点测试用 AsyncClient + Bearer JWT（CookieJWTAuthentication 兜底 Authorization 头），
与 test_conversation_isolation.py 同范式。
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from rest_framework_simplejwt.tokens import RefreshToken

from feedback.models import Feedback, FeedbackReply
from notifications.models import Notification

User = get_user_model()


# ============================================================================
# Helpers
# ============================================================================


async def _make_user_and_headers(
    *, username: str, superuser: bool = False
) -> tuple[object, dict[str, str]]:
    """异步创建用户并铸 JWT，返回 (user, Bearer 头 dict)。"""
    if superuser:
        user = await User.objects.acreate_superuser(
            username=username, email=f"{username}@test.local", password="pass-12345"
        )
    else:
        user = await User.objects.acreate_user(
            username=username, email=f"{username}@test.local", password="pass-12345"
        )
    token = await sync_to_async(RefreshToken.for_user)(user)
    return user, {"authorization": f"Bearer {token.access_token}"}


async def _create_feedback_via_api(client: AsyncClient, headers: dict, **overrides) -> dict:
    payload = {
        "category": "bug",
        "title": "登录失败",
        "content": "点击登录无反应，见 https://feishu.cn/docx/abc **加粗**",
        **overrides,
    }
    resp = await client.post(
        "/api/feedback/",
        data=json.dumps(payload),
        content_type="application/json",
        headers=headers,
    )
    assert resp.status_code == 201, resp.content
    return resp.json()


# ============================================================================
# 反馈：创建 / owner 列表 / 详情隔离
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestFeedbackOwnerScope:
    async def test_create_and_owner_list(self):
        _, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        _, headers_b = await _make_user_and_headers(username=f"fb_{uuid4().hex[:6]}")
        client = AsyncClient()

        created = await _create_feedback_via_api(client, headers_a)
        assert created["category"] == "bug"
        # markdown 原文应原样保留（不在后端转义/渲染）
        assert "**加粗**" in created["content"]

        list_a = await client.get("/api/feedback/", headers=headers_a)
        assert list_a.status_code == 200
        ids_a = {item["id"] for item in list_a.json()["items"]}
        assert created["id"] in ids_a

        # B 看不到 A 的反馈
        list_b = await client.get("/api/feedback/", headers=headers_b)
        assert list_b.status_code == 200
        ids_b = {item["id"] for item in list_b.json()["items"]}
        assert created["id"] not in ids_b

    async def test_detail_cross_user_404(self):
        _, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        _, headers_b = await _make_user_and_headers(username=f"fb_{uuid4().hex[:6]}")
        client = AsyncClient()

        created = await _create_feedback_via_api(client, headers_a)
        resp_b = await client.get(f"/api/feedback/{created['id']}/", headers=headers_b)
        assert resp_b.status_code == 404

    async def test_create_records_conversation_context(self):
        _, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        client = AsyncClient()
        conv_id = str(uuid4())
        created = await _create_feedback_via_api(
            client,
            headers_a,
            page_url="/chat?conversation=" + conv_id,
            conversation_id=conv_id,
        )
        assert created["conversation_id"] == conv_id
        assert created["page_url"].startswith("/chat")


# ============================================================================
# 管理端：权限 + 回复/状态触发站内信
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestFeedbackAdmin:
    async def test_admin_list_requires_superuser(self):
        _, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        client = AsyncClient()
        resp = await client.get("/api/admin/feedback/", headers=headers_a)
        assert resp.status_code == 403

    async def test_superuser_sees_all_feedback(self):
        _, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        _, headers_admin = await _make_user_and_headers(
            username=f"adm_{uuid4().hex[:6]}", superuser=True
        )
        client = AsyncClient()
        created = await _create_feedback_via_api(client, headers_a)

        resp = await client.get("/api/admin/feedback/", headers=headers_admin)
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()["items"]}
        assert created["id"] in ids

    async def test_admin_reply_creates_reply_and_notification(self):
        user_a, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        _, headers_admin = await _make_user_and_headers(
            username=f"adm_{uuid4().hex[:6]}", superuser=True
        )
        client = AsyncClient()
        created = await _create_feedback_via_api(client, headers_a)

        resp = await client.post(
            f"/api/admin/feedback/{created['id']}/reply/",
            data=json.dumps({"content": "已修复，请重试 **谢谢**"}),
            content_type="application/json",
            headers=headers_admin,
        )
        assert resp.status_code == 201, resp.content
        body = resp.json()
        assert len(body["replies"]) == 1
        assert body["replies"][0]["is_admin"] is True

        reply_exists = await FeedbackReply.objects.filter(
            feedback_id=created["id"], is_admin=True
        ).aexists()
        assert reply_exists

        notif = await Notification.objects.filter(
            recipient_id=user_a.id, type=Notification.Type.FEEDBACK_REPLY
        ).afirst()
        assert notif is not None
        assert "谢谢" in notif.body
        assert notif.link == f"/notifications?tab=feedback&fid={created['id']}"

    async def test_admin_reply_empty_content_400(self):
        _, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        _, headers_admin = await _make_user_and_headers(
            username=f"adm_{uuid4().hex[:6]}", superuser=True
        )
        client = AsyncClient()
        created = await _create_feedback_via_api(client, headers_a)
        resp = await client.post(
            f"/api/admin/feedback/{created['id']}/reply/",
            data=json.dumps({"content": "   "}),
            content_type="application/json",
            headers=headers_admin,
        )
        assert resp.status_code == 400

    async def test_admin_status_change_notifies_and_sets_resolved(self):
        user_a, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        _, headers_admin = await _make_user_and_headers(
            username=f"adm_{uuid4().hex[:6]}", superuser=True
        )
        client = AsyncClient()
        created = await _create_feedback_via_api(client, headers_a)

        resp = await client.patch(
            f"/api/admin/feedback/{created['id']}/",
            data=json.dumps({"status": "resolved"}),
            content_type="application/json",
            headers=headers_admin,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"

        fb = await Feedback.objects.aget(id=created["id"])
        assert fb.resolved_at is not None

        notif = await Notification.objects.filter(
            recipient_id=user_a.id, type=Notification.Type.FEEDBACK_STATUS
        ).afirst()
        assert notif is not None

    async def test_admin_status_invalid_400(self):
        _, headers_a = await _make_user_and_headers(username=f"fa_{uuid4().hex[:6]}")
        _, headers_admin = await _make_user_and_headers(
            username=f"adm_{uuid4().hex[:6]}", superuser=True
        )
        client = AsyncClient()
        created = await _create_feedback_via_api(client, headers_a)
        resp = await client.patch(
            f"/api/admin/feedback/{created['id']}/",
            data=json.dumps({"status": "bogus"}),
            content_type="application/json",
            headers=headers_admin,
        )
        assert resp.status_code == 400


# ============================================================================
# 站内信：列表 / 未读 / 已读 / owner 隔离
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestNotifications:
    async def test_list_unread_and_mark_read(self):
        user_a, headers_a = await _make_user_and_headers(username=f"na_{uuid4().hex[:6]}")
        n1 = await Notification.objects.acreate(
            recipient_id=user_a.id, type="system", title="t1", body="b1"
        )
        await Notification.objects.acreate(
            recipient_id=user_a.id, type="system", title="t2", body="b2"
        )
        client = AsyncClient()

        list_resp = await client.get("/api/notifications/", headers=headers_a)
        assert list_resp.status_code == 200
        assert list_resp.json()["unread"] == 2

        count_resp = await client.get("/api/notifications/unread-count/", headers=headers_a)
        assert count_resp.json()["unread"] == 2

        read_resp = await client.post(f"/api/notifications/{n1.id}/read/", headers=headers_a)
        assert read_resp.status_code == 200
        assert read_resp.json()["is_read"] is True

        count_resp2 = await client.get("/api/notifications/unread-count/", headers=headers_a)
        assert count_resp2.json()["unread"] == 1

    async def test_mark_all_read(self):
        user_a, headers_a = await _make_user_and_headers(username=f"na_{uuid4().hex[:6]}")
        for i in range(3):
            await Notification.objects.acreate(
                recipient_id=user_a.id, type="system", title=f"t{i}", body="b"
            )
        client = AsyncClient()
        resp = await client.post("/api/notifications/read-all/", headers=headers_a)
        assert resp.status_code == 200
        assert resp.json()["updated"] == 3
        remaining = await Notification.objects.filter(
            recipient_id=user_a.id, read_at__isnull=True
        ).acount()
        assert remaining == 0

    async def test_cross_user_read_404(self):
        user_a, _ = await _make_user_and_headers(username=f"na_{uuid4().hex[:6]}")
        _, headers_b = await _make_user_and_headers(username=f"nb_{uuid4().hex[:6]}")
        notif = await Notification.objects.acreate(
            recipient_id=user_a.id, type="system", title="t", body="b"
        )
        client = AsyncClient()
        resp = await client.post(f"/api/notifications/{notif.id}/read/", headers=headers_b)
        assert resp.status_code == 404

    async def test_list_only_own(self):
        user_a, headers_a = await _make_user_and_headers(username=f"na_{uuid4().hex[:6]}")
        user_b, _ = await _make_user_and_headers(username=f"nb_{uuid4().hex[:6]}")
        await Notification.objects.acreate(
            recipient_id=user_a.id, type="system", title="A", body="b"
        )
        await Notification.objects.acreate(
            recipient_id=user_b.id, type="system", title="B", body="b"
        )
        client = AsyncClient()
        resp = await client.get("/api/notifications/", headers=headers_a)
        titles = {item["title"] for item in resp.json()["items"]}
        assert "A" in titles
        assert "B" not in titles


# ============================================================================
# 附件校验 + 存储（单元）
# ============================================================================


class TestAttachmentValidation:
    def test_validate_image_ok(self):
        from feedback.attachments import validate_attachment_bytes

        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        kind, mime, size = validate_attachment_bytes(png, declared_mime_type="image/png")
        assert kind == "image"
        assert mime == "image/png"
        assert size == len(png)

    def test_validate_video_mp4_ok(self):
        from feedback.attachments import validate_attachment_bytes

        mp4 = b"\x00\x00\x00\x18ftypisom" + b"0" * 32
        kind, mime, _ = validate_attachment_bytes(mp4, declared_mime_type="video/mp4")
        assert kind == "video"
        assert mime == "video/mp4"

    def test_validate_video_webm_ok(self):
        from feedback.attachments import validate_attachment_bytes

        webm = b"\x1a\x45\xdf\xa3" + b"0" * 64
        kind, mime, _ = validate_attachment_bytes(webm, declared_mime_type="video/webm")
        assert kind == "video"
        assert mime == "video/webm"

    def test_image_too_large_rejected(self):
        from feedback.attachments import (
            MAX_IMAGE_BYTES,
            AttachmentValidationError,
            validate_attachment_bytes,
        )

        big = b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_IMAGE_BYTES + 1)
        with pytest.raises(AttachmentValidationError) as exc:
            validate_attachment_bytes(big, declared_mime_type="image/png")
        assert exc.value.code == "image_too_large"

    def test_unsupported_type_rejected(self):
        from feedback.attachments import (
            AttachmentValidationError,
            validate_attachment_bytes,
        )

        with pytest.raises(AttachmentValidationError) as exc:
            validate_attachment_bytes(b"not-a-media-file", declared_mime_type="text/plain")
        assert exc.value.code == "unsupported_type"

    def test_store_and_read_roundtrip(self, tmp_path, monkeypatch):
        from django.conf import settings

        from feedback import attachments as att

        monkeypatch.setattr(settings, "DATA_DIR", tmp_path, raising=False)
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        stored = att.store_attachment_bytes(png, declared_mime_type="image/png")
        assert stored.storage_ref.startswith("feedback_attachments/")
        assert stored.kind == "image"
        assert att.read_attachment_bytes(stored.storage_ref) == png

    def test_read_path_traversal_blocked(self, tmp_path, monkeypatch):
        from django.conf import settings

        from feedback import attachments as att

        monkeypatch.setattr(settings, "DATA_DIR", tmp_path, raising=False)
        with pytest.raises(att.AttachmentValidationError) as exc:
            att.read_attachment_bytes("feedback_attachments/../../etc/passwd")
        assert exc.value.code == "invalid_storage_ref"


# ============================================================================
# WS 鉴权中间件
# ============================================================================


@pytest.mark.django_db(transaction=True)
class TestJWTCookieAuthMiddleware:
    async def test_authenticates_with_cookie(self):
        from notifications.middleware import JWTCookieAuthMiddleware

        user = await User.objects.acreate_user(
            username=f"ws_{uuid4().hex[:6]}", password="pass-12345"
        )
        token = await sync_to_async(RefreshToken.for_user)(user)
        access = str(token.access_token)

        captured: dict = {}

        async def app(scope, receive, send):
            captured["user"] = scope["user"]

        mw = JWTCookieAuthMiddleware(app)
        scope = {
            "type": "websocket",
            "headers": [(b"cookie", f"access_token={access}".encode())],
        }
        await mw(scope, None, None)
        assert getattr(captured["user"], "id", None) == user.id

    async def test_anonymous_without_cookie(self):
        from django.contrib.auth.models import AnonymousUser

        from notifications.middleware import JWTCookieAuthMiddleware

        captured: dict = {}

        async def app(scope, receive, send):
            captured["user"] = scope["user"]

        mw = JWTCookieAuthMiddleware(app)
        scope = {"type": "websocket", "headers": []}
        await mw(scope, None, None)
        assert isinstance(captured["user"], AnonymousUser)

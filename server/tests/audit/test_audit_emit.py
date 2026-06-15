"""审计 emit 双入口 + actor 上下文 + 中间件测试。

覆盖 AUDIT-02（请求上下文 actor 提取）和 AUDIT-03（emit 双入口）的行为测试。
"""

import asyncio
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from audit.context import AuditActor, get_current_actor, reset_current_actor, set_current_actor
from audit.models import AuditEvent

User = get_user_model()


# === Task 1: contextvars + middleware tests ===


class TestAuditContextVars:
    """测试 contextvars actor 存取。"""

    def test_get_current_actor_returns_default_when_not_set(self):
        """get_current_actor() 在未设置时返回 system 默认值。"""
        # 确保 contextvar 未设置（新协程/线程）
        actor = get_current_actor()
        assert actor.actor_type == "system"
        assert actor.actor_id == "system"

    def test_set_current_actor_and_get(self):
        """set_current_actor 后 get_current_actor 返回设置的值。"""
        actor = AuditActor(actor_type="user", actor_id="42", actor_display="alice")
        token = set_current_actor(actor)
        try:
            result = get_current_actor()
            assert result.actor_type == "user"
            assert result.actor_id == "42"
            assert result.actor_display == "alice"
        finally:
            reset_current_actor(token)

    def test_reset_current_actor_restores_default(self):
        """reset_current_actor 后 get_current_actor 恢复默认值。"""
        actor = AuditActor(actor_type="pat", actor_id="abc123", actor_display="cli-token")
        token = set_current_actor(actor)
        reset_current_actor(token)
        result = get_current_actor()
        assert result.actor_type == "system"
        assert result.actor_id == "system"

    def test_audit_actor_frozen(self):
        """AuditActor 是 frozen dataclass，不可变。"""
        actor = AuditActor(actor_type="user", actor_id="1", actor_display="test")
        with pytest.raises(AttributeError):
            actor.actor_type = "system"


class TestAuditContextMiddleware:
    """测试 AuditContextMiddleware ASGI 中间件。"""

    @pytest.mark.django_db
    def test_jwt_authenticated_request_extracts_user_actor(self):
        """JWT 认证请求 → actor_type='user', actor_id=user.pk, actor_display=username。"""
        from audit.middleware import AuditContextMiddleware

        user = User.objects.create_user(username="jwtuser", password="testpass123")

        captured_actors = []

        async def mock_app(scope, receive, send):
            captured_actors.append(get_current_actor())
            return None

        middleware = AuditContextMiddleware(mock_app)

        # Django AuthenticationMiddleware 会设置 scope["user"] 和 scope["auth"]（JWT 场景 scope["auth"] 不是 AccessToken）
        scope = {
            "type": "http",
            "user": user,
            "auth": None,
            "headers": [],
            "client": ("10.0.0.1", 54321),
            "path": "/api/test/",
        }

        async def run():
            await middleware(scope, None, None)

        asyncio.run(run())

        assert len(captured_actors) == 1
        actor = captured_actors[0]
        assert actor.actor_type == "user"
        assert actor.actor_id == str(user.pk)
        assert actor.actor_display == "jwtuser"

    @pytest.mark.django_db
    def test_pat_authenticated_request_extracts_pat_actor(self):
        """PAT 认证请求 → actor_type='pat', actor_id=token_hash, actor_display=token_name。"""
        from audit.middleware import AuditContextMiddleware

        # 模拟 AccessToken 对象
        mock_token = MagicMock()
        mock_token.token_hash = "sha256_abc123"
        mock_token.name = "CI/CD Token"

        user = User.objects.create_user(username="patuser", password="testpass123")

        captured_actors = []

        async def mock_app(scope, receive, send):
            captured_actors.append(get_current_actor())
            return None

        middleware = AuditContextMiddleware(mock_app)

        scope = {
            "type": "http",
            "user": user,
            "auth": mock_token,  # AccessToken 实例
            "headers": [],
            "client": ("10.0.0.2", 12345),
            "path": "/api/test/",
        }

        async def run():
            await middleware(scope, None, None)

        asyncio.run(run())

        assert len(captured_actors) == 1
        actor = captured_actors[0]
        assert actor.actor_type == "pat"
        assert actor.actor_id == "sha256_abc123"
        assert actor.actor_display == "CI/CD Token"

    def test_unauthenticated_request_extracts_system_actor(self):
        """未认证请求 → actor_type='system', actor_id='anonymous'。"""
        from audit.middleware import AuditContextMiddleware

        from django.contrib.auth.models import AnonymousUser

        captured_actors = []

        async def mock_app(scope, receive, send):
            captured_actors.append(get_current_actor())
            return None

        middleware = AuditContextMiddleware(mock_app)

        scope = {
            "type": "http",
            "user": AnonymousUser(),
            "auth": None,
            "headers": [],
            "client": ("127.0.0.1", 9999),
            "path": "/api/test/",
        }

        async def run():
            await middleware(scope, None, None)

        asyncio.run(run())

        assert len(captured_actors) == 1
        actor = captured_actors[0]
        assert actor.actor_type == "system"
        assert actor.actor_id == "anonymous"

    @pytest.mark.django_db
    def test_middleware_cleans_up_contextvar_after_response(self):
        """middleware 在视图处理后清理 contextvar（不论成功或异常）。"""
        from audit.middleware import AuditContextMiddleware

        user = User.objects.create_user(username="cleanup_user", password="testpass123")

        async def mock_app(scope, receive, send):
            # 确认 contextvar 已设置
            actor = get_current_actor()
            assert actor.actor_type == "user"
            raise RuntimeError("simulated error")

        middleware = AuditContextMiddleware(mock_app)

        scope = {
            "type": "http",
            "user": user,
            "auth": None,
            "headers": [],
            "client": ("10.0.0.1", 54321),
            "path": "/api/test/",
        }

        async def run():
            with pytest.raises(RuntimeError, match="simulated error"):
                await middleware(scope, None, None)
            # 清理后 contextvar 应恢复默认
            actor = get_current_actor()
            assert actor.actor_type == "system"
            assert actor.actor_id == "system"

        asyncio.run(run())

    def test_middleware_skips_non_http_scope(self):
        """非 HTTP 请求（如 websocket）跳过 actor 设置。"""
        from audit.middleware import AuditContextMiddleware

        captured_actors = []

        async def mock_app(scope, receive, send):
            captured_actors.append(get_current_actor())
            return None

        middleware = AuditContextMiddleware(mock_app)

        scope = {
            "type": "websocket",
            "user": None,
            "headers": [],
            "path": "/ws/test/",
        }

        async def run():
            await middleware(scope, None, None)
            # websocket 不设置 actor，但 scope["type"] 非 http 时 middleware 应直接 pass through
            assert len(captured_actors) == 1

        asyncio.run(run())

    @pytest.mark.django_db
    def test_middleware_extracts_request_id_from_headers(self):
        """middleware 从 x-request-id header 提取 request_id。"""
        from audit.middleware import AuditContextMiddleware

        user = User.objects.create_user(username="reqid_user", password="testpass123")

        captured_actors = []

        async def mock_app(scope, receive, send):
            captured_actors.append(get_current_actor())
            return None

        middleware = AuditContextMiddleware(mock_app)

        # headers 是 bytes tuple list: [(b'x-request-id', b'req-123')]
        scope = {
            "type": "http",
            "user": user,
            "auth": None,
            "headers": [(b"x-request-id", b"req-123")],
            "client": ("10.0.0.1", 54321),
            "path": "/api/test/",
        }

        async def run():
            await middleware(scope, None, None)

        asyncio.run(run())

        assert len(captured_actors) == 1
        actor = captured_actors[0]
        assert actor.request_id == "req-123"


# === Task 2: emit_audit_event tests ===


class TestEmitAuditEvent:
    """测试 emit_audit_event 同步入口。"""

    @pytest.mark.django_db
    def test_emit_creates_audit_event(self):
        """emit_audit_event 成功写入一条 AuditEvent。"""
        from audit.emitter import emit_audit_event

        # 先清理 contextvar 确保干净环境
        token = set_current_actor(AuditActor(
            actor_type="user", actor_id="1", actor_display="testuser",
        ))
        try:
            event = emit_audit_event(
                action="user.login",
                target_type="User",
                target_id="1",
            )
            assert event is not None
            assert event.action == "user.login"
            assert event.target_type == "User"
            assert event.target_id == "1"
            assert event.actor_type == "user"
            assert event.actor_display == "testuser"
        finally:
            reset_current_actor(token)

    @pytest.mark.django_db
    def test_emit_auto_reads_actor_from_contextvars(self):
        """emit 自动从 contextvars 读取 actor 信息（不显式传 actor 时）。"""
        from audit.emitter import emit_audit_event

        token = set_current_actor(AuditActor(
            actor_type="pat", actor_id="sha256_xyz", actor_display="cli-token",
        ))
        try:
            event = emit_audit_event(
                action="repo.sync",
                target_type="Repository",
                target_id="100",
            )
            assert event is not None
            assert event.actor_type == "pat"
            assert event.actor_display == "cli-token"
        finally:
            reset_current_actor(token)

    @pytest.mark.django_db
    def test_emit_explicit_actor_overrides_contextvars(self):
        """显式传 actor 参数时覆盖 contextvars 值。"""
        from audit.emitter import emit_audit_event

        token = set_current_actor(AuditActor(
            actor_type="user", actor_id="1", actor_display="normal_user",
        ))
        try:
            event = emit_audit_event(
                action="system.maintenance",
                target_type="System",
                target_id="0",
                actor_type="system",
                actor_id="cron",
                actor_display="nightly-job",
            )
            assert event is not None
            assert event.actor_type == "system"
            assert event.actor_display == "nightly-job"
        finally:
            reset_current_actor(token)

    @pytest.mark.django_db
    def test_emit_returns_none_on_db_error(self):
        """AuditEvent.objects.create() 抛异常时 emit 降级为 None，不抛出。"""
        from audit.emitter import emit_audit_event

        with patch("audit.models.AuditEvent.objects.create", side_effect=Exception("db down")):
            event = emit_audit_event(
                action="user.login",
                target_type="User",
                target_id="1",
            )
            assert event is None

    @pytest.mark.django_db
    def test_emit_defaults_before_after_to_empty_dict(self):
        """before/after 默认为空 dict。"""
        from audit.emitter import emit_audit_event

        event = emit_audit_event(
            action="test.event",
            target_type="Test",
            target_id="1",
        )
        assert event is not None
        assert event.before == {}
        assert event.after == {}

    @pytest.mark.django_db
    def test_emit_source_defaults_from_contextvars_request_id(self):
        """source 从 contextvars 的 request_id 自动注入。"""
        from audit.emitter import emit_audit_event

        token = set_current_actor(AuditActor(
            actor_type="user", actor_id="1", actor_display="testuser",
            request_id="req-abc-123",
        ))
        try:
            event = emit_audit_event(
                action="test.event",
                target_type="Test",
                target_id="1",
            )
            assert event is not None
            # source 应默认为 "api"（有 request_id 意味着是 API 请求）
            assert event.source == AuditEvent.Source.API
        finally:
            reset_current_actor(token)


class TestAEmitAuditEvent:
    """测试 aemit_audit_event 异步入口。"""

    @pytest.mark.django_db
    def test_async_emit_creates_audit_event(self):
        """aemit_audit_event 异步调用成功写入一条 AuditEvent。"""
        from audit.emitter import aemit_audit_event

        token = set_current_actor(AuditActor(
            actor_type="user", actor_id="2", actor_display="async_user",
        ))
        try:
            event = asyncio.run(aemit_audit_event(
                action="user.logout",
                target_type="User",
                target_id="2",
            ))
            assert event is not None
            assert event.action == "user.logout"
            assert event.actor_display == "async_user"
        finally:
            reset_current_actor(token)

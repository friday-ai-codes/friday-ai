"""Chat 鉴权测试：ChatKeyAuthentication + ChatAuthPermission。

测试 X-Chat-Key header 密钥认证和鉴权开关权限控制的所有行为场景。
"""

from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import AuthenticationFailed

from chat.authentication import ChatKeyAuthentication
from chat.permissions import ChatAuthPermission
from system.models import SettingKeys, SystemSetting

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def chat_key_setting(db):
    """创建 Chat Key 系统设置。"""
    return SystemSetting.objects.create(
        key=SettingKeys.CHAT_KEY,
        value="test-chat-key-12345",
    )


@pytest.fixture
def auth_enabled_setting(db):
    """创建鉴权开关设置（开启）。"""
    return SystemSetting.objects.create(
        key=SettingKeys.CHAT_AUTH_ENABLED,
        value="true",
    )


def _make_request(chat_key: str | None = None, auth: object = None, user: object = None) -> MagicMock:
    """创建 mock request 对象。"""
    request = MagicMock()
    request.META = {}
    if chat_key is not None:
        request.META["HTTP_X_CHAT_KEY"] = chat_key
    request.auth = auth
    request.user = user or AnonymousUser()
    return request


# ============================================================================
# ChatKeyAuthentication 测试
# ============================================================================


@pytest.mark.django_db
class TestChatKeyAuthentication:
    """X-Chat-Key header 认证测试。"""

    def test_valid_key_returns_anonymous_user(self, chat_key_setting):
        """有效的 Chat Key 应返回 (AnonymousUser(), 'chat-key')。"""
        auth = ChatKeyAuthentication()
        request = _make_request(chat_key="test-chat-key-12345")

        result = auth.authenticate(request)

        assert result is not None
        user, auth_info = result
        assert isinstance(user, AnonymousUser)
        assert auth_info == "chat-key"

    def test_missing_header_returns_none(self, chat_key_setting):
        """X-Chat-Key header 不存在时应返回 None（交给下一个 authenticator）。"""
        auth = ChatKeyAuthentication()
        request = _make_request()

        result = auth.authenticate(request)

        assert result is None

    def test_invalid_key_raises_authentication_failed(self, chat_key_setting):
        """X-Chat-Key header 存在但值不匹配时应 raise AuthenticationFailed。"""
        auth = ChatKeyAuthentication()
        request = _make_request(chat_key="wrong-key")

        with pytest.raises(AuthenticationFailed):
            auth.authenticate(request)

    def test_no_setting_returns_none(self, db):
        """CHAT_KEY 配置不存在时应返回 None。"""
        auth = ChatKeyAuthentication()
        request = _make_request(chat_key="any-key")

        result = auth.authenticate(request)

        assert result is None

    def test_empty_setting_value_returns_none(self, db):
        """CHAT_KEY 配置值为空时应返回 None。"""
        SystemSetting.objects.create(key=SettingKeys.CHAT_KEY, value="")
        auth = ChatKeyAuthentication()
        request = _make_request(chat_key="any-key")

        result = auth.authenticate(request)

        assert result is None

    def test_plaintext_key_compared_correctly(self, db):
        """明文存储的密钥应被正确比较。"""
        SystemSetting.objects.create(
            key=SettingKeys.CHAT_KEY,
            value="secret-chat-key-99",
            is_encrypted=False,
        )
        auth = ChatKeyAuthentication()
        request = _make_request(chat_key="secret-chat-key-99")

        result = auth.authenticate(request)

        assert result is not None
        user, auth_info = result
        assert isinstance(user, AnonymousUser)
        assert auth_info == "chat-key"


# ============================================================================
# ChatAuthPermission 测试
# ============================================================================


@pytest.mark.django_db
class TestChatAuthPermission:
    """鉴权开关权限测试。"""

    def test_auth_disabled_allows_all(self, db):
        """鉴权开关关闭时（配置不存在），所有请求放行。"""
        perm = ChatAuthPermission()
        request = _make_request()

        assert perm.has_permission(request, None) is True

    def test_auth_enabled_chat_key_passes(self, auth_enabled_setting):
        """鉴权开关开启时，chat-key 认证放行。"""
        perm = ChatAuthPermission()
        request = _make_request(auth="chat-key")

        assert perm.has_permission(request, None) is True

    def test_auth_enabled_jwt_user_passes(self, auth_enabled_setting):
        """鉴权开关开启时，已认证的 JWT 用户放行。"""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(username="chatuser", password="pass123")

        perm = ChatAuthPermission()
        request = _make_request(user=user)

        assert perm.has_permission(request, None) is True

    def test_auth_enabled_no_auth_denied(self, auth_enabled_setting):
        """鉴权开关开启时，无认证的请求拒绝。"""
        perm = ChatAuthPermission()
        request = _make_request()

        assert perm.has_permission(request, None) is False

    def test_auth_disabled_with_false_value(self, db):
        """鉴权开关值为 false 时，所有请求放行。"""
        SystemSetting.objects.create(
            key=SettingKeys.CHAT_AUTH_ENABLED,
            value="false",
        )
        perm = ChatAuthPermission()
        request = _make_request()

        assert perm.has_permission(request, None) is True

    def test_auth_enabled_with_yes_value(self, db):
        """鉴权开关值为 yes 时，无认证的请求拒绝。"""
        SystemSetting.objects.create(
            key=SettingKeys.CHAT_AUTH_ENABLED,
            value="yes",
        )
        perm = ChatAuthPermission()
        request = _make_request()

        assert perm.has_permission(request, None) is False

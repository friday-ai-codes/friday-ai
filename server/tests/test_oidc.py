"""OIDC 认证 — 完整单元测试。"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core import signing
from rest_framework.test import APIClient

from accounts.models import UserSource
from identity.models import OIDCIdentity, OIDCProvider, OIDCProviderKind
from identity.services import (
    build_authorize_url,
    build_callback_url,
    create_signed_state,
    generate_state,
    jit_provision_user,
    verify_signed_state,
)

User = get_user_model()


@pytest.fixture
def oidc_provider(db):
    """创建测试用 OIDC Provider。"""
    return OIDCProvider.objects.create(
        name="Test Provider",
        kind=OIDCProviderKind.OTHER,
        issuer_url="https://accounts.example.com",
        client_id="test-client-id",
        client_secret_encrypted="test-client-secret",
        authorization_endpoint="https://accounts.example.com/authorize",
        token_endpoint="https://accounts.example.com/token",
        userinfo_endpoint="https://accounts.example.com/userinfo",
        scopes="openid profile email",
        is_active=True,
    )


@pytest.fixture
def feishu_provider(db):
    """创建 kind=feishu 的 OIDC Provider，用于来源映射测试。"""
    return OIDCProvider.objects.create(
        name="Feishu",
        kind=OIDCProviderKind.FEISHU,
        issuer_url="https://passport.feishu.cn",
        client_id="feishu-client-id",
        authorization_endpoint="https://passport.feishu.cn/authorize",
        token_endpoint="https://passport.feishu.cn/token",
        is_active=True,
    )


@pytest.fixture
def inactive_provider(db):
    """创建未启用的 OIDC Provider。"""
    return OIDCProvider.objects.create(
        name="Inactive Provider",
        issuer_url="https://inactive.example.com",
        client_id="inactive-client-id",
        authorization_endpoint="https://inactive.example.com/authorize",
        token_endpoint="https://inactive.example.com/token",
        is_active=False,
    )


@pytest.fixture
def admin_user(db):
    """创建超级管理员用户。"""
    return User.objects.create_superuser(
        username="oidc_admin",
        password="admin123!",
        email="oidc_admin@example.com",
    )


@pytest.fixture
def normal_user(db):
    """创建普通用户。"""
    return User.objects.create_user(
        username="normaluser",
        password="user123!",
        email="normal@example.com",
    )


@pytest.fixture
def admin_api(admin_user):
    """已认证的管理员 API Client。"""
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def anon_api():
    """未认证的 API Client。"""
    return APIClient()


# =============================================================================
# Provider CRUD 测试
# =============================================================================


@pytest.mark.django_db
class TestProviderCRUD:
    """OIDC Provider CRUD API 测试。"""

    def test_create_provider(self, admin_api):
        """创建 Provider 成功，且响应只暴露 has_secret 布尔位，不回显密钥本身。

        历史实现返回 masked_secret 掩码串，现已收敛为 client_secret 只写（write_only）
        + has_secret 派生布尔。守护的性质不变：client_secret 在任何读路径都不得外泄。
        """
        secret = "new-secret-must-never-be-echoed"
        data = {
            "name": "New Provider",
            "issuer_url": "https://new.example.com",
            "client_id": "new-client-id",
            "client_secret": secret,
            "authorization_endpoint": "https://new.example.com/authorize",
            "token_endpoint": "https://new.example.com/token",
        }
        response = admin_api.post("/api/oidc/providers/", data=data, format="json")
        assert response.status_code == 201
        result = response.json()
        assert result["name"] == "New Provider"
        assert result["client_id"] == "new-client-id"
        # 密钥已落库（has_secret 为派生布尔，不携带任何密钥内容）
        assert result["has_secret"] is True
        assert "client_secret" not in result
        assert "client_secret_encrypted" not in result
        # 整包体做子串扫描，防止密钥经由任何新增字段/嵌套结构泄漏
        assert secret not in json.dumps(result)

        # 后续读路径（详情 / 列表）同样不得回显密钥
        provider_id = result["id"]
        detail = admin_api.get(f"/api/oidc/providers/{provider_id}/")
        assert detail.status_code == 200
        assert detail.json()["has_secret"] is True
        assert secret not in json.dumps(detail.json())

        listing = admin_api.get("/api/oidc/providers/")
        assert listing.status_code == 200
        assert secret not in json.dumps(listing.json())

    def test_list_providers(self, admin_api, oidc_provider):
        """列出所有 Provider。"""
        response = admin_api.get("/api/oidc/providers/")
        assert response.status_code == 200
        result = response.json()
        assert len(result) >= 1

    def test_get_provider_detail(self, admin_api, oidc_provider):
        """获取单个 Provider 详情。"""
        response = admin_api.get(f"/api/oidc/providers/{oidc_provider.id}/")
        assert response.status_code == 200
        result = response.json()
        assert result["name"] == "Test Provider"
        assert result["has_secret"] is True

    def test_update_provider(self, admin_api, oidc_provider):
        """更新 Provider。"""
        response = admin_api.put(
            f"/api/oidc/providers/{oidc_provider.id}/",
            data={"name": "Updated Provider"},
            format="json",
        )
        assert response.status_code == 200
        result = response.json()
        assert result["name"] == "Updated Provider"

    def test_delete_provider(self, admin_api, oidc_provider):
        """删除 Provider。"""
        response = admin_api.delete(f"/api/oidc/providers/{oidc_provider.id}/")
        assert response.status_code == 204
        assert not OIDCProvider.objects.filter(id=oidc_provider.id).exists()

    def test_crud_requires_admin(self, anon_api):
        """非管理员无法访问 CRUD API。"""
        response = anon_api.get("/api/oidc/providers/")
        assert response.status_code in (401, 403)


# =============================================================================
# 加密存储测试
# =============================================================================


@pytest.mark.django_db
class TestSecretEncryption:
    """client_secret 加密存储测试。"""

    def test_secret_stored_plaintext_in_db(self, admin_api):
        """创建 Provider 后 DB 中明文存储 secret。"""
        data = {
            "name": "Plaintext Provider",
            "issuer_url": "https://plaintext.example.com",
            "client_id": "pt-client-id",
            "client_secret": "my-super-secret",
            "authorization_endpoint": "https://plaintext.example.com/authorize",
            "token_endpoint": "https://plaintext.example.com/token",
        }
        response = admin_api.post("/api/oidc/providers/", data=data, format="json")
        assert response.status_code == 201
        provider_id = response.json()["id"]
        provider = OIDCProvider.objects.get(id=provider_id)
        assert provider.client_secret_encrypted == "my-super-secret"

    def test_api_returns_has_secret(self, admin_api, oidc_provider):
        """API 返回 has_secret 标志。"""
        response = admin_api.get(f"/api/oidc/providers/{oidc_provider.id}/")
        result = response.json()
        assert result["has_secret"] is True
        assert "client_secret_encrypted" not in result


# =============================================================================
# Discovery 测试
# =============================================================================


@pytest.mark.django_db
class TestDiscovery:
    """OIDC Discovery URL 自动填充测试。"""

    def test_discovery_success(self, admin_api):
        """Discovery 成功返回端点信息。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "authorization_endpoint": "https://example.com/authorize",
            "token_endpoint": "https://example.com/token",
            "userinfo_endpoint": "https://example.com/userinfo",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("identity.services.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            response = admin_api.post(
                "/api/oidc/providers/discovery/",
                data={"issuer_url": "https://example.com"},
                format="json",
            )
        assert response.status_code == 200
        result = response.json()
        assert result["authorization_endpoint"] == "https://example.com/authorize"
        assert result["token_endpoint"] == "https://example.com/token"


# =============================================================================
# 授权流程测试
# =============================================================================


@pytest.mark.django_db
class TestAuthorize:
    """OIDC Authorize 端点测试。"""

    def test_authorize_returns_url(self, anon_api, oidc_provider):
        """authorize 端点返回授权 URL 并设置 state cookie。"""
        response = anon_api.get(f"/api/oidc/authorize/{oidc_provider.id}/?redirect_uri=/")
        assert response.status_code == 200
        result = response.json()
        assert "authorize_url" in result
        assert "accounts.example.com/authorize" in result["authorize_url"]
        assert "client_id=test-client-id" in result["authorize_url"]

    def test_authorize_inactive_provider(self, anon_api, inactive_provider):
        """未启用的 Provider 返回 404。"""
        response = anon_api.get(f"/api/oidc/authorize/{inactive_provider.id}/")
        assert response.status_code == 404

    def test_authorize_nonexistent_provider(self, anon_api):
        """不存在的 Provider 返回 404。"""
        fake_id = uuid.uuid4()
        response = anon_api.get(f"/api/oidc/authorize/{fake_id}/")
        assert response.status_code == 404

    def test_authorize_with_prompt_login(self, anon_api, oidc_provider):
        """传 prompt=login 时授权 URL 应包含 prompt 参数（用于退出后强制重认证）。"""
        response = anon_api.get(
            f"/api/oidc/authorize/{oidc_provider.id}/?prompt=login"
        )
        assert response.status_code == 200
        assert "prompt=login" in response.json()["authorize_url"]

    def test_authorize_without_prompt(self, anon_api, oidc_provider):
        """不传 prompt 时授权 URL 不应包含 prompt 参数（默认 SSO 行为）。"""
        response = anon_api.get(f"/api/oidc/authorize/{oidc_provider.id}/")
        assert response.status_code == 200
        assert "prompt=" not in response.json()["authorize_url"]

    def test_authorize_rejects_unknown_prompt(self, anon_api, oidc_provider):
        """非白名单 prompt 值应被静默忽略，避免任意值透传到 IdP。"""
        response = anon_api.get(
            f"/api/oidc/authorize/{oidc_provider.id}/?prompt=evil-value"
        )
        assert response.status_code == 200
        assert "prompt=" not in response.json()["authorize_url"]


# =============================================================================
# 站点 Host（site_host）解析测试
# =============================================================================


@pytest.mark.django_db
class TestSiteHostResolution:
    """OIDC 回调 URL 优先消费「站点 Host」系统设置（site_host）。"""

    def test_callback_url_uses_site_host_when_set(self):
        """site_host 已配置时，redirect_uri 用站点 Host 而非 FRIDAY_BASE_URL。"""
        from system.models import SettingKeys, SystemSetting

        SystemSetting.objects.create(
            key=SettingKeys.SITE_HOST, value="https://friday.example.com"
        )
        url = async_to_sync(build_callback_url)(None)
        assert url == "https://friday.example.com/api/oidc/callback/"

    def test_callback_url_falls_back_to_friday_base_url(self, settings):
        """site_host 未配置且无请求上下文时回退 FRIDAY_BASE_URL（旧部署行为不回退）。"""
        settings.FRIDAY_BASE_URL = "http://fallback.example.com:10241"
        url = async_to_sync(build_callback_url)(None)
        assert url == "http://fallback.example.com:10241/api/oidc/callback/"

    def test_callback_url_uses_request_host_when_no_site_host(self, rf, settings):
        """site_host 未配置时直接取当前请求的 Host（含端口）。"""
        settings.ALLOWED_HOSTS = ["*"]
        settings.FRIDAY_BASE_URL = "http://localhost:10241"
        request = rf.get("/api/oidc/authorize/x/", HTTP_HOST="192.168.1.10:10240")
        url = async_to_sync(build_callback_url)(request)
        assert url == "http://192.168.1.10:10240/api/oidc/callback/"

    def test_disallowed_request_host_falls_back(self, rf, settings):
        """请求 Host 不在 ALLOWED_HOSTS（疑似伪造）时回退 env，不中断登录。"""
        settings.ALLOWED_HOSTS = ["testserver"]
        settings.FRIDAY_BASE_URL = "http://fallback.example.com:10241"
        request = rf.get("/api/oidc/authorize/x/", HTTP_HOST="evil.example.com")
        url = async_to_sync(build_callback_url)(request)
        assert url == "http://fallback.example.com:10241/api/oidc/callback/"

    def test_site_host_overrides_request_host(self, rf):
        """site_host 已配置时优先于请求 Host。"""
        from system.models import SettingKeys, SystemSetting

        SystemSetting.objects.create(
            key=SettingKeys.SITE_HOST, value="https://friday.example.com"
        )
        request = rf.get("/api/oidc/authorize/x/", HTTP_HOST="192.168.1.10:10240")
        url = async_to_sync(build_callback_url)(request)
        assert url == "https://friday.example.com/api/oidc/callback/"

    def test_site_host_trailing_slash_stripped(self):
        """site_host 末尾斜杠被剥离，避免 URL 出现双斜杠。"""
        from system.models import SettingKeys, SystemSetting

        SystemSetting.objects.create(
            key=SettingKeys.SITE_HOST, value="https://friday.example.com/"
        )
        url = async_to_sync(build_callback_url)(None)
        assert url == "https://friday.example.com/api/oidc/callback/"

    def test_site_host_without_scheme_gets_http_prefix(self):
        """site_host 缺 scheme 时自动补 http://（IdP 拒绝无 scheme 的 redirect_uri）。"""
        from system.models import SettingKeys, SystemSetting

        SystemSetting.objects.create(
            key=SettingKeys.SITE_HOST, value="192.168.1.10:10240"
        )
        url = async_to_sync(build_callback_url)(None)
        assert url == "http://192.168.1.10:10240/api/oidc/callback/"

    def test_blank_site_host_falls_back(self, settings):
        """site_host 存在但为空串时回退 env 配置（设置页允许清空）。"""
        from system.models import SettingKeys, SystemSetting

        SystemSetting.objects.create(key=SettingKeys.SITE_HOST, value="")
        settings.FRIDAY_BASE_URL = "http://fallback.example.com:10241"
        url = async_to_sync(build_callback_url)(None)
        assert url == "http://fallback.example.com:10241/api/oidc/callback/"

    def test_authorize_redirect_uri_uses_request_host_without_site_host(
        self, anon_api, oidc_provider
    ):
        """端到端：未配置 site_host 时 redirect_uri 直接取请求 Host。"""
        from urllib.parse import quote

        response = anon_api.get(f"/api/oidc/authorize/{oidc_provider.id}/?redirect_uri=/")
        assert response.status_code == 200
        authorize_url = response.json()["authorize_url"]
        expected = quote("http://testserver/api/oidc/callback/", safe="")
        assert f"redirect_uri={expected}" in authorize_url

    def test_authorize_redirect_uri_uses_site_host(self, anon_api, oidc_provider):
        """端到端：authorize 端点生成的授权 URL 中 redirect_uri 用站点 Host。"""
        from urllib.parse import quote

        from system.models import SettingKeys, SystemSetting

        SystemSetting.objects.create(
            key=SettingKeys.SITE_HOST, value="https://friday.example.com"
        )
        response = anon_api.get(f"/api/oidc/authorize/{oidc_provider.id}/?redirect_uri=/")
        assert response.status_code == 200
        authorize_url = response.json()["authorize_url"]
        expected = quote("https://friday.example.com/api/oidc/callback/", safe="")
        assert f"redirect_uri={expected}" in authorize_url

    def test_login_error_redirect_uses_site_host(self, anon_api):
        """端到端：回调错误跳转登录页时前端 base 用站点 Host。"""
        from system.models import SettingKeys, SystemSetting

        SystemSetting.objects.create(
            key=SettingKeys.SITE_HOST, value="https://friday.example.com"
        )
        response = anon_api.get(
            "/api/oidc/callback/?error=access_denied&error_description=User+denied"
        )
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert location.startswith("https://friday.example.com/login?oidc_error=")


# =============================================================================
# State 校验测试
# =============================================================================


@pytest.mark.django_db
class TestStateValidation:
    """OIDC State 参数校验测试。"""

    def test_state_missing_cookie(self, anon_api):
        """缺少 state cookie 返回 400。"""
        response = anon_api.get("/api/oidc/callback/?code=test&state=test")
        assert response.status_code == 400

    def test_state_mismatch(self, anon_api, oidc_provider):
        """state 值不匹配返回 400。"""
        signed = signing.dumps({
            "state": "correct-state",
            "redirect_uri": "/",
            "provider_id": str(oidc_provider.id),
        })
        anon_api.cookies["oidc_state"] = signed
        response = anon_api.get("/api/oidc/callback/?code=test&state=wrong-state")
        assert response.status_code == 400

    def test_state_expired(self, anon_api):
        """state 过期返回 400。"""
        with patch("identity.views.verify_signed_state") as mock_verify:
            mock_verify.side_effect = signing.SignatureExpired("expired")
            anon_api.cookies["oidc_state"] = "some-signed-value"
            response = anon_api.get("/api/oidc/callback/?code=test&state=test")
        assert response.status_code == 400

    def test_state_invalid_signature(self, anon_api):
        """签名无效返回 400。"""
        anon_api.cookies["oidc_state"] = "invalid-signed-data"
        response = anon_api.get("/api/oidc/callback/?code=test&state=test")
        assert response.status_code == 400

    def test_state_generation(self):
        """state 值为 32 字节随机值。"""
        state = generate_state()
        assert len(state) >= 32

    def test_signed_state_roundtrip(self):
        """signed state 可以正确创建和验证。"""
        state = generate_state()
        signed = create_signed_state(state, "/dashboard", "test-id")
        verified = verify_signed_state(signed)
        assert verified["state"] == state
        assert verified["redirect_uri"] == "/dashboard"
        assert verified["provider_id"] == "test-id"


# =============================================================================
# Callback + Token Exchange 测试
# =============================================================================


@pytest.mark.django_db
class TestCallback:
    """OIDC Callback 端点测试。"""

    def test_callback_success(self, anon_api, oidc_provider):
        """完整回调流程成功签发 JWT。"""
        state_value = "test-state-value"
        signed = signing.dumps({
            "state": state_value,
            "redirect_uri": "/",
            "provider_id": str(oidc_provider.id),
        })
        anon_api.cookies["oidc_state"] = signed

        mock_token_response = {
            "access_token": "provider-access-token",
            "id_token": "provider-id-token",
            "token_type": "Bearer",
        }
        mock_userinfo = {
            "sub": "oidc-user-123",
            "email": "oidc@example.com",
            "preferred_username": "oidcuser",
            "name": "OIDC User",
        }

        with patch("identity.views.exchange_code_for_tokens", new_callable=AsyncMock) as mock_exchange, \
             patch("identity.views.fetch_userinfo", new_callable=AsyncMock) as mock_userinfo_fn:
            mock_exchange.return_value = mock_token_response
            mock_userinfo_fn.return_value = mock_userinfo

            response = anon_api.get(f"/api/oidc/callback/?code=test-code&state={state_value}")

        # 应该重定向到前端
        assert response.status_code == 302

    def test_callback_provider_error(self, anon_api):
        """Provider 返回 error 参数时重定向到登录页。"""
        response = anon_api.get(
            "/api/oidc/callback/?error=access_denied&error_description=User+denied"
        )
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "login" in location
        assert "oidc_error" in location

    def test_callback_missing_params(self, anon_api):
        """缺少 code 或 state 返回 400。"""
        response = anon_api.get("/api/oidc/callback/")
        assert response.status_code == 400


# =============================================================================
# JIT Provisioning 测试
# =============================================================================


@pytest.mark.django_db(transaction=True)
class TestJITProvisioning:
    """JIT 用户创建/关联测试。"""

    def test_new_user_creation(self, oidc_provider):
        """首次 OIDC 登录自动创建新用户。"""
        userinfo = {
            "sub": "new-sub-123",
            "email": "newuser@example.com",
            "preferred_username": "newuser",
            "name": "New User",
        }
        user, is_new = async_to_sync(jit_provision_user)(oidc_provider, userinfo)
        assert is_new is True
        assert user.username == "newuser"
        assert user.email == "newuser@example.com"
        assert user.display_name == "New User"
        assert not user.has_usable_password()
        # 检查 OIDCIdentity 创建
        assert OIDCIdentity.objects.filter(
            provider=oidc_provider, sub="new-sub-123"
        ).exists()

    def test_existing_email_association(self, oidc_provider, normal_user):
        """已有同 email 用户时关联到已有账号。"""
        userinfo = {
            "sub": "existing-email-sub",
            "email": "normal@example.com",
            "name": "Normal User",
        }
        user, is_new = async_to_sync(jit_provision_user)(oidc_provider, userinfo)
        assert is_new is False
        assert user.id == normal_user.id
        assert OIDCIdentity.objects.filter(
            provider=oidc_provider, sub="existing-email-sub"
        ).exists()

    def test_existing_identity_login(self, oidc_provider, normal_user):
        """已有 OIDCIdentity 映射时直接登录。"""
        OIDCIdentity.objects.create(
            user=normal_user,
            provider=oidc_provider,
            sub="known-sub-456",
            email="normal@example.com",
        )
        userinfo = {
            "sub": "known-sub-456",
            "email": "normal@example.com",
        }
        user, is_new = async_to_sync(jit_provision_user)(oidc_provider, userinfo)
        assert is_new is False
        assert user.id == normal_user.id

    def test_username_conflict_resolution(self, oidc_provider, normal_user):
        """用户名冲突时加后缀。"""
        userinfo = {
            "sub": "conflict-sub",
            "email": "another@example.com",
            "preferred_username": "normaluser",
            "name": "Another User",
        }
        user, is_new = async_to_sync(jit_provision_user)(oidc_provider, userinfo)
        assert is_new is True
        assert user.username.startswith("normaluser")
        assert user.username != "normaluser"

    def test_new_user_source_matches_provider_kind(self, feishu_provider):
        """通过 kind=feishu 的 Provider 创建的用户 source 应为 feishu。"""
        userinfo = {
            "sub": "feishu-sub-001",
            "email": "fs-user@example.com",
            "preferred_username": "fsuser",
            "name": "Feishu User",
        }
        user, is_new = async_to_sync(jit_provision_user)(feishu_provider, userinfo)
        assert is_new is True
        assert user.source == UserSource.FEISHU.value

    def test_other_provider_maps_to_oidc_other(self, oidc_provider):
        """kind=other 的 Provider 创建的用户 source 为 oidc_other。"""
        userinfo = {
            "sub": "other-sub-001",
            "email": "other-user@example.com",
            "preferred_username": "otheruser",
            "name": "Other User",
        }
        user, _ = async_to_sync(jit_provision_user)(oidc_provider, userinfo)
        assert user.source == UserSource.OIDC_OTHER.value


# =============================================================================
# 公开端点测试
# =============================================================================


@pytest.mark.django_db
class TestPublicProviderList:
    """公开 Provider 列表端点测试。"""

    def test_public_list_returns_active_only(
        self, anon_api, oidc_provider, inactive_provider
    ):
        """公开端点仅返回活跃 Provider 的 id + name。"""
        response = anon_api.get("/api/oidc/providers/public/")
        assert response.status_code == 200
        result = response.json()
        names = [p["name"] for p in result]
        assert "Test Provider" in names
        assert "Inactive Provider" not in names
        for provider in result:
            assert "client_id" not in provider
            assert set(provider.keys()) == {"id", "name"}


# =============================================================================
# 辅助函数测试
# =============================================================================


class TestHelperFunctions:
    """辅助函数测试。"""

    def test_build_authorize_url(self, oidc_provider):
        """构造正确的授权 URL。"""
        url = build_authorize_url(oidc_provider, "my-state", "http://localhost/callback")
        assert "accounts.example.com/authorize" in url
        assert "client_id=test-client-id" in url
        assert "response_type=code" in url
        assert "state=my-state" in url
        assert "redirect_uri=" in url
        assert "prompt=" not in url

    def test_build_authorize_url_with_prompt(self, oidc_provider):
        """传入 prompt 时应附加到授权 URL（用于退出后强制重认证）。"""
        url = build_authorize_url(
            oidc_provider, "my-state", "http://localhost/callback", prompt="login"
        )
        assert "prompt=login" in url

"""首启向导门禁测试 — SetupStatusView + SetupInitView（SETUP-02/03/04）。"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

SETUP_STATUS_URL = "/api/auth/setup/status/"
SETUP_INIT_URL = "/api/auth/setup/"
LOGIN_URL = "/api/auth/login/"

# 满足 Django 四校验器（长度≥8、非纯数字、非常见、与用户名不相似）的强口令
STRONG_PASSWORD = "Str0ng!Passw0rd"


@pytest.mark.django_db
class TestSetupStatusView:
    """GET /api/auth/setup/status/ 测试（SETUP-02）。"""

    def test_status_not_initialized(self, api_client):
        """未创建 superuser 时返回 needs_setup=True, is_initialized=False。"""
        response = api_client.get(SETUP_STATUS_URL)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["needs_setup"] is True
        assert response.data["is_initialized"] is False

    def test_status_initialized(self, api_client, admin_user):
        """已有 superuser 时返回 needs_setup=False, is_initialized=True。"""
        response = api_client.get(SETUP_STATUS_URL)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["needs_setup"] is False
        assert response.data["is_initialized"] is True

    def test_no_auth_required(self, api_client):
        """无 Authorization 头可正常调用，证明 AllowAny 生效。"""
        # api_client 未 force_authenticate，相当于匿名请求
        response = api_client.get(SETUP_STATUS_URL)
        assert response.status_code == status.HTTP_200_OK

    def test_status_ignores_invalid_access_cookie(self, api_client):
        """公开 setup status 不应被过期/损坏的 access_token cookie 短路成 401。"""
        api_client.cookies["access_token"] = "not-a-valid-jwt"

        response = api_client.get(SETUP_STATUS_URL)

        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestSetupInitView:
    """POST /api/auth/setup/ 测试（SETUP-02/03/04）。"""

    def test_init_post_success(self, api_client):
        """无 superuser 时 POST 成功，返回 201，DB 中存在 is_superuser=True 用户。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD, "display_name": "管理员"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(username="firstadmin", is_superuser=True).exists()

    def test_init_post_403_when_initialized(self, api_client, admin_user):
        """已有 superuser 时 POST 返回 403（fail-closed，SETUP-03）。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "new_admin", "password": STRONG_PASSWORD},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_duplicate_post_rejected(self, api_client):
        """首次 POST 成功后，再次 POST 被 403 拒绝（防重入，SETUP-04）。"""
        # 第一次 POST，创建 superuser
        first = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD},
            format="json",
        )
        assert first.status_code == status.HTTP_201_CREATED
        # 第二次 POST，superuser 已存在，SetupNotInitialized 拦截
        second = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD},
            format="json",
        )
        assert second.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_password(self, api_client):
        """缺少 password 字段返回 400。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "admin"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_short_password(self, api_client):
        """password 少于 8 位返回 400（ADMIN-01）。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "admin", "password": "123"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_numeric_password_rejected(self, api_client):
        """纯数字口令被 NumericPasswordValidator 拒绝，返回 400（ADMIN-01）。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "adminx", "password": "12345678"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_common_password_rejected(self, api_client):
        """常见弱口令被 CommonPasswordValidator 拒绝，返回 400（ADMIN-01）。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "adminx", "password": "password"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_password_similar_to_username_rejected(self, api_client):
        """密码与用户名过于相似被 UserAttributeSimilarityValidator 拒绝，返回 400（ADMIN-01）。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "adminuser", "password": "adminuser1"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_does_not_force_password_change(self, api_client):
        """创建的 superuser 不触发 must_change_password 强制改密（ADMIN-02）。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["must_change_password"] is False
        created = User.objects.get(username="firstadmin")
        assert created.must_change_password is False

    def test_session_cookies_set(self, api_client):
        """创建成功后下发会话 cookie 且响应体含 access_token + user（ADMIN-03）。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "refresh_token" in response.cookies
        assert "access_token" in response.cookies
        assert response.data["access_token"]
        assert response.data["user"]["username"] == "firstadmin"

    def test_created_admin_can_login(self, api_client):
        """创建的账号随后可正常用于登录（ADMIN-02）。"""
        create = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD},
            format="json",
        )
        assert create.status_code == status.HTTP_201_CREATED
        login = api_client.post(
            LOGIN_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD},
            format="json",
        )
        assert login.status_code == status.HTTP_200_OK

    def test_login_ignores_invalid_access_cookie(self, api_client):
        """登录入口应忽略旧 access_token，否则浏览器残留坏 cookie 会导致无法重新登录。"""
        create = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD},
            format="json",
        )
        assert create.status_code == status.HTTP_201_CREATED
        api_client.cookies["access_token"] = "not-a-valid-jwt"

        login = api_client.post(
            LOGIN_URL,
            {"username": "firstadmin", "password": STRONG_PASSWORD},
            format="json",
        )

        assert login.status_code == status.HTTP_200_OK

    def test_refresh_ignores_invalid_access_cookie(self, api_client, admin_user):
        """刷新入口只依赖 refresh_token，坏 access_token 不应让刷新在视图前 401。"""
        refresh = RefreshToken.for_user(admin_user)
        refresh["sub"] = str(admin_user.id)
        api_client.cookies["refresh_token"] = str(refresh)
        api_client.cookies["access_token"] = "not-a-valid-jwt"

        response = api_client.post("/api/auth/refresh/")

        assert response.status_code == status.HTTP_200_OK
        assert "access_token" in response.cookies
        assert "refresh_token" in response.cookies

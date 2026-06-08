"""首启向导门禁测试 — SetupStatusView + SetupInitView（SETUP-02/03/04）。"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status

User = get_user_model()

SETUP_STATUS_URL = "/api/auth/setup/status/"
SETUP_INIT_URL = "/api/auth/setup/"


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


@pytest.mark.django_db
class TestSetupInitView:
    """POST /api/auth/setup/ 测试（SETUP-02/03/04）。"""

    def test_init_post_success(self, api_client):
        """无 superuser 时 POST 成功，返回 201，DB 中存在 is_superuser=True 用户。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": "admin1234", "display_name": "管理员"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(username="firstadmin", is_superuser=True).exists()

    def test_init_post_403_when_initialized(self, api_client, admin_user):
        """已有 superuser 时 POST 返回 403（fail-closed，SETUP-03）。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "new_admin", "password": "admin1234"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_duplicate_post_rejected(self, api_client):
        """首次 POST 成功后，再次 POST 被 403 拒绝（防重入，SETUP-04）。"""
        # 第一次 POST，创建 superuser
        first = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": "admin1234"},
            format="json",
        )
        assert first.status_code == status.HTTP_201_CREATED
        # 第二次 POST，superuser 已存在，SetupNotInitialized 拦截
        second = api_client.post(
            SETUP_INIT_URL,
            {"username": "firstadmin", "password": "admin1234"},
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
        """password 少于 6 位返回 400。"""
        response = api_client.post(
            SETUP_INIT_URL,
            {"username": "admin", "password": "123"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

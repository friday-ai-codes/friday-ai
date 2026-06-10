"""Runner 注册 API 测试 -- 覆盖 work item 注册流程。"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from runners.models import (
    RegistrationToken,
    Runner,
    generate_token,
    hash_token,
)


@pytest.mark.django_db
class TestRunnerRegistrationAPI:
    """POST /api/runners/register/ 端点测试。"""

    def _create_reg_token(self, user: User, **kwargs: object) -> str:
        """辅助方法：创建有效的 RegistrationToken 并返回原始 token 字符串。"""
        raw_token: str = generate_token()
        defaults: dict[str, object] = {
            "token_hash": hash_token(raw_token),
            "expires_at": timezone.now() + timedelta(hours=1),
            "created_by": user,
        }
        defaults.update(kwargs)
        RegistrationToken.objects.create(**defaults)
        return raw_token

    def test_register_runner_with_valid_token(self, api_client: APIClient, user: User) -> None:
        """有效 token 注册 Runner 返回 201 + runner_token。"""
        raw_token: str = self._create_reg_token(user)
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": raw_token,
            "name": "test-runner-api",
        })
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "runner_id" in data
        assert "runner_token" in data
        assert data["name"] == "test-runner-api"
        # 验证 Runner 已创建
        assert Runner.objects.filter(name="test-runner-api").exists()

    def test_register_with_expired_token_fails(self, api_client: APIClient, user: User) -> None:
        """过期 token 注册返回 401。"""
        raw_token: str = generate_token()
        RegistrationToken.objects.create(
            token_hash=hash_token(raw_token),
            expires_at=timezone.now() - timedelta(hours=1),  # 已过期
            created_by=user,
        )
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": raw_token,
            "name": "expired-runner",
        })
        # RunnerRegisterView 对无效/过期 token 返回 401
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_register_with_used_token_fails(self, api_client: APIClient, user: User) -> None:
        """已使用的 token 注册返回 401。"""
        raw_token: str = generate_token()
        RegistrationToken.objects.create(
            token_hash=hash_token(raw_token),
            expires_at=timezone.now() + timedelta(hours=1),
            created_by=user,
            is_used=True,
            used_at=timezone.now(),
        )
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": raw_token,
            "name": "used-token-runner",
        })
        # is_used=True 的 token 被 filter 排除，返回 401
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_register_with_invalid_token_fails(self, api_client: APIClient) -> None:
        """无效 token 注册返回 401。"""
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": "completely-invalid-token",
            "name": "invalid-runner",
        })
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_register_marks_token_as_used(self, api_client: APIClient, user: User) -> None:
        """注册成功后 RegistrationToken 被标记为 is_used=True。"""
        raw_token: str = self._create_reg_token(user)
        url: str = reverse("runner-register")
        api_client.post(url, {
            "token": raw_token,
            "name": "mark-used-runner",
        })
        reg_token = RegistrationToken.objects.get(token_hash=hash_token(raw_token))
        assert reg_token.is_used is True
        assert reg_token.used_at is not None

    def test_register_without_name_fails(self, api_client: APIClient, user: User) -> None:
        """缺少 name 字段返回 400。"""
        raw_token: str = self._create_reg_token(user)
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": raw_token,
        })
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_register_with_custom_scope_and_concurrent(
        self, api_client: APIClient, user: User
    ) -> None:
        """注册时指定 scope 和 concurrent 参数。"""
        raw_token: str = self._create_reg_token(user)
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": raw_token,
            "name": "custom-runner",
            "scope": "project",
            "concurrent": 4,
        })
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["scope"] == "project"
        runner = Runner.objects.get(name="custom-runner")
        assert runner.concurrent == 4

    def test_register_with_master_token(self, api_client: APIClient, settings) -> None:
        """共享注册令牌（env）可直接注册 Runner，无需 DB 一次性令牌。"""
        settings.RUNNER_REGISTRATION_TOKEN = "shared-master-token"
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": "shared-master-token",
            "name": "compose-runner",
        })
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "compose-runner"
        assert "runner_token" in data
        assert Runner.objects.filter(name="compose-runner").count() == 1
        # 不应消耗任何一次性令牌
        assert RegistrationToken.objects.count() == 0

    def test_register_with_master_token_is_idempotent_by_name(
        self, api_client: APIClient, settings
    ) -> None:
        """同名 Runner 用共享令牌重注册时幂等（轮换 token，不重复建实例）。"""
        settings.RUNNER_REGISTRATION_TOKEN = "shared-master-token"
        url: str = reverse("runner-register")
        first = api_client.post(url, {"token": "shared-master-token", "name": "compose-runner"})
        second = api_client.post(url, {"token": "shared-master-token", "name": "compose-runner"})
        assert first.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert Runner.objects.filter(name="compose-runner").count() == 1
        # token 已轮换
        assert first.json()["runner_token"] != second.json()["runner_token"]

    def test_register_with_wrong_master_token_falls_through(
        self, api_client: APIClient, settings
    ) -> None:
        """非共享令牌仍走 DB 一次性令牌校验，无效则 401。"""
        settings.RUNNER_REGISTRATION_TOKEN = "shared-master-token"
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": "not-the-master-token",
            "name": "compose-runner",
        })
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_master_token_disabled_when_empty(
        self, api_client: APIClient, settings
    ) -> None:
        """共享令牌为空时禁用该路径，空 token 不应放行。"""
        settings.RUNNER_REGISTRATION_TOKEN = ""
        url: str = reverse("runner-register")
        response = api_client.post(url, {
            "token": "",
            "name": "compose-runner",
        })
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_401_UNAUTHORIZED,
        )


@pytest.mark.django_db
class TestRunnerVerifyEndpoint:
    """GET /api/runners/verify/ -- Runner token 验证端点。"""

    def test_verify_valid_runner_token(self, api_client: APIClient) -> None:
        """有效 Runner token 验证返回 200。"""
        raw_token: str = "verify-test-runner-contract"
        Runner.objects.create(
            name="Verify Runner",
            token_hash=hash_token(raw_token),
            token_prefix=raw_token[:8],
        )
        url: str = reverse("runner-verify")
        response = api_client.get(
            url, HTTP_AUTHORIZATION=f"Bearer {raw_token}"
        )
        assert response.status_code == status.HTTP_200_OK

    def test_verify_invalid_token_returns_401(self, api_client: APIClient) -> None:
        """无效 token 返回 401 或 403。"""
        url: str = reverse("runner-verify")
        response = api_client.get(
            url, HTTP_AUTHORIZATION="Bearer invalid-token-xyz"
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

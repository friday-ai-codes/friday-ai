"""runners App 冒烟测试。"""
from datetime import timedelta
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
# ============================================================================
# Model 冒烟测试
# ============================================================================
@pytest.mark.django_db
class TestRunnerModel:
 """Runner 模型创建与查询。"""
 def test_create_runner(self):
 from runners.models import Runner, hash_token
 raw_token = "test-runner-token-smoke"
 runner = Runner.objects.create(
 name="Smoke Runner",
 token_hash=hash_token(raw_token),
 token_prefix=raw_token[:8],
 )
 assert Runner.objects.filter(pk=runner.pk).exists
 assert runner.name == "Smoke Runner"
@pytest.mark.django_db
class TestRegistrationTokenModel:
 """RegistrationToken 模型创建与查询。"""
 def test_create_registration_token(self, user):
 from runners.models import RegistrationToken, hash_token
 raw_token = "reg-token-smoke-test"
 token = RegistrationToken.objects.create(
 token_hash=hash_token(raw_token),
 expires_at=timezone.now + timedelta(hours=1),
 created_by=user,
 )
 assert RegistrationToken.objects.filter(pk=token.pk).exists
 assert not token.is_expired
# ============================================================================
# 认证冒烟测试
# ============================================================================
@pytest.mark.django_db
class TestRunnerTokenAuthentication:
 """Runner Bearer token 认证验证。"""
 def test_verify_with_valid_token(self, api_client):
 from runners.models import Runner, hash_token
 raw_token = "runner-verify-smoke-token"
 Runner.objects.create(
 name="Verify Runner",
 token_hash=hash_token(raw_token),
 token_prefix=raw_token[:8],
 )
 url = reverse("runner-verify")
 response = api_client.get(
 url, HTTP_AUTHORIZATION=f"Bearer {raw_token}"
 )
 assert response.status_code == status.HTTP_200_OK
 def test_verify_without_token_fails(self, api_client):
 url = reverse("runner-verify")
 response = api_client.get(url)
 assert response.status_code in (
 status.HTTP_401_UNAUTHORIZED,
 status.HTTP_403_FORBIDDEN,
 )

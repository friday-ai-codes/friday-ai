"""Phase: Webhook Secret 生成与全量索引统计修复测试
测试覆盖：
-: Webhook Secret 生成 API（generate_webhook_secret action）
-: 前端集成所需的 API 响应格式验证
"""
import re
import pytest
from rest_framework.test import APIClient
from repositories.models import Repository
pytestmark = pytest.mark.django_db(transaction=True)
# ============================================================================
# Webhook Secret 生成 API 测试
# ============================================================================
class TestGenerateWebhookSecret:
 """POST /api/repositories/{id}/generate-webhook-secret/ 测试。"""
 @pytest.fixture(autouse=True)
 def _setup(self, user) -> None:
 self.client = APIClient
 self.client.force_authenticate(user=user)
 self.repo = Repository.objects.create(
 name="Test Repo",
 git_url="https://github.com/test/repo.git",
 git_platform="github",
 default_branch="main",
 )
 self.url = f"/api/repositories/{self.repo.id}/generate-webhook-secret/"
 def test_generate_secret_returns_64_hex(self) -> None:
 """生成的 secret 应为 64 字符 hex 字符串。"""
 response = self.client.post(self.url)
 assert response.status_code == 200
 secret = response.data["webhook_secret"]
 assert len(secret) == 64
 assert re.fullmatch(r"[0-9a-f]{64}", secret)
 def test_secret_persisted_to_database(self) -> None:
 """secret 应持久化到数据库。"""
 response = self.client.post(self.url)
 secret = response.data["webhook_secret"]
 self.repo.refresh_from_db
 assert self.repo.webhook_secret == secret
 def test_regenerate_overwrites_old_secret(self) -> None:
 """重复调用应生成不同 secret，覆盖旧值。"""
 resp1 = self.client.post(self.url)
 resp2 = self.client.post(self.url)
 secret1 = resp1.data["webhook_secret"]
 secret2 = resp2.data["webhook_secret"]
 assert secret1 != secret2
 self.repo.refresh_from_db
 assert self.repo.webhook_secret == secret2
 def test_nonexistent_repo_returns_404(self) -> None:
 """不存在的仓库应返回 404。"""
 import uuid
 url = f"/api/repositories/{uuid.uuid4}/generate-webhook-secret/"
 response = self.client.post(url)
 assert response.status_code == 404

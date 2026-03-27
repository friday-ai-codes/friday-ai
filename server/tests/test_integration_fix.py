"""Phase 集成修复：InvitationView 权限测试。
验证 InvitationView GET（校验令牌）允许未认证访问，
POST（创建邀请）仍需认证。
"""
import pytest
from django.urls import reverse
from rest_framework import status
@pytest.mark.django_db
class TestInvitationViewPermissions:
 """InvitationView 按 HTTP method 分派权限。"""
 url = reverse("invite")
 def test_invitation_get_allows_unauthenticated(self, api_client):
 """未认证客户端 GET 应返回 404（令牌不存在）而非 401/403。"""
 response = api_client.get(self.url, {"token": "nonexistent-token"})
 # 404 表示进入了视图逻辑，权限检查已通过
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_invitation_post_requires_auth(self, api_client):
 """未认证客户端 POST 应返回 401（需要认证）。"""
 response = api_client.post(self.url, {})
 assert response.status_code == status.HTTP_401_UNAUTHORIZED

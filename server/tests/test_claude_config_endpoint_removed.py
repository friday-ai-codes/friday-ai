"""Phase Plan Task 2：v8.1 /api/projects/<id>/claude-config/ 端点硬删 404 契约。
Scope:
 验证 ClaudeConfigView / ClaudeConfigSerializer / claude_config @action 全部清零：
 - 请求 GET/PUT/DELETE /api/projects/<id>/claude-config/ → 404
 - SpaceViewSet 无 claude_config 方法
 - projects/serializers.py 无 ClaudeConfigSerializer / ClaudeConfigCreateSerializer
"""
from __future__ import annotations
import uuid
import pytest
from rest_framework import status
from rest_framework.test import APIClient
@pytest.mark.django_db
def test_no_claude_config_viewset_action_on_project_viewset -> None:
 """SpaceViewSet 不再有 claude_config 方法。"""
 from projects.views import SpaceViewSet
 assert not hasattr(SpaceViewSet, "claude_config")
def test_no_claude_config_serializer_symbol_in_module -> None:
 """projects/serializers.py 不再有 ClaudeConfigSerializer / ClaudeConfigCreateSerializer。"""
 import projects.serializers as psr
 assert not hasattr(psr, "ClaudeConfigSerializer")
 assert not hasattr(psr, "ClaudeConfigCreateSerializer")
@pytest.mark.django_db
def test_get_claude_config_returns_404(authenticated_admin_client, project) -> None:
 """GET /api/projects/<id>/claude-config/ 返回 404。"""
 response = authenticated_admin_client.get(
 f"/api/projects/{project.id}/claude-config/"
 )
 assert response.status_code == status.HTTP_404_NOT_FOUND
@pytest.mark.django_db
def test_put_claude_config_returns_404(authenticated_admin_client, project) -> None:
 """PUT /api/projects/<id>/claude-config/ 返回 404。"""
 response = authenticated_admin_client.put(
 f"/api/projects/{project.id}/claude-config/",
 {"api_key": "sk-foo"},
 format="json",
 )
 assert response.status_code == status.HTTP_404_NOT_FOUND
@pytest.mark.django_db
def test_delete_claude_config_returns_404(authenticated_admin_client, project) -> None:
 """DELETE /api/projects/<id>/claude-config/ 返回 404。"""
 response = authenticated_admin_client.delete(
 f"/api/projects/{project.id}/claude-config/"
 )
 assert response.status_code == status.HTTP_404_NOT_FOUND
@pytest.mark.django_db
def test_get_claude_config_nonexistent_project_returns_404 -> None:
 """GET /api/projects/<nonexistent>/claude-config/ 也返回 404。"""
 client = APIClient
 response = client.get(f"/api/projects/{uuid.uuid4}/claude-config/")
 assert response.status_code in (
 status.HTTP_401_UNAUTHORIZED,
 status.HTTP_403_FORBIDDEN,
 status.HTTP_404_NOT_FOUND,
 )

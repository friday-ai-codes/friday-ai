"""codegraph 视图权限测试 —— work item IDOR 修复验证。

验证 RepositoryPermission 正确拦截不存在仓库的请求，
同时确保合法用户可正常访问已存在仓库的接口。
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from repositories.models import Repository

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="perm_test_user",
        email="perm_test@example.com",
        password="testpassword",
    )


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def repo(db):
    return Repository.objects.create(
        name="perm-test-repo",
        git_url="https://example.com/perm-test.git",
        default_branch="main",
    )


@pytest.fixture
def deleted_repo(db):
    r = Repository.objects.create(
        name="deleted-repo",
        git_url="https://example.com/deleted.git",
        default_branch="main",
    )
    r.is_deleted = True
    r.save()
    return r


ENDPOINTS = [
    "/codegraph/symbols/",
    "/codegraph/imports/",
    "/codegraph/endpoints/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("path_suffix", ENDPOINTS)
def test_nonexistent_repo_returns_403(api_client, path_suffix):
    """不存在的 repository_id 应被 RepositoryPermission 拦截，返回 403。"""
    fake_id = uuid.uuid4()
    url = f"/api/repositories/{fake_id}{path_suffix}"
    response = api_client.get(url)
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("path_suffix", ENDPOINTS)
def test_deleted_repo_returns_403(api_client, deleted_repo, path_suffix):
    """软删除仓库应被 RepositoryPermission 拦截，返回 403。"""
    url = f"/api/repositories/{deleted_repo.id}{path_suffix}"
    response = api_client.get(url)
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("path_suffix", ENDPOINTS)
def test_existing_repo_accessible(api_client, repo, path_suffix):
    """合法认证用户访问存在的仓库接口应返回 200。"""
    url = f"/api/repositories/{repo.id}{path_suffix}"
    response = api_client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
def test_calls_for_nonexistent_repo_returns_403(api_client):
    """/calls/ 子端点：不存在的仓库应返回 403。"""
    fake_repo_id = uuid.uuid4()
    fake_symbol_id = uuid.uuid4()
    url = f"/api/repositories/{fake_repo_id}/codegraph/symbols/{fake_symbol_id}/calls/"
    response = api_client.get(url)
    assert response.status_code == 403

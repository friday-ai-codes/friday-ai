"""ImportEdgeListView API 测试 —— work item 覆盖。

测试端点：GET /api/repositories/{repository_id}/codegraph/imports/
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from codegraph.models import ImportEdge
from repositories.models import Repository

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="import_api_user",
        email="import_api@example.com",
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
        name="import-test-repo",
        git_url="https://example.com/import-test.git",
        default_branch="main",
    )


@pytest.fixture
def import_edges(repo):
    """创建 2 个 ImportEdge。"""
    e1 = ImportEdge.objects.create(
        repository=repo,
        source_file="src/views.py",
        target_module="django.db",
        imported_names=["models"],
        is_relative=False,
    )
    e2 = ImportEdge.objects.create(
        repository=repo,
        source_file="src/utils.py",
        target_module="django.utils",
        imported_names=["timezone"],
        is_relative=False,
    )
    return [e1, e2]


@pytest.mark.django_db
def test_import_list_returns_paginated(api_client, repo, import_edges):
    """work item: GET /imports/ 返回 {count, results}，含 source_file / target_module 字段。"""
    url = f"/api/repositories/{repo.id}/codegraph/imports/"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert "results" in data
    assert data["count"] == 2
    result = data["results"][0]
    assert "source_file" in result
    assert "target_module" in result
    assert "imported_names" in result
    assert "is_relative" in result


@pytest.mark.django_db
def test_import_filter_source_file(api_client, repo, import_edges):
    """work item: ?source_file=src/views 触发 source_file__startswith 过滤。"""
    url = f"/api/repositories/{repo.id}/codegraph/imports/?source_file=src/views"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["source_file"] == "src/views.py"


@pytest.mark.django_db
def test_import_filter_target_module(api_client, repo, import_edges):
    """work item: ?target_module=utils 触发 target_module__icontains 过滤。"""
    url = f"/api/repositories/{repo.id}/codegraph/imports/?target_module=utils"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert "utils" in data["results"][0]["target_module"]


@pytest.mark.django_db
def test_import_list_pagination(api_client, repo, import_edges):
    """work item: ?limit=1 → count=2, results 1 条。"""
    url = f"/api/repositories/{repo.id}/codegraph/imports/?limit=1&offset=0"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["results"]) == 1


@pytest.mark.django_db
def test_import_list_unauthenticated(repo, import_edges):
    """未认证请求返回 401/403。"""
    client = APIClient()
    url = f"/api/repositories/{repo.id}/codegraph/imports/"
    response = client.get(url)
    assert response.status_code in (401, 403)

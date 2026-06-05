"""SymbolListView API 测试 —— work item 覆盖。

测试端点：GET /api/repositories/{repository_id}/codegraph/symbols/
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from codegraph.models import Symbol
from repositories.models import Repository

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="symbol_api_user",
        email="symbol_api@example.com",
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
        name="symbol-test-repo",
        git_url="https://example.com/symbol-test.git",
        default_branch="main",
    )


@pytest.fixture
def symbols(repo):
    """创建 3 个 Symbol：2 个 FUNCTION，1 个 CLASS。"""
    s1 = Symbol.objects.create(
        repository=repo,
        name="process_data",
        symbol_type="FUNCTION",
        file_path="src/core.py",
        start_line=10,
        end_line=25,
        signature="def process_data(input: dict) -> dict",
    )
    s2 = Symbol.objects.create(
        repository=repo,
        name="validate_input",
        symbol_type="FUNCTION",
        file_path="src/validators.py",
        start_line=5,
        end_line=15,
        signature="def validate_input(data: dict) -> bool",
    )
    s3 = Symbol.objects.create(
        repository=repo,
        name="DataProcessor",
        symbol_type="CLASS",
        file_path="src/core.py",
        start_line=1,
        end_line=50,
        signature="class DataProcessor:",
    )
    return [s1, s2, s3]


@pytest.mark.django_db
def test_symbol_list_returns_paginated(api_client, repo, symbols):
    """work item: GET /codegraph/symbols/ 返回 {count, results}。"""
    url = f"/api/repositories/{repo.id}/codegraph/symbols/"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert "results" in data
    assert data["count"] == 3
    assert len(data["results"]) == 3


@pytest.mark.django_db
def test_symbol_list_alias_fields(api_client, repo, symbols):
    """work item: results[0] 含 line_start/line_end，不含 start_line/end_line（关键差异 1）。"""
    url = f"/api/repositories/{repo.id}/codegraph/symbols/"
    response = api_client.get(url)
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert "line_start" in result, "应含 line_start 别名字段"
    assert "line_end" in result, "应含 line_end 别名字段"
    assert "start_line" not in result, "不应暴露原始 start_line 字段"
    assert "end_line" not in result, "不应暴露原始 end_line 字段"


@pytest.mark.django_db
def test_symbol_list_filter_by_type(api_client, repo, symbols):
    """work item: ?symbol_type=FUNCTION 只返回 FUNCTION 类型。"""
    url = f"/api/repositories/{repo.id}/codegraph/symbols/?symbol_type=FUNCTION"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    for item in data["results"]:
        assert item["symbol_type"] == "FUNCTION"


@pytest.mark.django_db
def test_symbol_list_filter_by_name(api_client, repo, symbols):
    """work item: ?name=process 触发 name__icontains 过滤。"""
    url = f"/api/repositories/{repo.id}/codegraph/symbols/?name=process"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2  # process_data + DataProcessor
    names = {item["name"] for item in data["results"]}
    assert "process_data" in names
    assert "DataProcessor" in names


@pytest.mark.django_db
def test_symbol_list_filter_by_file_path(api_client, repo, symbols):
    """work item: ?file_path=src/core.py 触发 file_path__startswith 过滤。"""
    url = f"/api/repositories/{repo.id}/codegraph/symbols/?file_path=src/core.py"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2  # process_data + DataProcessor 都在 src/core.py
    for item in data["results"]:
        assert item["file_path"].startswith("src/core.py")


@pytest.mark.django_db
def test_symbol_list_pagination(api_client, repo, symbols):
    """work item: ?limit=2&offset=0 → count=3, results 2 条；response 含 offset/limit。"""
    url = f"/api/repositories/{repo.id}/codegraph/symbols/?limit=2&offset=0"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert len(data["results"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0


@pytest.mark.django_db
def test_symbol_list_limit_capped_at_200(api_client, repo, symbols):
    """security mitigation: limit 超过 200 被截断到 200，不报错。"""
    url = f"/api/repositories/{repo.id}/codegraph/symbols/?limit=9999"
    response = api_client.get(url)
    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 200


@pytest.mark.django_db
def test_symbol_list_unauthenticated(repo, symbols):
    """未认证请求返回 401/403。"""
    client = APIClient()
    url = f"/api/repositories/{repo.id}/codegraph/symbols/"
    response = client.get(url)
    assert response.status_code in (401, 403)

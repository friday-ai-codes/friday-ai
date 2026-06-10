"""CallsForSymbolView API 测试 —— work item 覆盖。

测试端点：GET /api/repositories/{repository_id}/codegraph/symbols/{symbol_id}/calls/
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from codegraph.models import Symbol
from repositories.models import Repository

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="calls_api_user",
        email="calls_api@example.com",
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
        name="calls-test-repo",
        git_url="https://example.com/calls-test.git",
        default_branch="main",
    )


@pytest.fixture
def seed_symbol(repo):
    return Symbol.objects.create(
        repository=repo,
        name="seed_function",
        symbol_type="FUNCTION",
        file_path="src/core.py",
        start_line=10,
        end_line=30,
    )


@pytest.fixture
def neighbor_symbol(repo):
    return Symbol.objects.create(
        repository=repo,
        name="neighbor_function",
        symbol_type="FUNCTION",
        file_path="src/utils.py",
        start_line=5,
        end_line=20,
    )


def _make_expand_result(seed: Symbol, neighbor: Symbol) -> dict[str, Any]:
    """构造 GraphExpansionService.expand() 的模拟返回值。"""
    return {
        "seed_symbol": seed,
        "nodes": [
            {"symbol": neighbor, "depth": 1, "relationship": "callee"},
        ],
        "edges": [
            {
                "source": str(seed.id),
                "target": str(neighbor.id),
                "call_type": "DIRECT",
            }
        ],
    }


@pytest.mark.django_db
def test_calls_returns_dag_structure(api_client, repo, seed_symbol, neighbor_symbol):
    """GET /calls/ 返回 {seed_symbol_id, nodes, edges}。"""
    expand_result = _make_expand_result(seed_symbol, neighbor_symbol)

    with patch(
        "codegraph.views.GraphExpansionService.expand",
        new=AsyncMock(return_value=expand_result),
    ):
        url = f"/api/repositories/{repo.id}/codegraph/symbols/{seed_symbol.id}/calls/"
        response = api_client.get(url)

    assert response.status_code == 200
    data = response.json()
    assert "seed_symbol_id" in data
    assert data["seed_symbol_id"] == str(seed_symbol.id)
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 1
    assert len(data["edges"]) == 1
    node = data["nodes"][0]
    assert "symbol" in node
    assert "depth" in node
    assert "relationship" in node


@pytest.mark.django_db
def test_calls_uuid_filter(api_client, repo, seed_symbol, neighbor_symbol):
    """graph_expansion L274 bug —— 注入非 UUID target，确认响应中全部被过滤。"""
    # 构造含非 UUID target 的边（graph_expansion L274 bug 场景）
    expand_result = {
        "seed_symbol": seed_symbol,
        "nodes": [{"symbol": neighbor_symbol, "depth": 1, "relationship": "callee"}],
        "edges": [
            # 合法 UUID edge
            {
                "source": str(seed_symbol.id),
                "target": str(neighbor_symbol.id),
                "call_type": "DIRECT",
            },
            # 非 UUID target（callee_name 字符串，L274 bug 产生）
            {
                "source": str(seed_symbol.id),
                "target": "some_function_name",
                "call_type": "DIRECT",
            },
            # 非 UUID source
            {
                "source": "not-a-uuid",
                "target": str(neighbor_symbol.id),
                "call_type": "METHOD",
            },
        ],
    }

    with patch(
        "codegraph.views.GraphExpansionService.expand",
        new=AsyncMock(return_value=expand_result),
    ):
        url = f"/api/repositories/{repo.id}/codegraph/symbols/{seed_symbol.id}/calls/"
        response = api_client.get(url)

    assert response.status_code == 200
    data = response.json()
    edges = data["edges"]
    # 只有 1 条合法 UUID edge 通过过滤
    assert len(edges) == 1
    # 验证保留的边 source/target 均为合法 UUID
    edge = edges[0]
    _validate_uuid(edge["source"])
    _validate_uuid(edge["target"])


def _validate_uuid(value: str) -> None:
    """断言字符串是合法 UUID 格式。"""
    try:
        uuid.UUID(value)
    except ValueError:
        pytest.fail(f"期望合法 UUID，实际收到: {value!r}")


@pytest.mark.django_db
def test_calls_symbol_not_found(api_client, repo):
    """访问不存在的 symbol_id 返回 404。"""
    non_existent_id = uuid.uuid4()
    url = f"/api/repositories/{repo.id}/codegraph/symbols/{non_existent_id}/calls/"
    response = api_client.get(url)
    assert response.status_code == 404

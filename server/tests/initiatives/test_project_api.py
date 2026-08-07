"""项目/成员 REST API 守护测试：权限 fail-closed + CRUD + 状态 + 幂等（Phase 77）。

覆盖 PROJ-03/05、MEMBER-01/02：非 Space 成员一律拒绝；Space admin 可创建/管理；
``(space, feishu_project_key)`` 幂等；状态非法流转 400。
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import Project
from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="API Space", feishu_project_key="api-space-key")


@pytest.fixture
def space_admin(db, space) -> object:
    u = User.objects.create_user(username="api_admin", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.ADMIN)
    return u


@pytest.fixture
def space_viewer(db, space) -> object:
    u = User.objects.create_user(username="api_viewer", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.VIEWER)
    return u


@pytest.fixture
def outsider(db) -> object:
    return User.objects.create_user(username="api_outsider", password="x")


@pytest.fixture(autouse=True)
def _no_workspace_provision(monkeypatch: pytest.MonkeyPatch) -> None:
    """挡掉建项目触发的后台工作区 provision 派发（CI flaky 根因）。

    本模块只守护 REST 权限/CRUD/状态机，provision 与断言无关；但它经
    background_runner 独立线程（独立 DB 连接）写 ProjectDoc，与测试的后续请求
    并发写共享内存 SQLite 会偶发 ``database table is locked``（server-ci 上
    ``test_illegal_status_transition_returns_400`` 的间歇失败即此）。provision
    自身行为由 tests/initiatives 的 workspace 专项测试覆盖，这里直接 no-op。
    """
    monkeypatch.setattr(
        "initiatives.services.project_doc_service.ProjectDocService.provision_dispatch",
        lambda self, project_id, initiated_by_user_id=None: None,
    )


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_outsider_cannot_create_project(space, outsider) -> None:
    resp = _client(outsider).post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "X", "feishu_project_key": "k1"},
        format="json",
    )
    assert resp.status_code == 403
    assert not Project.objects.filter(space=space).exists()


def test_viewer_cannot_create_project(space, space_viewer) -> None:
    resp = _client(space_viewer).post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "X", "feishu_project_key": "k2"},
        format="json",
    )
    assert resp.status_code == 403


def test_admin_creates_project_and_idempotent(space, space_admin) -> None:
    client = _client(space_admin)
    resp1 = client.post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "P", "feishu_project_key": "k3"},
        format="json",
    )
    assert resp1.status_code == 201
    pid = resp1.json()["id"]
    # 幂等：同 (space, key) 第二次返回既有项目（200）
    resp2 = client.post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "P-again", "feishu_project_key": "k3"},
        format="json",
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == pid
    assert Project.objects.filter(space=space, feishu_project_key="k3").count() == 1


def test_outsider_cannot_retrieve_project(space, space_admin, outsider) -> None:
    pid = (
        _client(space_admin)
        .post(
            "/api/projects/",
            {"space_id": str(space.id), "name": "P", "feishu_project_key": "k4"},
            format="json",
        )
        .json()["id"]
    )
    resp = _client(outsider).get(f"/api/projects/{pid}/")
    assert resp.status_code == 403


def test_viewer_can_retrieve_project(space, space_admin, space_viewer) -> None:
    pid = (
        _client(space_admin)
        .post(
            "/api/projects/",
            {"space_id": str(space.id), "name": "P", "feishu_project_key": "k5"},
            format="json",
        )
        .json()["id"]
    )
    resp = _client(space_viewer).get(f"/api/projects/{pid}/")
    assert resp.status_code == 200
    assert resp.json()["id"] == pid


def test_illegal_status_transition_returns_400(space, space_admin) -> None:
    client = _client(space_admin)
    pid = client.post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "P", "feishu_project_key": "k6"},
        format="json",
    ).json()["id"]
    # developing -> terminated（合法）
    assert (
        client.post(
            f"/api/projects/{pid}/transition/", {"to_status": "terminated"}, format="json"
        ).status_code
        == 200
    )
    # terminated -> developing（非法 -> 400）
    resp = client.post(
        f"/api/projects/{pid}/transition/", {"to_status": "developing"}, format="json"
    )
    assert resp.status_code == 400


def test_list_ordered_newest_first_and_plain_array(space, space_admin) -> None:
    """不带 limit：保持数组响应（既有调用方零改动），按 created_at 倒序。"""
    client = _client(space_admin)
    for i in range(3):
        client.post(
            "/api/projects/",
            {"space_id": str(space.id), "name": f"P{i}", "feishu_project_key": f"order-k{i}"},
            format="json",
        )
    resp = client.get("/api/projects/")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    created = [p["created_at"] for p in body]
    assert created == sorted(created, reverse=True)


def test_list_with_limit_returns_paginated_envelope(space, space_admin) -> None:
    """带 limit：返回 {results, total, limit, offset} 分页包，切片与总数正确。"""
    client = _client(space_admin)
    for i in range(5):
        client.post(
            "/api/projects/",
            {"space_id": str(space.id), "name": f"PG{i}", "feishu_project_key": f"page-k{i}"},
            format="json",
        )
    resp = client.get("/api/projects/", {"limit": "2", "offset": "0"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["results"]) == 2
    # 倒序：第一页第一条是最后创建的
    assert body["results"][0]["name"] == "PG4"

    # 翻页无重叠、无遗漏
    resp2 = client.get("/api/projects/", {"limit": "2", "offset": "2"})
    ids_page1 = {p["id"] for p in body["results"]}
    ids_page2 = {p["id"] for p in resp2.json()["results"]}
    assert not (ids_page1 & ids_page2)

    # 越过末尾：results 为空但 total 不变
    resp3 = client.get("/api/projects/", {"limit": "2", "offset": "10"})
    assert resp3.json()["results"] == []
    assert resp3.json()["total"] == 5


def test_list_pagination_params_are_sanitized(space, space_admin) -> None:
    """非法 limit/offset 回退默认值而非 500。"""
    client = _client(space_admin)
    client.post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "S", "feishu_project_key": "san-k"},
        format="json",
    )
    resp = client.get("/api/projects/", {"limit": "abc", "offset": "-3"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["limit"] == 24
    assert body["offset"] == 0


def test_add_member_via_api(space, space_admin) -> None:
    client = _client(space_admin)
    pid = client.post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "P", "feishu_project_key": "k7"},
        format="json",
    ).json()["id"]
    target = User.objects.create_user(username="api_member", password="x")
    resp = client.post(
        f"/api/projects/{pid}/members/",
        {"user_id": str(target.id), "role": "frontend"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "frontend"

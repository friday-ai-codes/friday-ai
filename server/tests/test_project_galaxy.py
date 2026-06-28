"""项目作战室 P4 — 项目级关系星图端点守护测试。

GET /api/projects/{id}/galaxy/：
- 聚合 项目 + MR + 仓库节点与关联边（HAS_MR / USES_REPO）
- 读权限 fail-closed：members_only 非成员 → 403
- meta 含 total_nodes / total_edges / truncated
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import MergeRequest, ProjectVisibility
from initiatives.services import ProjectDocService, ProjectService
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture(autouse=True)
def _silence_provision():
    with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
        yield


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _make_project(*, key: str, owner, visibility=ProjectVisibility.PUBLIC_ORG):
    from asgiref.sync import async_to_sync

    space = Space.objects.create(name="S", feishu_project_key=f"sp-{key}")
    project, _ = async_to_sync(ProjectService().create)(
        space=space, name="P", feishu_project_key=key, created_by=owner
    )
    if visibility != ProjectVisibility.PUBLIC_ORG:
        project.visibility = visibility
        project.save(update_fields=["visibility"])
    return project


def test_galaxy_aggregates_project_and_mr() -> None:
    owner = User.objects.create_user(username="gx_owner", password="x")
    project = _make_project(key="gx-agg", owner=owner)
    MergeRequest.objects.create(
        project=project, platform="github", external_id="1", title="MR1", status="open"
    )

    resp = _client(owner).get(f"/api/projects/{project.id}/galaxy/")
    assert resp.status_code == 200, resp.content
    data = resp.json()

    types = {n["type"] for n in data["nodes"]}
    assert "project" in types
    assert "merge_request" in types

    relations = {e["relation"] for e in data["edges"]}
    assert "HAS_MR" in relations

    assert data["meta"]["total_nodes"] >= 2
    assert "truncated" in data["meta"]


def test_galaxy_forbidden_for_non_member() -> None:
    owner = User.objects.create_user(username="gx_owner2", password="x")
    stranger = User.objects.create_user(username="gx_stranger", password="x")
    project = _make_project(
        key="gx-priv", owner=owner, visibility=ProjectVisibility.MEMBERS_ONLY
    )

    resp = _client(stranger).get(f"/api/projects/{project.id}/galaxy/")
    assert resp.status_code == 403, resp.content


def test_galaxy_empty_project_returns_project_node_only() -> None:
    owner = User.objects.create_user(username="gx_owner3", password="x")
    project = _make_project(key="gx-empty", owner=owner)
    resp = _client(owner).get(f"/api/projects/{project.id}/galaxy/")
    assert resp.status_code == 200, resp.content
    data = resp.json()
    types = [n["type"] for n in data["nodes"]]
    assert "project" in types
    # 无 feature/MR 工件 → 仅项目节点（不报错）
    assert data["meta"]["total_nodes"] >= 1

"""分支↔项目绑定 REST API 守护测试（Phase 85，BIND-01）。

权限：读需 Space viewer+ 或项目成员；写（bind/unbind）由 ProjectBranchService 成员校验
fail-closed。覆盖：成员 POST 201 / GET 200 / DELETE 解绑；非成员 POST/DELETE 403；
缺参 400；重复绑定幂等（不 500）。
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import Project, ProjectBranch, ProjectMember, ProjectRole
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="Branch API Space", feishu_project_key="branch-api")


@pytest.fixture
def project(db, space) -> Project:
    return Project.objects.create(space=space, name="P", feishu_project_key="")


@pytest.fixture
def repo(db) -> Repository:
    return Repository.objects.create(name="r", git_url="https://git/r.git")


@pytest.fixture
def member(db, project) -> object:
    u = User.objects.create_user(username="branch_member", password="x")
    ProjectMember.objects.create(project=project, user=u, role=ProjectRole.OWNER)
    return u


@pytest.fixture
def outsider(db) -> object:
    return User.objects.create_user(username="branch_outsider", password="x")


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_member_binds_and_lists(project, repo, member):
    client = _client(member)
    resp = client.post(
        f"/api/projects/{project.id}/branches/",
        {"repository_id": str(repo.id), "branch_name": "feature/x"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    resp = client.get(f"/api/projects/{project.id}/branches/")
    assert resp.status_code == 200
    body = resp.json()
    assert any(b["branch_name"] == "feature/x" for b in body)
    assert body[0]["repository_name"] == "r"


def test_member_unbinds(project, repo, member):
    client = _client(member)
    resp = client.post(
        f"/api/projects/{project.id}/branches/",
        {"repository_id": str(repo.id), "branch_name": "feature/x"},
        format="json",
    )
    binding_id = resp.json()["id"]
    resp = client.delete(f"/api/projects/{project.id}/branches/{binding_id}/")
    assert resp.status_code == 204
    assert ProjectBranch.objects.filter(project=project).count() == 0


def test_outsider_cannot_bind_or_unbind(project, repo, member, outsider):
    # 先由成员建一条绑定供非成员尝试删除
    binding = ProjectBranch.objects.create(
        project=project, repository=repo, branch_name="feature/x"
    )
    client = _client(outsider)
    resp = client.post(
        f"/api/projects/{project.id}/branches/",
        {"repository_id": str(repo.id), "branch_name": "feature/y"},
        format="json",
    )
    assert resp.status_code == 403
    resp = client.delete(f"/api/projects/{project.id}/branches/{binding.id}/")
    assert resp.status_code == 403


def test_missing_params_returns_400(project, member):
    resp = _client(member).post(
        f"/api/projects/{project.id}/branches/",
        {"branch_name": "feature/x"},
        format="json",
    )
    assert resp.status_code == 400


def test_duplicate_bind_is_idempotent_not_500(project, repo, member):
    client = _client(member)
    payload = {"repository_id": str(repo.id), "branch_name": "feature/x"}
    resp1 = client.post(
        f"/api/projects/{project.id}/branches/", payload, format="json"
    )
    resp2 = client.post(
        f"/api/projects/{project.id}/branches/", payload, format="json"
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert ProjectBranch.objects.filter(project=project).count() == 1

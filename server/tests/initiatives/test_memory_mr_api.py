"""项目记忆 / 草稿 / MR REST API 守护测试（Phase 80）。

权限：读需 Space viewer+ 或项目成员；记忆写入由 MemoryService 成员校验 fail-closed。
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import (
    MergeRequest,
    Project,
    ProjectMember,
    ProjectMemory,
    ProjectMemoryDraft,
    ProjectMemoryStatus,
    ProjectRole,
)
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="Mem API Space", feishu_project_key="mem-api-space")


@pytest.fixture
def project(db, space) -> Project:
    return Project.objects.create(space=space, name="P", feishu_project_key="")


@pytest.fixture
def member(db, project) -> object:
    u = User.objects.create_user(username="mem_member", password="x")
    ProjectMember.objects.create(project=project, user=u, role=ProjectRole.OWNER)
    return u


@pytest.fixture
def outsider(db) -> object:
    return User.objects.create_user(username="mem_outsider", password="x")


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_member_appends_and_lists_memory(project, member):
    client = _client(member)
    resp = client.post(
        f"/api/projects/{project.id}/memories/",
        {"content": "记忆A"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    resp = client.get(f"/api/projects/{project.id}/memories/")
    assert resp.status_code == 200
    assert any(m["content"] == "记忆A" for m in resp.json())


def test_outsider_cannot_access_memory(project, outsider):
    resp = _client(outsider).get(f"/api/projects/{project.id}/memories/")
    assert resp.status_code == 403


def test_member_edits_memory(project, member):
    memory = ProjectMemory.objects.create(
        project=project, content="v1", contributor=member, status=ProjectMemoryStatus.ACTIVE
    )
    resp = _client(member).patch(
        f"/api/projects/{project.id}/memories/{memory.id}/",
        {"content": "v2"},
        format="json",
    )
    assert resp.status_code == 200
    memory.refresh_from_db()
    assert memory.content == "v2"


def test_draft_confirm_via_api(project, member):
    draft = ProjectMemoryDraft.objects.create(project=project, content="候选")
    resp = _client(member).post(
        f"/api/projects/{project.id}/memory-drafts/{draft.id}/confirm/"
    )
    assert resp.status_code == 201, resp.content
    assert ProjectMemory.objects.filter(project=project).count() == 1
    draft.refresh_from_db()
    assert draft.status == "confirmed"


def test_merge_request_list(project, member):
    MergeRequest.objects.create(
        project=project, platform="github", external_id="1", status="open"
    )
    resp = _client(member).get(f"/api/projects/{project.id}/merge-requests/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

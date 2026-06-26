"""项目工作区 REST + 改归 + 可见性翻转守护测试（82-05）。

覆盖 WS-03 / DOC-02：
- ProjectService.update 白名单含 visibility（PATCH 可翻转）；feishu_folder_token 不可 PATCH。
- ProjectService.rehome_space 专用方法换空间 + 同空间幂等 + 目标空间不存在 fail-loud。
- ProjectDoc 列表（读权限）+ 一键重建（写权限，调 rebuild_workspace）。
- ProjectStateApi 列表 / 手动增删 REST（写经 ProjectDocService，INV-6 不旁路）。
- 写端点非 admin 403、读端点非 viewer/非成员 403。

REST 经 APIClient（adrf 异步视图）；service 半经 async + sync_to_async（transaction=True）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from audit.models import AuditEvent
from audit.services import taxonomy
from initiatives.models import (
    DocSyncStatus,
    DocType,
    Project,
    ProjectDoc,
    ProjectStateApi,
    ProjectVisibility,
)
from initiatives.services import ProjectDocService, ProjectRehomeError, ProjectService
from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture(autouse=True)
def _silence_provision():
    """建项目时不真正派发飞书 provision（隔离后台外呼）。"""
    with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
        yield


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="WS Space", feishu_project_key="ws-space-key")


@pytest.fixture
def other_space(db) -> Space:
    return Space.objects.create(name="WS Space 2", feishu_project_key="ws-space-key-2")


@pytest.fixture
def space_admin(db, space) -> object:
    u = User.objects.create_user(username="ws_admin", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.ADMIN)
    return u


@pytest.fixture
def space_viewer(db, space) -> object:
    u = User.objects.create_user(username="ws_viewer", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.VIEWER)
    return u


@pytest.fixture
def outsider(db) -> object:
    return User.objects.create_user(username="ws_outsider", password="x")


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _create_project(client, space, key) -> str:
    resp = client.post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "P", "feishu_project_key": key},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["id"]


# ============================ 可见性 PATCH ============================


def test_patch_visibility_takes_effect(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "vis1")
    resp = client.patch(
        f"/api/projects/{pid}/", {"visibility": "members_only"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["visibility"] == "members_only"
    assert Project.objects.get(pk=pid).visibility == ProjectVisibility.MEMBERS_ONLY


def test_patch_folder_token_is_ignored(space, space_admin) -> None:
    """feishu_folder_token 不在 update 白名单/serializer 字段——PATCH 不生效。"""
    client = _client(space_admin)
    pid = _create_project(client, space, "vis2")
    resp = client.patch(
        f"/api/projects/{pid}/", {"feishu_folder_token": "fldcnHACK"}, format="json"
    )
    assert resp.status_code == 200
    assert Project.objects.get(pk=pid).feishu_folder_token == ""


# ============================ 工作区文件列表 ============================


def test_workspace_docs_list(space, space_admin, space_viewer, outsider) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "docs1")
    for dt in (
        DocType.MEMORY,
        DocType.STATE,
        DocType.MILESTONES,
        DocType.RESEARCH,
        DocType.PREFLIGHT,
    ):
        ProjectDoc.objects.create(
            project_id=pid, doc_type=dt, sync_status=DocSyncStatus.READY
        )
    resp = _client(space_viewer).get(f"/api/projects/{pid}/workspace/docs/")
    assert resp.status_code == 200
    assert len(resp.json()) == 5
    # 非成员/非 viewer → 403
    assert (
        _client(outsider).get(f"/api/projects/{pid}/workspace/docs/").status_code == 403
    )


# ============================ 工作区一键重建 ============================


def test_workspace_rebuild_admin_triggers_service(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "rb1")
    with patch.object(
        ProjectDocService, "rebuild_workspace", new=AsyncMock(return_value=None)
    ) as mock_rebuild:
        resp = client.post(f"/api/projects/{pid}/workspace/rebuild/")
    assert resp.status_code == 202
    mock_rebuild.assert_awaited_once()
    kwargs = mock_rebuild.await_args.kwargs
    assert str(kwargs["project_id"]) == pid
    assert kwargs["initiated_by_user_id"] == space_admin.id


def test_workspace_rebuild_viewer_forbidden(space, space_admin, space_viewer) -> None:
    pid = _create_project(_client(space_admin), space, "rb2")
    resp = _client(space_viewer).post(f"/api/projects/{pid}/workspace/rebuild/")
    assert resp.status_code == 403


# ============================ 改归空间 ============================


def test_rehome_admin_changes_space(space, other_space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "rh1")
    resp = client.post(
        f"/api/projects/{pid}/rehome/",
        {"new_space_id": str(other_space.id)},
        format="json",
    )
    assert resp.status_code == 200
    assert str(Project.objects.get(pk=pid).space_id) == str(other_space.id)
    assert AuditEvent.objects.filter(
        action=taxonomy.ACTION_PROJECT_SPACE_REHOMED, target_id=str(pid)
    ).count() == 1


def test_rehome_missing_space_404(space, space_admin) -> None:
    import uuid

    client = _client(space_admin)
    pid = _create_project(client, space, "rh2")
    resp = client.post(
        f"/api/projects/{pid}/rehome/",
        {"new_space_id": str(uuid.uuid4())},
        format="json",
    )
    assert resp.status_code == 404


def test_rehome_viewer_forbidden(space, other_space, space_admin, space_viewer) -> None:
    pid = _create_project(_client(space_admin), space, "rh3")
    resp = _client(space_viewer).post(
        f"/api/projects/{pid}/rehome/",
        {"new_space_id": str(other_space.id)},
        format="json",
    )
    assert resp.status_code == 403


# ============================ 结构化 API 清单 REST ============================


def test_state_api_create_list_delete(space, space_admin, space_viewer) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "sa1")
    # 新增
    resp = client.post(
        f"/api/projects/{pid}/workspace/state-apis/",
        {"method": "GET", "path": "/foo", "status": "planned"},
        format="json",
    )
    assert resp.status_code == 201
    api_id = resp.json()["id"]
    assert ProjectStateApi.objects.filter(pk=api_id).exists()
    # 重复 (method, path) 幂等：返回既有（200，不重复建）
    resp_dup = client.post(
        f"/api/projects/{pid}/workspace/state-apis/",
        {"method": "GET", "path": "/foo"},
        format="json",
    )
    assert resp_dup.status_code == 200
    assert resp_dup.json()["id"] == api_id
    assert ProjectStateApi.objects.filter(project_id=pid).count() == 1
    # 读列表（viewer 可读）
    resp_list = _client(space_viewer).get(
        f"/api/projects/{pid}/workspace/state-apis/"
    )
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1
    # 删除
    resp_del = client.delete(
        f"/api/projects/{pid}/workspace/state-apis/{api_id}/"
    )
    assert resp_del.status_code == 204
    assert not ProjectStateApi.objects.filter(pk=api_id).exists()


def test_state_api_create_viewer_forbidden(space, space_admin, space_viewer) -> None:
    pid = _create_project(_client(space_admin), space, "sa2")
    resp = _client(space_viewer).post(
        f"/api/projects/{pid}/workspace/state-apis/",
        {"method": "POST", "path": "/bar"},
        format="json",
    )
    assert resp.status_code == 403


def test_state_api_delete_missing_404(space, space_admin) -> None:
    import uuid

    client = _client(space_admin)
    pid = _create_project(client, space, "sa3")
    resp = client.delete(
        f"/api/projects/{pid}/workspace/state-apis/{uuid.uuid4()}/"
    )
    assert resp.status_code == 404


# ============================ service 半：update / rehome_space ============================


@sync_to_async
def _make_space(name: str, key: str) -> Space:
    return Space.objects.create(name=name, feishu_project_key=key)


@sync_to_async
def _make_user(username: str) -> object:
    return User.objects.create_user(username=username, password="x")


async def _make_project_svc(space: Space, key: str) -> Project:
    user = await _make_user(f"u-{key}")
    project, _ = await ProjectService().create(
        space=space, name="P", created_by=user, feishu_project_key=key
    )
    return project


async def test_service_update_visibility_lands() -> None:
    space = await _make_space("S-svc-1", "svc1")
    project = await _make_project_svc(space, "svc1")
    await ProjectService().update(
        project_id=project.id, visibility=ProjectVisibility.MEMBERS_ONLY
    )
    refreshed = await Project.objects.aget(pk=project.id)
    assert refreshed.visibility == ProjectVisibility.MEMBERS_ONLY


async def test_service_update_ignores_folder_token() -> None:
    space = await _make_space("S-svc-2", "svc2")
    project = await _make_project_svc(space, "svc2")
    await ProjectService().update(project_id=project.id, feishu_folder_token="fldcnX")
    refreshed = await Project.objects.aget(pk=project.id)
    assert refreshed.feishu_folder_token == ""


async def test_service_rehome_idempotent_same_space() -> None:
    space = await _make_space("S-svc-3", "svc3")
    project = await _make_project_svc(space, "svc3")
    await ProjectService().rehome_space(
        project_id=project.id, new_space_id=space.id
    )
    # 同空间幂等：不产生 space_rehomed 审计
    assert not await AuditEvent.objects.filter(
        action=taxonomy.ACTION_PROJECT_SPACE_REHOMED, target_id=str(project.id)
    ).aexists()


async def test_service_rehome_missing_space_fail_loud() -> None:
    import uuid

    space = await _make_space("S-svc-4", "svc4")
    project = await _make_project_svc(space, "svc4")
    with pytest.raises(ProjectRehomeError):
        await ProjectService().rehome_space(
            project_id=project.id, new_space_id=uuid.uuid4()
        )

"""工件 / 类型 / 知识关联 REST API 守护测试（ARTIFACT-01/02/03，KLINK-01/02）。

权限 fail-closed：工件 CRUD 需 Space admin+；类型管理需超管；查看需 Space viewer+。
"""

from __future__ import annotations

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from initiatives.models import Artifact, ArtifactType, Project
from knowledge.models import EntityKind, EntityOrigin, KnowledgeEntity, generate_entity_id
from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="API Space", feishu_project_key="art-api-space")


@pytest.fixture
def project(db, space) -> Project:
    return Project.objects.create(space=space, name="P", feishu_project_key="")


@pytest.fixture
def admin(db, space) -> object:
    u = User.objects.create_user(username="art_admin", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.ADMIN)
    return u


@pytest.fixture
def viewer(db, space) -> object:
    u = User.objects.create_user(username="art_viewer", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.VIEWER)
    return u


@pytest.fixture
def outsider(db) -> object:
    return User.objects.create_user(username="art_outsider", password="x")


@pytest.fixture
def superuser(db) -> object:
    u = User.objects.create_user(username="art_su", password="x")
    u.is_superuser = True
    u.is_staff = True
    u.save(update_fields=["is_superuser", "is_staff"])
    return u


@pytest.fixture
def ui_type(db) -> ArtifactType:
    # UI 稿（external_link / ragable=False）：创建工件不触发 RAG 调度。
    # 直接造（transaction=True 会清空迁移 seed 行，故不依赖 seed）。
    return ArtifactType.objects.create(
        key="ui_design_t", name="UI 稿", carrier="external_link", ragable=False, builtin=True
    )


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_outsider_cannot_create_artifact(project, outsider, ui_type) -> None:
    resp = _client(outsider).post(
        f"/api/projects/{project.id}/artifacts/",
        {"type_id": str(ui_type.id), "title": "X", "url": "https://figma.com/x"},
        format="json",
    )
    assert resp.status_code == 403


def test_viewer_cannot_create_artifact(project, viewer, ui_type) -> None:
    resp = _client(viewer).post(
        f"/api/projects/{project.id}/artifacts/",
        {"type_id": str(ui_type.id), "title": "X", "url": "https://figma.com/x"},
        format="json",
    )
    assert resp.status_code == 403


def test_admin_creates_and_lists_and_views_artifact(project, admin, ui_type) -> None:
    client = _client(admin)
    resp = client.post(
        f"/api/projects/{project.id}/artifacts/",
        {"type_id": str(ui_type.id), "title": "UI 稿", "url": "https://figma.com/x"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    artifact_id = resp.json()["id"]
    assert resp.json()["carrier"] == "external_link"

    # list
    resp = client.get(f"/api/projects/{project.id}/artifacts/")
    assert resp.status_code == 200
    assert any(a["id"] == artifact_id for a in resp.json())

    # online view（外链元数据）
    resp = client.get(f"/api/projects/{project.id}/artifacts/{artifact_id}/view/")
    assert resp.status_code == 200
    assert resp.json()["render_type"] == "link"


def test_viewer_can_view_artifact(project, admin, viewer, ui_type) -> None:
    a = Artifact.objects.create(
        project=project, type=ui_type, carrier="external_link", title="X", url="https://x"
    )
    resp = _client(viewer).get(f"/api/projects/{project.id}/artifacts/{a.id}/view/")
    assert resp.status_code == 200


def test_artifact_type_list_open_create_superuser_only(admin, superuser) -> None:
    # 列表已认证可读
    resp = _client(admin).get("/api/artifact-types/")
    assert resp.status_code == 200

    # 非超管不可新增
    resp = _client(admin).post(
        "/api/artifact-types/",
        {"key": "x_type", "name": "X", "carrier": "markdown"},
        format="json",
    )
    assert resp.status_code == 403

    # 超管可新增 + 新增后列表可见
    resp = _client(superuser).post(
        "/api/artifact-types/",
        {"key": "x_type", "name": "X", "carrier": "markdown"},
        format="json",
    )
    assert resp.status_code == 201
    resp = _client(admin).get("/api/artifact-types/")
    assert any(t["key"] == "x_type" for t in resp.json())


def test_builtin_type_delete_refused(superuser) -> None:
    builtin = ArtifactType.objects.create(
        key="builtin_api", name="内置", carrier="feishu_doc", ragable=True, builtin=True
    )
    resp = _client(superuser).delete(f"/api/artifact-types/{builtin.id}/")
    assert resp.status_code == 409
    assert ArtifactType.objects.filter(pk=builtin.id).exists()


def test_link_knowledge_and_query_graph(project, admin) -> None:
    sid = uuid.uuid4().hex
    entity = KnowledgeEntity.objects.create(
        id=generate_entity_id(EntityKind.DOCUMENT, "feishu_document", sid),
        kind=EntityKind.DOCUMENT,
        origin=EntityOrigin.FEISHU,
        source_kind="feishu_document",
        source_id=sid,
        title="知识",
        event_time=timezone.now(),
    )
    client = _client(admin)
    resp = client.post(
        f"/api/projects/{project.id}/knowledge/",
        {"entity_id": str(entity.id)},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert resp.json()["created"] is True

    resp = client.get(f"/api/projects/{project.id}/graph/")
    assert resp.status_code == 200
    entity_ids = {n["entity_id"] for n in resp.json()["nodes"]}
    assert str(entity.id) in entity_ids

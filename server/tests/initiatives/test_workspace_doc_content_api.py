"""工作区单文档内容 + 人工区写回 + StateApi PATCH 守护测试（84-01 Task 1/2）。

覆盖 WB-03 后端读写：
- 单文档内容 GET：rendered_markdown + blocks（system editable=false / human editable=true）；
  非法 doc_type → 400；非可见项目 → 403。
- 人工区写回 PUT：触发同步引擎 push（spy 断言 schedule_doc_push 被调度）+ sync_status=syncing；
  写 system block → 409；非项目成员 → 403。
- StateApi PATCH：更新单条字段；缺失 → 404。

REST 经 APIClient（adrf 异步视图）；写收口经 ProjectDocService（INV-6 不旁路）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import (
    ApiStatus,
    DocSection,
    DocSyncStatus,
    DocType,
    ProjectDoc,
    ProjectDocBlockMap,
    ProjectDocBlockRevision,
    ProjectStateApi,
)
from initiatives.services import ProjectDocService
from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture(autouse=True)
def _silence_provision():
    with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
        yield


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="DC Space", feishu_project_key="dc-space-key")


@pytest.fixture
def space_admin(db, space) -> object:
    u = User.objects.create_user(username="dc_admin", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.ADMIN)
    return u


@pytest.fixture
def space_viewer(db, space) -> object:
    """Space viewer 但**非**项目成员（人工区写应 403）。"""
    u = User.objects.create_user(username="dc_viewer", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.VIEWER)
    return u


@pytest.fixture
def outsider(db) -> object:
    return User.objects.create_user(username="dc_outsider", password="x")


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


def _seed_state_doc(project_id: str) -> tuple[str, str]:
    """建 STATE 文档 + 1 系统 block（映射到 state api）+ 1 人工 block（带留痕）。"""
    doc = ProjectDoc.objects.create(
        project_id=project_id,
        doc_type=DocType.STATE,
        sync_status=DocSyncStatus.READY,
        last_synced_snapshot="# 项目状态\n\nGET /x — planned",
        last_synced_revision=3,
    )
    api = ProjectStateApi.objects.create(
        project_id=project_id, method="GET", path="/x", status=ApiStatus.PLANNED
    )
    ProjectDocBlockMap.objects.create(
        doc=doc,
        feishu_block_id="blk-sys",
        db_ref=str(api.id),
        section=DocSection.SYSTEM,
        content_hash="h1",
    )
    ProjectDocBlockMap.objects.create(
        doc=doc,
        feishu_block_id="blk-hum",
        db_ref="",
        section=DocSection.HUMAN,
        content_hash="h2",
    )
    ProjectDocBlockRevision.objects.create(
        doc=doc, feishu_block_id="blk-hum", content="人工区内容", source="human"
    )
    return str(doc.id), str(api.id)


# ============================ 文档内容 GET ============================


def test_doc_content_returns_markdown_and_sections(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "dc1")
    _seed_state_doc(pid)

    resp = client.get(f"/api/projects/{pid}/workspace/docs/state/")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["doc_type"] == "state"
    assert "GET /x" in body["rendered_markdown"]
    assert body["sync_status"] == DocSyncStatus.READY
    assert body["last_synced_revision"] == 3

    by_id = {b["block_id"]: b for b in body["blocks"]}
    assert by_id["blk-sys"]["editable"] is False
    assert by_id["blk-sys"]["section"] == "system"
    assert by_id["blk-sys"]["text"] == "GET /x — planned"
    assert by_id["blk-hum"]["editable"] is True
    assert by_id["blk-hum"]["section"] == "human"
    assert by_id["blk-hum"]["text"] == "人工区内容"


def test_doc_content_invalid_doc_type_400(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "dc2")
    resp = client.get(f"/api/projects/{pid}/workspace/docs/bogus/")
    assert resp.status_code == 400


def test_doc_content_missing_doc_404(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "dc3")
    # 未建 research 文档
    resp = client.get(f"/api/projects/{pid}/workspace/docs/research/")
    assert resp.status_code == 404


def test_doc_content_outsider_forbidden(space, space_admin, outsider) -> None:
    pid = _create_project(_client(space_admin), space, "dc4")
    _seed_state_doc(pid)
    resp = _client(outsider).get(f"/api/projects/{pid}/workspace/docs/state/")
    assert resp.status_code == 403


# ============================ 人工区写回 PUT ============================


def test_human_write_triggers_push_and_syncing(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "hw1")
    _seed_state_doc(pid)

    with patch(
        "initiatives.services.doc_content_service.schedule_doc_push",
        new=AsyncMock(return_value=None),
    ) as spy:
        resp = client.put(
            f"/api/projects/{pid}/workspace/docs/state/human-blocks/",
            {"blocks": [{"block_id": "blk-hum", "text": "新的人工区文本"}]},
            format="json",
        )
    assert resp.status_code == 200, resp.content
    assert resp.json()["sync_status"] == "syncing"
    assert resp.json()["written"] == 1
    spy.assert_awaited_once()
    # append-only 留痕：最新一条 human 留痕即新文本。
    latest = (
        ProjectDocBlockRevision.objects.filter(
            feishu_block_id="blk-hum", source="human"
        )
        .order_by("-captured_at")
        .first()
    )
    assert latest is not None and latest.content == "新的人工区文本"


def test_human_write_system_block_rejected(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "hw2")
    _seed_state_doc(pid)
    resp = client.put(
        f"/api/projects/{pid}/workspace/docs/state/human-blocks/",
        {"blocks": [{"block_id": "blk-sys", "text": "想改系统区"}]},
        format="json",
    )
    assert resp.status_code == 409


def test_human_write_non_member_forbidden(space, space_admin, space_viewer) -> None:
    pid = _create_project(_client(space_admin), space, "hw3")
    _seed_state_doc(pid)
    resp = _client(space_viewer).put(
        f"/api/projects/{pid}/workspace/docs/state/human-blocks/",
        {"blocks": [{"block_id": "blk-hum", "text": "非成员写"}]},
        format="json",
    )
    assert resp.status_code == 403


def test_human_write_unknown_block_404(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "hw4")
    _seed_state_doc(pid)
    resp = client.put(
        f"/api/projects/{pid}/workspace/docs/state/human-blocks/",
        {"blocks": [{"block_id": "blk-nope", "text": "x"}]},
        format="json",
    )
    assert resp.status_code == 404


# ============================ StateApi PATCH ============================


def test_state_api_patch_updates_field(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "sap1")
    resp = client.post(
        f"/api/projects/{pid}/workspace/state-apis/",
        {"method": "GET", "path": "/foo", "status": "planned"},
        format="json",
    )
    assert resp.status_code == 201
    api_id = resp.json()["id"]

    resp_patch = client.patch(
        f"/api/projects/{pid}/workspace/state-apis/{api_id}/",
        {"status": "implemented"},
        format="json",
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["status"] == "implemented"
    assert ProjectStateApi.objects.get(pk=api_id).status == ApiStatus.IMPLEMENTED


def test_state_api_patch_missing_404(space, space_admin) -> None:
    import uuid

    client = _client(space_admin)
    pid = _create_project(client, space, "sap2")
    resp = client.patch(
        f"/api/projects/{pid}/workspace/state-apis/{uuid.uuid4()}/",
        {"status": "implemented"},
        format="json",
    )
    assert resp.status_code == 404


def test_state_api_patch_viewer_forbidden(space, space_admin, space_viewer) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "sap3")
    resp = client.post(
        f"/api/projects/{pid}/workspace/state-apis/",
        {"method": "GET", "path": "/bar"},
        format="json",
    )
    api_id = resp.json()["id"]
    resp_patch = _client(space_viewer).patch(
        f"/api/projects/{pid}/workspace/state-apis/{api_id}/",
        {"status": "implemented"},
        format="json",
    )
    assert resp_patch.status_code == 403

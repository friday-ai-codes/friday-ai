"""ArtifactOverviewView 聚合接口测试（KDEP-03）。

覆盖：access_scope 过滤（仅可见 Space 的工件）、类型分组计数、type_key 预筛、空 scope。
纯 PG 聚合，不触 Qdrant（本接口无向量调用）。
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from initiatives.models import Artifact, ArtifactType, ProjectVisibility
from initiatives.models import Project as InitiativeProject
from projects.models import Space

pytestmark = pytest.mark.django_db

URL = "/api/knowledge/artifacts/overview/"


def _make_project(space, name):
    return InitiativeProject.objects.create(
        space=space, name=name, feishu_project_key="", visibility=ProjectVisibility.MEMBERS_ONLY
    )


def _make_artifact(iproject, atype, title, carrier="markdown", url=""):
    return Artifact.objects.create(
        project=iproject, type=atype, carrier=carrier, title=title, url=url, version=1
    )


def test_overview_scopes_to_visible_spaces(
    project, user, project_memberships, authenticated_client
):
    """仅统计当前用户可见 Space 的工件；他项目工件不可见。"""
    space_b = Space.objects.create(name="Space B", feishu_project_key="space-b-key")
    iproj_a = _make_project(project, "项目A")
    iproj_b = _make_project(space_b, "项目B")
    prd = ArtifactType.objects.create(key="prd", name="PRD", carrier="markdown", ragable=True)
    ui = ArtifactType.objects.create(key="ui", name="UI 稿", carrier="external_link", ragable=False)
    _make_artifact(iproj_a, prd, "需求1")
    _make_artifact(iproj_a, prd, "需求2")
    _make_artifact(iproj_a, ui, "UI1", carrier="external_link", url="https://figma.com/x")
    _make_artifact(iproj_b, prd, "越权需求")  # Space B，用户无 membership → 不可见

    resp = authenticated_client.get(URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3  # 仅 Space A 的 3 条
    counts = {t["type_key"]: t["count"] for t in body["types"]}
    assert counts == {"prd": 2, "ui": 1}
    titles = {i["title"] for i in body["items"]}
    assert titles == {"需求1", "需求2", "UI1"}
    assert "越权需求" not in titles

    item = next(i for i in body["items"] if i["title"] == "UI1")
    assert item["type_name"] == "UI 稿"
    assert item["carrier"] == "external_link"
    assert item["url"] == "https://figma.com/x"
    assert item["project_name"] == "项目A"
    assert "artifact_id" in item
    assert body["truncated"] is False


def test_overview_type_key_prefilter(
    project, user, project_memberships, authenticated_client
):
    """?type_key= 预筛收窄计数与列表。"""
    iproj = _make_project(project, "项目A")
    prd = ArtifactType.objects.create(key="prd", name="PRD", carrier="markdown", ragable=True)
    ui = ArtifactType.objects.create(key="ui", name="UI 稿", carrier="external_link", ragable=False)
    _make_artifact(iproj, prd, "需求1")
    _make_artifact(iproj, ui, "UI1", carrier="external_link")

    resp = authenticated_client.get(URL, {"type_key": "prd"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert {t["type_key"] for t in body["types"]} == {"prd"}
    assert {i["title"] for i in body["items"]} == {"需求1"}


def test_overview_no_visible_project_empty(other_user):
    """无可见 project 的用户 → 空结构（非 500）。"""
    client = APIClient()
    client.force_authenticate(user=other_user)
    resp = client.get(URL)
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "types": [], "items": [], "truncated": False}

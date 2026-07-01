"""ArtifactTreeView 嵌套树接口测试（KDEP-06）。

覆盖：access_scope 过滤（仅可见 Space 的工件、嵌套层级）、类型嵌套分组、空 scope。
纯 PG 聚合，不触 Qdrant（本接口无向量调用）。
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from initiatives.models import Artifact, ArtifactType, ProjectVisibility
from initiatives.models import Project as InitiativeProject
from projects.models import Space

pytestmark = pytest.mark.django_db

URL = "/api/knowledge/artifacts/tree/"


def _make_project(space, name):
    return InitiativeProject.objects.create(
        space=space, name=name, feishu_project_key="", visibility=ProjectVisibility.MEMBERS_ONLY
    )


def _make_artifact(iproject, atype, title, carrier="markdown", url=""):
    return Artifact.objects.create(
        project=iproject, type=atype, carrier=carrier, title=title, url=url, version=1
    )


def test_tree_scopes_to_visible_spaces(
    project, user, project_memberships, authenticated_client
):
    """仅返回当前用户可见 Space 的项目节点；他 Space 项目/工件不可见，嵌套层级正确。"""
    space_b = Space.objects.create(name="Space B", feishu_project_key="space-b-key")
    iproj_a1 = _make_project(project, "项目A1")
    iproj_a2 = _make_project(project, "项目A2")
    iproj_b = _make_project(space_b, "项目B")
    prd = ArtifactType.objects.create(key="prd", name="PRD", carrier="markdown", ragable=True)
    ui = ArtifactType.objects.create(key="ui", name="UI 稿", carrier="external_link", ragable=False)
    _make_artifact(iproj_a1, prd, "需求1")
    _make_artifact(iproj_a1, prd, "需求2")
    _make_artifact(iproj_a1, ui, "UI1", carrier="external_link", url="https://figma.com/x")
    _make_artifact(iproj_a2, prd, "需求3")
    _make_artifact(iproj_b, prd, "越权需求")  # Space B，用户无 membership → 不可见

    resp = authenticated_client.get(URL)
    assert resp.status_code == 200
    body = resp.json()

    assert body["total"] == 4  # 仅 Space A 的 4 条
    assert body["truncated"] is False

    project_names = {p["project_name"] for p in body["projects"]}
    assert project_names == {"项目A1", "项目A2"}
    assert "项目B" not in project_names

    proj_a1 = next(p for p in body["projects"] if p["project_name"] == "项目A1")
    assert proj_a1["count"] == 3
    types_a1 = {t["type_key"]: t for t in proj_a1["types"]}
    assert set(types_a1) == {"prd", "ui"}
    assert types_a1["prd"]["count"] == 2
    assert types_a1["ui"]["count"] == 1

    prd_titles = {a["title"] for a in types_a1["prd"]["artifacts"]}
    assert prd_titles == {"需求1", "需求2"}

    leaf = types_a1["ui"]["artifacts"][0]
    assert set(leaf) == {"artifact_id", "title", "carrier", "url", "updated_at"}
    assert leaf["title"] == "UI1"
    assert leaf["carrier"] == "external_link"
    assert leaf["url"] == "https://figma.com/x"
    assert "project_id" not in leaf  # 叶子不含冗余 project_id

    all_titles = {
        a["title"]
        for p in body["projects"]
        for t in p["types"]
        for a in t["artifacts"]
    }
    assert "越权需求" not in all_titles


def test_tree_nested_grouping(
    project, user, project_memberships, authenticated_client
):
    """单项目下混两类型：类型节点带 type_name/carrier/ragable/count，外链 url 透传。"""
    iproj = _make_project(project, "项目A")
    prd = ArtifactType.objects.create(key="prd", name="PRD", carrier="markdown", ragable=True)
    ui = ArtifactType.objects.create(key="ui", name="UI 稿", carrier="external_link", ragable=False)
    _make_artifact(iproj, prd, "需求1")
    _make_artifact(iproj, ui, "UI1", carrier="external_link", url="https://figma.com/y")

    resp = authenticated_client.get(URL)
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["projects"]) == 1
    proj = body["projects"][0]
    assert proj["count"] == 2
    types = {t["type_key"]: t for t in proj["types"]}
    assert set(types) == {"prd", "ui"}

    assert types["prd"]["type_name"] == "PRD"
    assert types["prd"]["carrier"] == "markdown"
    assert types["prd"]["ragable"] is True
    assert types["prd"]["count"] == 1

    assert types["ui"]["type_name"] == "UI 稿"
    assert types["ui"]["carrier"] == "external_link"
    assert types["ui"]["ragable"] is False
    assert types["ui"]["artifacts"][0]["url"] == "https://figma.com/y"


def test_tree_no_visible_project_empty(other_user):
    """无可见 project 的用户 → 空结构（非 500）。"""
    client = APIClient()
    client.force_authenticate(user=other_user)
    resp = client.get(URL)
    assert resp.status_code == 200
    assert resp.json() == {"total": 0, "projects": [], "truncated": False}

"""Cursor rules 模板生成 + API 守护测试（CURSOR-02）。"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import Project, ProjectMember, ProjectRole
from initiatives.services.cursor_rules import (
    build_project_cursor_rules,
    cursor_rules_filename,
)
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="Rules Space", feishu_project_key="rules-space")


@pytest.fixture
def project(db, space) -> Project:
    return Project.objects.create(
        space=space, name="登录重构项目", feishu_project_key="login-key"
    )


@pytest.fixture
def member(db, project) -> object:
    u = User.objects.create_user(username="rules_member", password="x")
    ProjectMember.objects.create(project=project, user=u, role=ProjectRole.OWNER)
    return u


def test_build_rules_contains_mandatory_flow(project) -> None:
    text = build_project_cursor_rules(project)
    # 强制「先关联本分支项目、召回、再编码、后上报沉淀」。
    assert "lookup_project_by_branch" in text
    assert "report_project_knowledge" in text
    assert "alwaysApply: true" in text
    assert project.name in text
    assert str(project.id) in text


def test_filename(project) -> None:
    assert cursor_rules_filename(project) == f"friday-project-{project.id}.mdc"


def test_api_returns_rules_for_member(project, member) -> None:
    client = APIClient()
    client.force_authenticate(user=member)
    resp = client.get(f"/api/projects/{project.id}/cursor-rules/")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["filename"].endswith(".mdc")
    assert "lookup_project_by_branch" in body["content"]


def test_api_forbidden_for_outsider(project) -> None:
    outsider = User.objects.create_user(username="rules_outsider", password="x")
    client = APIClient()
    client.force_authenticate(user=outsider)
    resp = client.get(f"/api/projects/{project.id}/cursor-rules/")
    assert resp.status_code == 403

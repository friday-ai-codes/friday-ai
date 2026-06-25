"""项目工作项组合 REST API 守护测试（COMPOSE-01/02，Phase 81 surface）。

覆盖：超管 attach（手动并入）/ 幂等 409 / list 派生摘要 / detach。
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from delivery.models import WorkItem
from initiatives.models import Project, ProjectWorkItemLink
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="WI Space", feishu_project_key="wi-space")


@pytest.fixture
def project(db, space) -> Project:
    return Project.objects.create(space=space, name="P", feishu_project_key="wi-key")


@pytest.fixture
def admin(db) -> object:
    return User.objects.create_superuser(username="wi_admin", password="x")


@pytest.fixture
def work_item(db) -> WorkItem:
    return WorkItem.objects.create(
        feishu_project_key="wpk",
        work_item_type="story",
        work_item_id=5001,
        title="登录页改造",
    )


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_attach_list_detach_flow(project, admin, work_item) -> None:
    client = _client(admin)
    # attach
    resp = client.post(
        f"/api/projects/{project.id}/work-items/",
        {"work_item_id": str(work_item.id)},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert ProjectWorkItemLink.objects.filter(
        project=project, work_item=work_item
    ).exists()

    # list 派生摘要
    resp = client.get(f"/api/projects/{project.id}/work-items/")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["feishu_work_item_id"] == 5001
    assert rows[0]["work_item_type"] == "story"
    assert rows[0]["title"] == "登录页改造"

    # 幂等 attach → 409
    resp = client.post(
        f"/api/projects/{project.id}/work-items/",
        {"work_item_id": str(work_item.id)},
        format="json",
    )
    assert resp.status_code == 409

    # detach
    resp = client.delete(
        f"/api/projects/{project.id}/work-items/{work_item.id}/"
    )
    assert resp.status_code == 204
    assert not ProjectWorkItemLink.objects.filter(
        project=project, work_item=work_item
    ).exists()


def test_attach_missing_work_item_404(project, admin) -> None:
    client = _client(admin)
    import uuid

    resp = client.post(
        f"/api/projects/{project.id}/work-items/",
        {"work_item_id": str(uuid.uuid4())},
        format="json",
    )
    assert resp.status_code == 404


def test_list_forbidden_for_outsider(project) -> None:
    outsider = User.objects.create_user(username="wi_outsider", password="x")
    resp = _client(outsider).get(f"/api/projects/{project.id}/work-items/")
    assert resp.status_code == 403

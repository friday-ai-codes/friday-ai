"""feature list 树 + 进度灯 + work-items 含 status + 项目基础搜索守护测试（84-01 Task 3）。

覆盖 WB-02 / WB-05 后端：
- feature-list GET：模块→功能点→验收项 三层树，功能点带四态进度灯；空工件返回空树不报错。
- work-items GET：返回项含 WorkItem 状态字段（status_state_key/status_display_name）。
- search GET：返回结果含 locator（属哪个 repo/project）；写 RetrievalTrace。

REST 经 APIClient（adrf 异步视图）。feature list bitable 拉取以 patch ``_fetch_records`` 注入
合成记录（无飞书外呼）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from delivery.models import WorkItem, WorkItemOrigin
from initiatives.models import (
    Artifact,
    ArtifactCarrier,
    ArtifactType,
    ProjectWorkItemLink,
)
from initiatives.services import ProjectDocService
from initiatives.services.feature_list_service import (
    LIGHT_DONE,
    LIGHT_PENDING,
    LIGHT_TESTING,
    FeatureListService,
)
from interactions.models import RetrievalTrace
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
    return Space.objects.create(name="FL Space", feishu_project_key="fl-space-key")


@pytest.fixture
def space_admin(db, space) -> object:
    u = User.objects.create_user(username="fl_admin", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.ADMIN)
    return u


@pytest.fixture
def outsider(db) -> object:
    return User.objects.create_user(username="fl_outsider", password="x")


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


def _feature_list_type() -> ArtifactType:
    # transaction=True 测试会 flush 掉 data migration 的 seed 数据，故 get_or_create 兜底。
    ftype, _ = ArtifactType.objects.get_or_create(
        key="feature_list",
        defaults={
            "name": "feature list",
            "carrier": ArtifactCarrier.FEISHU_BITABLE,
            "ragable": True,
            "builtin": True,
        },
    )
    return ftype


def _make_feature_list_artifact(project_id: str) -> Artifact:
    ftype = _feature_list_type()
    return Artifact.objects.create(
        project_id=project_id,
        type=ftype,
        carrier=ArtifactCarrier.FEISHU_BITABLE,
        title="feature list",
        url="https://example.feishu.cn/base/app?table=tbl1",
    )


def _attach_work_item(space, project_id, *, title, **status):
    wi = WorkItem.objects.create(
        feishu_project_key="fl-space-key",
        work_item_type="story",
        work_item_id=WorkItem.objects.count() + 1000,
        space=space,
        origin=WorkItemOrigin.MANUAL,
        title=title,
        **status,
    )
    ProjectWorkItemLink.objects.create(project_id=project_id, work_item=wi)
    return wi


# ============================ feature-list 树 ============================


def test_feature_list_empty_returns_empty_tree(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "fl1")
    resp = client.get(f"/api/projects/{pid}/feature-list/")
    assert resp.status_code == 200, resp.content
    assert resp.json() == {"modules": []}


def test_feature_list_builds_three_layer_tree(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "fl2")
    _make_feature_list_artifact(pid)
    # 匹配的 WorkItem（归档完成态 → 已完成）。
    _attach_work_item(
        space, pid, title="短信登录", status_state_key="archived", is_archived_state=True
    )

    records = [
        {"fields": {"模块": "登录", "功能点": "短信登录", "验收项": "收到验证码"}},
        {"fields": {"模块": "登录", "功能点": "短信登录", "验收项": "校验通过"}},
        {"fields": {"模块": "支付", "功能点": "微信支付", "验收项": "拉起收银台", "状态": "测试中"}},
        {"fields": {"模块": "支付", "功能点": "退款", "验收项": "原路退回"}},
    ]
    with patch.object(
        FeatureListService, "_fetch_records", new=AsyncMock(return_value=records)
    ):
        resp = client.get(f"/api/projects/{pid}/feature-list/")
    assert resp.status_code == 200, resp.content
    modules = {m["module"]: m for m in resp.json()["modules"]}
    assert set(modules) == {"登录", "支付"}

    login_features = {f["name"]: f for f in modules["登录"]["features"]}
    # 同一功能点两条验收项聚合。
    assert set(login_features["短信登录"]["acceptance"]) == {"收到验证码", "校验通过"}
    # WorkItem 归档完成态 → 已完成。
    assert login_features["短信登录"]["progress"] == LIGHT_DONE

    pay_features = {f["name"]: f for f in modules["支付"]["features"]}
    # 记录状态文本「测试中」→ 测试中（无匹配 WorkItem）。
    assert pay_features["微信支付"]["progress"] == LIGHT_TESTING
    # 无状态无匹配 → 待开发。
    assert pay_features["退款"]["progress"] == LIGHT_PENDING


# ============================ work-items 含 status ============================


def test_work_items_include_status_fields(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "wi1")
    _attach_work_item(
        space,
        pid,
        title="登录需求",
        status_state_key="in_progress",
        status_display_name="进行中",
        module_normalized="登录",
    )
    resp = client.get(f"/api/projects/{pid}/work-items/")
    assert resp.status_code == 200, resp.content
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["status_state_key"] == "in_progress"
    assert row["status_display_name"] == "进行中"
    assert row["module_normalized"] == "登录"


# ============================ 项目搜索 ============================


def test_search_returns_results_with_locator(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "se1")
    # 工件标题命中关键词。
    ftype = _feature_list_type()
    Artifact.objects.create(
        project_id=pid,
        type=ftype,
        carrier=ArtifactCarrier.MARKDOWN,
        title="登录模块设计",
        content_ref="登录流程说明",
    )
    resp = client.get(f"/api/projects/{pid}/search/", {"q": "登录"})
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["query"] == "登录"
    assert len(body["results"]) >= 1
    first = body["results"][0]
    assert first["locator"]["project_id"] == pid
    assert first["locator"]["project_name"] == "P"
    assert "kind" in first and "score" in first
    # 召回写 RetrievalTrace（脱敏经 ledger）。
    assert RetrievalTrace.objects.filter(source="project_search").exists()


def test_search_knowledge_fallback_includes_project_documents(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "se1-docs")

    with patch(
        "knowledge.retrieval.DeliveryKnowledgeSearchService.search_similar",
        new_callable=AsyncMock,
    ) as mocked:
        mocked.return_value = []

        resp = client.get(f"/api/projects/{pid}/search/", {"q": "错题本"})

    assert resp.status_code == 200, resp.content
    mocked.assert_awaited_once()
    args, kwargs = mocked.await_args
    assert args == ("错题本",)
    assert kwargs["project_ids"] == [pid]
    assert kwargs["include_document_kind"] is True


def test_search_empty_query_returns_empty(space, space_admin) -> None:
    client = _client(space_admin)
    pid = _create_project(client, space, "se2")
    resp = client.get(f"/api/projects/{pid}/search/", {"q": "   "})
    assert resp.status_code == 200
    assert resp.json() == {"query": "", "results": []}


def test_search_outsider_forbidden(space, space_admin, outsider) -> None:
    pid = _create_project(_client(space_admin), space, "se3")
    resp = _client(outsider).get(f"/api/projects/{pid}/search/", {"q": "x"})
    assert resp.status_code == 403

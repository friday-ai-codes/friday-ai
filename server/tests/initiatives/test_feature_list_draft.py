"""feature list 异步解析草稿守护测试。

覆盖重构后的核心链路（不依赖真实 durable worker / LLM）：
- 父任务体 ``run_feature_list_parse_start``：出模块外壳、置 phase=features、fan-out 子任务。
- 子任务体 ``run_feature_list_parse_module``：写功能点、进度累加、全完成置 ready。
- 429 退回队列：``run_feature_list_parse_module`` 遇 upstream_status=429 复位 pending 并 re-defer。
- 草稿 commit：落正式工件后删除草稿（每项目一份）。

task 体经 ``async_to_sync`` 在同步 django_db 测试内执行；``agenerate_module_*`` /
``DurableTaskService.defer`` 全 patch，杜绝外呼与真实入队。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import (
    Artifact,
    ArtifactCarrier,
    ArtifactType,
    FeatureListDraft,
    FeatureListDraftStatus,
)
from initiatives.services import ProjectDocService
from initiatives.services.feature_list_draft_service import FeatureListDraftService
from initiatives.services.feature_list_import import FeatureListParseError
from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space

pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()

_IMPORT = "initiatives.services.feature_list_import"
_DEFER = "durable.service.DurableTaskService.defer"


@pytest.fixture(autouse=True)
def _silence_provision():
    with patch.object(ProjectDocService, "provision_dispatch", return_value=None):
        yield


@pytest.fixture
def space(db) -> Space:
    return Space.objects.create(name="FLD Space", feishu_project_key="fld-space-key")


@pytest.fixture
def admin(db, space) -> object:
    u = User.objects.create_user(username="fld_admin", password="x")
    SpaceMembership.objects.create(user=u, space=space, role=SpaceRole.ADMIN)
    return u


def _feature_list_type() -> ArtifactType:
    ftype, _ = ArtifactType.objects.get_or_create(
        key="feature_list",
        defaults={
            "name": "feature list",
            "carrier": ArtifactCarrier.MARKDOWN,
            "ragable": True,
            "builtin": True,
        },
    )
    return ftype


def _create_project(client, space, key="fld-1") -> str:
    resp = client.post(
        "/api/projects/",
        {"space_id": str(space.id), "name": "P", "feishu_project_key": key},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["id"]


def test_async_parse_full_flow(space, admin):
    """出模块 → 逐模块解析 → 全完成 ready，进度权重 20/80。"""
    client = APIClient()
    client.force_authenticate(user=admin)
    project_id = _create_project(client, space)

    service = FeatureListDraftService()
    # 发起解析：写草稿（parsing），defer 被 patch 成不真正入队。
    with patch(_DEFER, new=AsyncMock(return_value="job-1")):
        snap = async_to_sync(service.astart_parse)(
            project_id, "# M1\nline\n# M2\nline", actor_id=admin.id
        )
    assert snap["status"] == FeatureListDraftStatus.PARSING
    draft = FeatureListDraft.objects.get(project_id=project_id)

    from durable.tasks_impl import (
        run_feature_list_parse_module,
        run_feature_list_parse_start,
    )

    outline = [
        {"module": "M1", "line_start": 1, "line_end": 2},
        {"module": "M2", "line_start": 3, "line_end": 4},
    ]
    with (
        patch(f"{_IMPORT}.agenerate_module_outline", new=AsyncMock(return_value=outline)),
        patch(_DEFER, new=AsyncMock(return_value="child")),
    ):
        async_to_sync(run_feature_list_parse_start)(
            project_id=str(project_id), draft_id=str(draft.id)
        )
    draft.refresh_from_db()
    assert draft.phase == "features"
    assert len(draft.tree["modules"]) == 2
    assert draft.progress == 20  # 出模块外壳 = W_MODULES

    # 逐模块解析：每个模块返回 1 个功能点。
    feats = [{"name": "F", "acceptance": ["A"], "source": "s"}]
    with patch(f"{_IMPORT}.agenerate_module_features", new=AsyncMock(return_value=feats)):
        async_to_sync(run_feature_list_parse_module)(
            project_id=str(project_id), draft_id=str(draft.id), module_index=0
        )
        draft.refresh_from_db()
        assert draft.status == FeatureListDraftStatus.PARTIAL
        assert draft.progress == 60  # 20 + 80 * 1/2

        async_to_sync(run_feature_list_parse_module)(
            project_id=str(project_id), draft_id=str(draft.id), module_index=1
        )
    draft.refresh_from_db()
    assert draft.status == FeatureListDraftStatus.READY
    assert draft.progress == 100
    assert draft.tree["modules"][0]["parse_state"] == "done"
    assert draft.tree["modules"][0]["features"][0]["name"] == "F"


def test_module_429_requeues(space, admin):
    """模块解析遇 429 → 复位 pending 并以 attempt+1 re-defer（退回队列）。"""
    client = APIClient()
    client.force_authenticate(user=admin)
    project_id = _create_project(client, space, key="fld-2")

    service = FeatureListDraftService()
    with patch(_DEFER, new=AsyncMock(return_value="job")):
        async_to_sync(service.astart_parse)(project_id, "doc", actor_id=admin.id)
    draft = FeatureListDraft.objects.get(project_id=project_id)
    # 手动铺一个模块外壳。
    async_to_sync(service.aset_outline)(
        str(draft.id), [{"module": "M1", "line_start": 1, "line_end": 1}]
    )

    from durable.tasks_impl import run_feature_list_parse_module

    err = FeatureListParseError("rate limited", upstream_status=429)
    defer_mock = AsyncMock(return_value="retry-job")
    with (
        patch(f"{_IMPORT}.agenerate_module_features", new=AsyncMock(side_effect=err)),
        patch(_DEFER, new=defer_mock),
    ):
        result = async_to_sync(run_feature_list_parse_module)(
            project_id=str(project_id), draft_id=str(draft.id), module_index=0, attempt=0
        )
    assert result["status"] == "requeued"
    assert result["attempt"] == 1
    draft.refresh_from_db()
    assert draft.tree["modules"][0]["parse_state"] == "pending"
    # re-defer 用同任务名、attempt+1。
    assert defer_mock.await_count == 1
    args, kwargs = defer_mock.await_args
    assert args[0] == "feature_list_parse_module"
    assert args[1]["attempt"] == 1


def test_commit_deletes_draft(space, admin):
    """草稿 commit → 落正式工件 + 删除草稿。"""
    _feature_list_type()
    client = APIClient()
    client.force_authenticate(user=admin)
    project_id = _create_project(client, space, key="fld-3")

    service = FeatureListDraftService()
    modules = [{"module": "M1", "features": [{"name": "F1", "acceptance": ["A1"]}]}]
    async_to_sync(service.asave_manual)(project_id, modules, actor_id=admin.id)
    assert FeatureListDraft.objects.filter(project_id=project_id).exists()

    async_to_sync(service.acommit)(project_id, actor=admin, actor_id=admin.id)
    assert not FeatureListDraft.objects.filter(project_id=project_id).exists()
    assert Artifact.objects.filter(
        project_id=project_id, type__key="feature_list"
    ).exists()

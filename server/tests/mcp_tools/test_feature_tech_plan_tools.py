"""feature list 技术方案 MCP 三工具端到端守护测试（两段式）。

覆盖这条链路最容易坏的地方：

- **两段式不可跳过**：``create`` 只出待确认题、绝不直接给方案（产品硬约束——路由再确定
  也要让用户确认关联仓库）。
- **强制确认真的发生**：即便路由候选全是 high 置信，仍然产出仓库确认题。
- **轮询能拿到方案**：非 chat 入口没有自动续驱，``get`` 必须自己把编排推到终态。
- **权限 fail-closed**：非成员拿不到他人会话。
- **三种取数源**：项目 feature list / 分支反查 / 纯文本。

编排内部（路由 / 召回 / 分类 / 调研 / 融合)全部 patch 成确定性替身——这里验证的是接入面
与状态机流转，不是 LLM 质量。
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from initiatives.models import Artifact, ArtifactType, Project, ProjectBranch
from initiatives.services import ProjectService
from projects.models import Space
from repositories.models import Repository

pytestmark = pytest.mark.django_db(transaction=True)

# ⭐ 同步点 2 收尾：本文件冲着**旧 technical_plan 链**写（旧 stage 图 / MergedPlan content /
# 旧终态映射）。四个入口开关默认值已翻到 technical_blueprint ⇒ 这里显式 override 回旧链，
# 把「我要测的是旧链」说出来，而不是继续靠「默认恰好是旧链」隐式到达。
# 旧链退役后，显式 override 正是它唯一合法的到达方式（见
# tests/services/process_runtime/test_technical_plan_retirement.py）。
pytestmark = [pytestmark, pytest.mark.usefixtures("legacy_plan_entry_switch")]


User = get_user_model()

_CREATE_URL = "/api/mcp/tools/create_feature_tech_plan/"
_CONFIRM_URL = "/api/mcp/tools/confirm_feature_tech_plan/"
_GET_URL = "/api/mcp/tools/get_feature_tech_plan/"

_FEATURE_LIST_JSON = """{
  "modules": [
    {
      "module": "入口与权益",
      "features": [
        {"name": "入口位置与排序", "acceptance": ["当进入页面时应展示入口"]},
        {"name": "课程包权益鉴权", "acceptance": ["无权限时不展示入口"]}
      ]
    }
  ]
}"""

_FEATURE_TEXT = """## 入口与权益

功能点 A：入口位置与排序
当 用户进入页面 时，系统应展示入口

功能点 B：课程包权益鉴权
当 用户无权限 时，系统应隐藏入口
"""


def _valid_merged_plan() -> dict[str, Any]:
    return {
        "title": "入口与权益改造",
        "summary": "后端补鉴权、前端接入入口",
        "api_contracts": [{"name": "GET /entry", "repo": "backend"}],
        "dependency_dag": {"frontend": ["backend"], "backend": []},
        "data_migrations": [],
        "compat_risks": ["老客户端需兼容入口缺失"],
        "release_order": ["backend", "frontend"],
        "rollback_plan": {"backend": "回滚鉴权", "frontend": "回滚入口"},
        "overall_plan": "先后端后前端",
        "cross_repo_context": "入口展示依赖后端权益接口",
        "execution_plan": [
            {
                "id": "t-backend",
                "name": "权益鉴权接口",
                "repository_id": "backend",
                "repository_name": "backend-repo",
                "branch_strategy": "feature",
                "coding_instruction": "实现 GET /entry 鉴权",
                "dependencies": [],
                "change_type": "modify",
                "touch_points": ["src/entry/service.py"],
                "pseudocode": "if not user.has_package: return None",
            }
        ],
    }


def _classification() -> dict[str, Any]:
    return {
        "items": [
            {
                "key": "入口与权益::入口位置与排序",
                "module": "入口与权益",
                "name": "入口位置与排序",
                "change_type": "new",
                "confidence": "medium",
                "target_repo_id": "",
                "reason": "现有代码无对应实现",
                "evidence_files": [],
                "suggested_location": "src/entry/",
            },
            {
                "key": "入口与权益::课程包权益鉴权",
                "module": "入口与权益",
                "name": "课程包权益鉴权",
                "change_type": "modify",
                "confidence": "high",
                "target_repo_id": "backend",
                "reason": "已有鉴权实现",
                "evidence_files": ["src/entry/service.py"],
                "suggested_location": "",
            },
        ],
        "summary": {"new": 1, "modify": 1, "unclear": 0},
        "evidence_hits": 2,
    }


def _high_confidence_routing(repo: Repository) -> dict[str, Any]:
    """全部 high 置信——用来验证「再确定也要问」。"""
    return {
        "candidates": [
            {"repo_id": str(repo.id), "confidence": "high", "repository_name": repo.name}
        ],
        "router_version": "v2",
        "auto_selected": True,
    }


@sync_to_async
def _make_user(username: str):
    return User.objects.create_user(username=username, password="x")


@sync_to_async
def _make_repo() -> Repository:
    return Repository.objects.create(
        name=f"repo-{uuid.uuid4().hex[:6]}",
        git_url=f"https://github.com/t/{uuid.uuid4().hex[:6]}.git",
        index_status="indexed",
    )


async def _make_project_with_features(owner) -> Project:
    space = await sync_to_async(Space.objects.create)(
        name="S", feishu_project_key=f"fs-{uuid.uuid4().hex[:6]}"
    )
    project, _ = await ProjectService().create(
        space=space, name="P", feishu_project_key=f"p-{uuid.uuid4().hex[:6]}", created_by=owner
    )
    atype, _ = await ArtifactType.objects.aget_or_create(
        key="feature_list",
        defaults={"name": "feature list", "carrier": "feishu_bitable", "builtin": True},
    )
    await Artifact.objects.acreate(
        project=project,
        type=atype,
        carrier="markdown",
        title="Feature List",
        content_ref=_FEATURE_LIST_JSON,
    )
    return project


def _patched_engine(repo: Repository, *, merged_plan: dict | None = None):
    """把编排内部依赖换成确定性替身（路由/召回/分类/调研/融合合成）。"""
    plan = merged_plan or _valid_merged_plan()
    return [
        patch(
            "services.process_runtime.repo_router_adapter.RepoRouterV2Adapter.route",
            new=AsyncMock(return_value=_high_confidence_routing(repo)),
        ),
        patch(
            "services.process_runtime.recall_adapter.DeliveryKnowledgeRecallAdapter.recall",
            new=AsyncMock(return_value={"hits": [], "query": "", "kinds": []}),
        ),
        patch(
            "services.process_runtime.classify_adapter.FeatureChangeClassifyAdapter.classify",
            new=AsyncMock(return_value=_classification()),
        ),
        patch(
            "services.process_runtime.research_adapter.ResearchDispatchAdapter.dispatch",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "services.process_runtime.architect_merge_adapter.LLMMergedPlanSynthesizer.synthesize",
            new=AsyncMock(return_value=plan),
        ),
    ]


class _Patches:
    """批量上下文管理（避免 5 层 with 缩进）。"""

    def __init__(self, patches: list) -> None:
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc) -> None:
        for p in reversed(self._patches):
            p.stop()


@pytest.mark.asyncio
async def test_create_returns_questions_not_plan(mcp_client, access_user) -> None:
    """两段式第一段：只出待确认题，绝不直接给方案。"""
    client, _ = mcp_client
    repo = await _make_repo()
    project = await _make_project_with_features(access_user)

    with _Patches(_patched_engine(repo)):
        resp = await sync_to_async(client.post)(
            _CREATE_URL, {"project_id": str(project.id)}, format="json"
        )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["session_id"]
    assert body["feature_count"] == 2
    assert body["source"] == "project"
    # 关键：第一段不给方案。
    assert body["plan"] == {}
    assert body["markdown"] == ""
    # 强制确认：全 high 置信仍然问仓库。
    assert body["questions"], "必须产出待确认题"
    assert any("仓库" in q["question"] for q in body["questions"])
    assert body["classification"]["summary"] == {"new": 1, "modify": 1, "unclear": 0}


@pytest.mark.asyncio
async def test_confirm_then_get_returns_full_plan(mcp_client, access_user) -> None:
    """确认后编排继续，get 轮询把会话推到终态并返回完整方案 markdown。"""
    client, _ = mcp_client
    repo = await _make_repo()
    project = await _make_project_with_features(access_user)

    with _Patches(_patched_engine(repo)):
        created = await sync_to_async(client.post)(
            _CREATE_URL, {"project_id": str(project.id)}, format="json"
        )
        session_id = created.json()["session_id"]
        questions = created.json()["questions"]

        answers = [
            {"question_id": q["question_id"], "selected": q["recommended"]} for q in questions
        ]
        confirmed = await sync_to_async(client.post)(
            _CONFIRM_URL, {"session_id": session_id, "answers": answers}, format="json"
        )
        assert confirmed.status_code == 200, confirmed.json()

        got = await sync_to_async(client.post)(_GET_URL, {"session_id": session_id}, format="json")

    assert got.status_code == 200, got.json()
    body = got.json()
    assert body["status"] == "completed", body
    assert body["artifact_version_id"]
    assert body["plan"]["title"] == "入口与权益改造"
    # 完整方案包含整体 + 分仓 + 落点 + 伪代码。
    markdown = body["markdown"]
    assert "## 整体方案" in markdown
    assert "## 分仓方案" in markdown
    assert "src/entry/service.py" in markdown
    assert "if not user.has_package" in markdown
    assert "## 功能点分类" in markdown


@pytest.mark.asyncio
async def test_confirm_with_empty_answers_uses_recommended(mcp_client, access_user) -> None:
    """空 answers = 全部按推荐执行——漏答不能让会话永久挂起。"""
    client, _ = mcp_client
    repo = await _make_repo()
    project = await _make_project_with_features(access_user)

    with _Patches(_patched_engine(repo)):
        created = await sync_to_async(client.post)(
            _CREATE_URL, {"project_id": str(project.id)}, format="json"
        )
        session_id = created.json()["session_id"]
        confirmed = await sync_to_async(client.post)(
            _CONFIRM_URL, {"session_id": session_id, "answers": []}, format="json"
        )

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] in ("researching", "completed")


@pytest.mark.asyncio
async def test_start_from_branch_binding(mcp_client, access_user) -> None:
    """分支入口：复用手动绑定的 ProjectBranch 反查项目取 feature list。"""
    client, _ = mcp_client
    repo = await _make_repo()
    project = await _make_project_with_features(access_user)
    await ProjectBranch.objects.acreate(
        project=project, repository=repo, branch_name="feat/entry", source="manual"
    )

    with _Patches(_patched_engine(repo)):
        resp = await sync_to_async(client.post)(
            _CREATE_URL, {"branch_name": "feat/entry"}, format="json"
        )

    assert resp.status_code == 200, resp.json()
    assert resp.json()["source"] == "branch"
    assert resp.json()["feature_count"] == 2


@pytest.mark.asyncio
async def test_start_from_raw_text_without_project(mcp_client) -> None:
    """纯文本入口：没有项目上下文也能用（IDE / CLI 主场景），走启发式结构解析。"""
    client, _ = mcp_client
    repo = await _make_repo()

    with _Patches(_patched_engine(repo)):
        resp = await sync_to_async(client.post)(
            _CREATE_URL, {"feature_list_text": _FEATURE_TEXT}, format="json"
        )

    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["source"] == "text"
    assert body["feature_count"] == 2
    assert body["status"] == "awaiting_confirmation"


@pytest.mark.asyncio
async def test_missing_source_rejected(mcp_client) -> None:
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(_CREATE_URL, {}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "invalid_params"


@pytest.mark.asyncio
async def test_branch_without_binding_reports_actionable_error(mcp_client) -> None:
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _CREATE_URL, {"branch_name": "feat/never-bound"}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "branch_not_bound"
    assert "关联分支" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_unknown_session_404(mcp_client) -> None:
    client, _ = mcp_client
    resp = await sync_to_async(client.post)(
        _GET_URL, {"session_id": str(uuid.uuid4())}, format="json"
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "session_not_found"


@pytest.mark.asyncio
async def test_outsider_cannot_read_others_session(mcp_client, access_user) -> None:
    """权限 fail-closed：非创建者、非项目可读者拿不到他人方案会话。"""
    client, _ = mcp_client
    repo = await _make_repo()
    project = await _make_project_with_features(access_user)

    with _Patches(_patched_engine(repo)):
        created = await sync_to_async(client.post)(
            _CREATE_URL, {"project_id": str(project.id)}, format="json"
        )
    session_id = created.json()["session_id"]

    outsider = await _make_user(f"outsider-{uuid.uuid4().hex[:6]}")
    other_client = APIClient()
    await sync_to_async(other_client.force_authenticate)(user=outsider, token="x")
    resp = await sync_to_async(other_client.post)(
        _GET_URL, {"session_id": session_id}, format="json"
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "forbidden"


@pytest.mark.asyncio
async def test_project_without_feature_list_reports_empty(mcp_client, access_user) -> None:
    """项目没录 feature list → 明确报错，不静默产出空方案。"""
    client, _ = mcp_client
    space = await sync_to_async(Space.objects.create)(
        name="S2", feishu_project_key=f"empty-{uuid.uuid4().hex[:6]}"
    )
    project, _ = await ProjectService().create(
        space=space,
        name="Empty",
        feishu_project_key=f"e-{uuid.uuid4().hex[:6]}",
        created_by=access_user,
    )

    resp = await sync_to_async(client.post)(
        _CREATE_URL, {"project_id": str(project.id)}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "empty_feature_list"

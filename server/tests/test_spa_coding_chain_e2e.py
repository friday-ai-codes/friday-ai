"""SPA 编码链路四步「共用同一个 CodingPlan.id」端到端护栏 —— Phase 109 / SPINE-01 前置。

本文件存在的唯一理由是锁住一条**不变量**：

    ①选目标仓 ②配置分支 ③确认编码（fan-out） ④飞书导出
    —— 四步全部只以 chat ``CodingPlan.id`` 为锚点，一次投影/一份方案即点亮全部四步。

四步各自都已有独立测试（``test_coding_plans_sessions_api.py`` /
``test_coding_plan_export_api.py`` / ``test_coding_plan_detail_api``…），但在本文件
落地之前，**没有任何一条用例把「四步都还挂在同一个 plan_id 上」这件事锁住**。
SPINE-01 的投影方案与 SPINE-02 的 schema 收窄都建立在这条不变量之上，因此本护栏
必须先于本 phase 任何 schema / 模型改动落地（wave 1）。

Mock 边界（刻意收得极窄）：只 mock 飞书 HTTP 客户端这一层 IO（``--disable-socket``
下不允许真实网络），``create_sessions_for_plan`` 与导出 service 本体全部真跑 ——
把它们 mock 掉护栏就空了。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from chat.models import (
    CodingPlan,
    CodingPlanProvenance,
    CodingSession,
    Conversation,
)
from projects.models import Space
from repositories.models import IndexStatus, Repository

User = get_user_model()

# 分支模板带 ${repo} 占位符 → per-repo 渲染，便于断言「模板确实被应用」。
_BRANCH_TEMPLATE = "feat/20260730.spine-${repo}"
_TARGET_BRANCH = "main"

_MOCK_DOC = {
    "document_id": "doxcnSPINE109",
    "url": "https://feishu.cn/docx/doxcnSPINE109",
}


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def spine_user(db):
    """链路 owner（conversation.created_by，四步 owner gate 的通行身份）。"""
    return User.objects.create_user(
        username=f"spine_owner_{uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:6]}@spine.local",
        password="testpass123",
    )


@pytest.fixture
def spine_outsider(db):
    """非 owner 用户（owner gate 对照组）。"""
    return User.objects.create_user(
        username=f"spine_outsider_{uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:6]}@spine.local",
        password="testpass123",
    )


@pytest.fixture
def spine_space(db) -> Space:
    """带飞书导出配置的 Space（folder_token 让第 ④ 步不在参数校验处提前 400）。"""
    suffix = uuid.uuid4().hex[:8]
    return Space.objects.create(
        name=f"双脊柱合流测试空间-{suffix}",
        feishu_project_key=f"spine-{suffix}",
        feishu_doc_folder_token="fk_spine",
        feishu_app_id="cli_spine_test",
        feishu_app_secret_encrypted="enc_spine_test",
    )


@pytest.fixture
def spine_repos(db, spine_space: Space) -> list[Repository]:
    """两个 indexed 仓库并挂到 space（第 ①③ 步的多仓 fan-out 素材）。"""
    repos: list[Repository] = []
    for name in ("spine-repo-a", "spine-repo-b"):
        repo = Repository.objects.create(
            name=name,
            git_url=f"https://gitlab.com/spine/{name}.git",
            git_platform="gitlab",
            default_branch="main",
            index_status=IndexStatus.INDEXED,
        )
        spine_space.repositories.add(repo)
        repos.append(repo)
    return repos


@pytest.fixture
def spine_plan(db, spine_space: Space, spine_user, spine_repos) -> CodingPlan:
    """Conversation + CodingPlan。

    本 phase 阶段仍走 ``aget_or_create_for_conversation``（投影 service 尚未存在），
    SPINE-01 落地后该构造点会换成投影 service，但本护栏断言的不变量不变。

    ``provenance`` 显式置为 ``orchestrated``：四步连通性护栏测的是**编排方案的正常
    路径**（草稿路径由本文件的 ``test_draft_plan_fanout_blocked_without_acknowledge``
    覆盖）。``aget_or_create_for_conversation`` 走 DB default ``draft``，落 109-07 的
    草稿 gate 后第 ③ 步会变 400 —— 若在此一律置 orchestrated 而不补草稿用例，这条
    「ROADMAP 顺序硬约束的唯一物化护栏」就不再覆盖存量方案的真实形态（迁移 default
    是 ``draft``，存量全是草稿）。两条用例缺一即视为护栏失守。
    """
    conversation = Conversation.objects.create(
        space=spine_space,
        title="双脊柱合流端到端护栏对话",
        created_by=spine_user,
    )
    plan, _created = async_to_sync(CodingPlan.aget_or_create_for_conversation)(
        conversation=conversation,
        tech_plan="## 技术方案\n\n- 步骤 1：改 A 仓\n- 步骤 2：改 B 仓",
        affected_files=[{"file_path": "src/main.py", "change_type": "modify"}],
        title="双脊柱合流方案",
    )
    plan.recommended_repository_ids = [str(r.id) for r in spine_repos]
    plan.provenance = CodingPlanProvenance.ORCHESTRATED
    plan.save(update_fields=["recommended_repository_ids", "provenance", "updated_at"])
    return plan


@pytest.fixture
def spine_client(db, spine_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=spine_user)
    return client


@pytest.fixture
def spine_outsider_client(db, spine_outsider) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=spine_outsider)
    return client


@pytest.fixture
def spine_artifact_version(db, spine_space: Space, spine_user, spine_repos):
    """编排产出的方案版本（chat 入口）—— 投影端点的来源。

    造的是完整来源链 WorkItem → Artifact → ArtifactVersion + 带 ``conversation_id``
    的 ``ConvergenceSession``，与投影 service 解析 conversation 的路径一致。
    """
    from delivery.models import (
        Artifact,
        ArtifactVersion,
        ConvergenceSession,
        ConvergenceSessionEntrypoint,
        ConvergenceSessionStatus,
        WorkItem,
        WorkItemOrigin,
    )

    conversation = Conversation.objects.create(
        space=spine_space,
        title="编排产出直连执行流对话",
        created_by=spine_user,
    )
    session = ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="merge",
        status=ConvergenceSessionStatus.DONE,
        conversation_id=conversation.id,
    )
    work_item = WorkItem.objects.create(
        feishu_project_key=f"pk-{uuid.uuid4().hex[:8]}",
        work_item_type="story",
        work_item_id=int(uuid.uuid4().int % 10_000_000),
        origin=WorkItemOrigin.MANUAL,
        title="双脊柱合流：编排产出直连执行流",
    )
    artifact = Artifact.objects.create(
        artifact_type="technical_plan",
        work_item=work_item,
        title="双脊柱合流方案（编排产出）",
    )
    return ArtifactVersion.objects.create(
        artifact=artifact,
        version_no=1,
        content={
            "title": "双脊柱合流方案（编排产出）",
            "summary": "把 A 仓接口改造后同步 B 仓调用方。",
            "execution_plan": [
                {
                    "id": f"t{i}",
                    "name": f"改造 {repo.name}",
                    "repository_id": str(repo.id),
                    "repository_name": repo.name,
                    "coding_instruction": f"在 {repo.name} 内实现改造",
                    "files": [{"path": f"{repo.name}/main.py", "action": "create"}],
                }
                for i, repo in enumerate(spine_repos, 1)
            ],
        },
        produced_by_session_id=str(session.id),
    )


def _detail_url(plan_id: object) -> str:
    return reverse("coding-plan-detail", kwargs={"plan_id": str(plan_id)})


def _project_url() -> str:
    return reverse("coding-plan-project-from-artifact-version")


def _sessions_url(plan_id: object) -> str:
    return reverse("coding-plan-sessions-batch", kwargs={"plan_id": str(plan_id)})


def _export_url(plan_id: object) -> str:
    return reverse(
        "coding-plan-export-to-feishu", kwargs={"coding_plan_id": str(plan_id)}
    )


def _patch_feishu_doc_client():
    """只 mock 飞书 HTTP 客户端这一层 IO 边界，导出 service 本体真跑。

    ``export_coding_plan_to_feishu`` 在 ``doc_client is None`` 时经
    ``create_feishu_doc_client_for_project`` 构造真实 client（会触网）；这里把工厂换成
    返回一个 ``create_document`` 为 AsyncMock 的假 client，markdown 组装、
    ``feishu_doc_url`` 回填等逻辑全部保持真实执行路径。
    """
    fake_client = MagicMock()
    fake_client.create_document = AsyncMock(return_value=_MOCK_DOC)
    return patch(
        "agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project",
        new=AsyncMock(return_value=fake_client),
    )


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.django_db(transaction=True)
def test_spa_coding_chain_four_steps_share_one_plan_id(
    spine_client: APIClient,
    spine_plan: CodingPlan,
    spine_repos: list[Repository],
) -> None:
    """①②③④ 四步串跑，且四步使用的 plan 标识必须是同一个。"""
    plan_id = spine_plan.id
    # 四步实际打出去的 plan 标识收集器 —— 末尾的不变量断言基于它。
    plan_ids_used: set[str] = set()

    # ①② 选目标仓 / 配置分支：前端 RepoMultiSelector 以 plan 详情为锚点拉取方案，
    #     分支配置是纯前端态，后端侧以 branch_template / target_branch 入参在第 ③ 步一起提交。
    detail_resp = spine_client.get(_detail_url(plan_id))
    assert detail_resp.status_code == status.HTTP_200_OK
    detail_body = detail_resp.json()
    assert detail_body["id"] == str(plan_id)
    plan_ids_used.add(detail_body["id"])
    # 推荐仓库高亮的数据源在模型层（REST 详情序列化器不透出该字段），此处直接断言
    # 数据未被链路上游改写。
    spine_plan.refresh_from_db()
    assert spine_plan.recommended_repository_ids == [str(r.id) for r in spine_repos]

    # ③ 确认编码：同一个 plan_id 上 fan-out 出 N 条 CodingSession。
    sessions_resp = spine_client.post(
        _sessions_url(plan_id),
        data={
            "repository_ids": [str(r.id) for r in spine_repos],
            "branch_template": _BRANCH_TEMPLATE,
            "target_branch": _TARGET_BRANCH,
        },
        format="json",
    )
    assert sessions_resp.status_code == status.HTTP_200_OK
    sessions_body = sessions_resp.json()
    assert len(sessions_body["created"]) == 2
    assert sessions_body["failed"] == []
    plan_ids_used.add(str(plan_id))

    for item in sessions_body["created"]:
        session = CodingSession.objects.get(id=item["session_id"])
        assert session.coding_plan_id == plan_id
        assert session.status == CodingSession.Status.DRAFT
        assert session.target_branch == _TARGET_BRANCH
        # 模板已按 ${repo} 渲染（而不是回退到 LLM 生成的共享分支名）
        assert session.branch_name == f"feat/20260730.spine-{session.repository.name}"
        assert item["branch_name"] == session.branch_name

    # ④ 飞书导出：同一个 plan_id 打导出端点，回填 feishu_doc_url。
    with _patch_feishu_doc_client():
        export_resp = spine_client.post(
            _export_url(plan_id),
            data={"folder_token": "fk_spine"},
            format="json",
        )
    assert export_resp.status_code == status.HTTP_200_OK
    plan_ids_used.add(str(plan_id))
    spine_plan.refresh_from_db()
    assert spine_plan.feishu_doc_url
    assert spine_plan.feishu_doc_url == _MOCK_DOC["url"]

    # —— 不变量断言（本用例存在的唯一理由）——
    # 锁的是「一次投影/一份方案即点亮全部四步」：四步共用同一个锚点，
    # 任何把某一步改成依赖别的锚点（另一个 plan、session id、artifact version…）
    # 的改动都会在此变红。
    assert plan_ids_used == {str(plan_id)}
    assert len(plan_ids_used) == 1
    # 反查一致性：从 plan 侧反查到的 session 数量必须等于第 ③ 步 created 数量。
    assert (
        CodingSession.objects.filter(coding_plan_id=plan_id).count()
        == len(sessions_body["created"])
    )


@pytest.mark.django_db(transaction=True)
def test_projected_plan_completes_fanout_and_export(
    spine_client: APIClient,
    spine_artifact_version,
    spine_repos: list[Repository],
) -> None:
    """SPINE-01 收口：plan 来源换成**投影端点**，四步依旧全通。

    与上一条护栏的唯一差别是 plan 的来源 —— 那条手工造 ``CodingPlan``，这条打投影端点。
    两条都绿即证明「投影出一条记录即四步全通」，编排产出无需改执行流即可直连。
    """
    project_resp = spine_client.post(
        _project_url(),
        data={"artifact_version_id": str(spine_artifact_version.id)},
        format="json",
    )
    assert project_resp.status_code == status.HTTP_200_OK
    projected = project_resp.json()
    assert projected["created"] is True
    assert projected["provenance"] == "orchestrated"
    plan_id = projected["coding_plan_id"]
    # 投影响应直接带正文：前端无需二次拉 runtime 即可渲染。
    assert projected["tech_plan"]
    assert projected["recommended_repository_ids"] == [str(r.id) for r in spine_repos]

    # ①② 选目标仓 / 配置分支：详情端点以投影出的 plan_id 为锚点。
    detail_resp = spine_client.get(_detail_url(plan_id))
    assert detail_resp.status_code == status.HTTP_200_OK
    assert detail_resp.json()["id"] == plan_id

    # ③ 确认编码：同一个 plan_id fan-out。
    sessions_resp = spine_client.post(
        _sessions_url(plan_id),
        data={
            "repository_ids": [str(r.id) for r in spine_repos],
            "branch_template": _BRANCH_TEMPLATE,
            "target_branch": _TARGET_BRANCH,
        },
        format="json",
    )
    assert sessions_resp.status_code == status.HTTP_200_OK
    sessions_body = sessions_resp.json()
    assert len(sessions_body["created"]) == len(spine_repos)
    assert sessions_body["failed"] == []
    for item in sessions_body["created"]:
        session = CodingSession.objects.get(id=item["session_id"])
        # 投影出的 plan id 就是执行流的锚点 —— SPINE-01 的核心断言。
        assert str(session.coding_plan_id) == plan_id

    # ④ 飞书导出：同一个 plan_id。
    with _patch_feishu_doc_client():
        export_resp = spine_client.post(
            _export_url(plan_id),
            data={"folder_token": "fk_spine"},
            format="json",
        )
    assert export_resp.status_code == status.HTTP_200_OK

    plan = CodingPlan.objects.get(id=plan_id)
    assert plan.feishu_doc_url == _MOCK_DOC["url"]
    assert str(plan.source_artifact_version_id) == str(spine_artifact_version.id)


@pytest.mark.django_db(transaction=True)
def test_draft_plan_fanout_blocked_without_acknowledge(
    spine_client: APIClient,
    spine_plan: CodingPlan,
    spine_repos: list[Repository],
) -> None:
    """草稿形态（存量方案的真实形态）打第 ③ 步 → 被服务端 gate 拦（RELY-01）。

    存在理由：迁移 ``default="draft"`` ⇒ 线上存量 ``CodingPlan`` 全是草稿。若本文件
    只留「置为 orchestrated 的四步连通性」一条，护栏就不再覆盖存量真实形态，草稿
    送编码的 fail-closed 性质可以被静默删掉而这里全绿。
    """
    plan_id = spine_plan.id
    # 显式回落到存量形态（fixture 为四步连通性置了 orchestrated）。
    CodingPlan.objects.filter(id=plan_id).update(provenance=CodingPlanProvenance.DRAFT)

    sessions_resp = spine_client.post(
        _sessions_url(plan_id),
        data={
            "repository_ids": [str(r.id) for r in spine_repos],
            "branch_template": _BRANCH_TEMPLATE,
            "target_branch": _TARGET_BRANCH,
        },
        format="json",
    )
    assert sessions_resp.status_code == status.HTTP_400_BAD_REQUEST
    # 前端按稳定机器码分支，绝不匹配 detail 文案。
    assert sessions_resp.json()["code"] == "draft_requires_explicit_confirm"
    # fail-closed 的实质：整批拒绝，DB 零写入。
    assert CodingSession.objects.filter(coding_plan_id=plan_id).count() == 0

    # 显式确认后同一条链路放行 —— 草稿是「有防护的应急路径」，不是被禁用的路径。
    acked_resp = spine_client.post(
        _sessions_url(plan_id),
        data={
            "repository_ids": [str(r.id) for r in spine_repos],
            "branch_template": _BRANCH_TEMPLATE,
            "target_branch": _TARGET_BRANCH,
            "acknowledge_unresearched": True,
        },
        format="json",
    )
    assert acked_resp.status_code == status.HTTP_200_OK
    assert len(acked_resp.json()["created"]) == len(spine_repos)


@pytest.mark.django_db(transaction=True)
def test_spa_coding_chain_non_owner_gets_404_on_execute_and_export(
    spine_outsider_client: APIClient,
    spine_plan: CodingPlan,
    spine_repos: list[Repository],
) -> None:
    """非 owner 打第 ③④ 步 → 均 404（不是 403，不泄漏 plan 存在性）。

    护栏若只覆盖 happy path，owner gate 被改松也不会有人发现；这条对照用例把
    「越权与不存在同体」的口径一并锁住（chat/views.py owner gate）。
    """
    plan_id = spine_plan.id

    sessions_resp = spine_outsider_client.post(
        _sessions_url(plan_id),
        data={
            "repository_ids": [str(spine_repos[0].id)],
            "branch_template": _BRANCH_TEMPLATE,
        },
        format="json",
    )
    assert sessions_resp.status_code == status.HTTP_404_NOT_FOUND

    with _patch_feishu_doc_client() as mocked_factory:
        export_resp = spine_outsider_client.post(
            _export_url(plan_id),
            data={"folder_token": "fk_spine"},
            format="json",
        )
    assert export_resp.status_code == status.HTTP_404_NOT_FOUND
    # owner gate 先于任何导出动作触发：飞书 client 根本没被构造。
    mocked_factory.assert_not_awaited()

    # 越权请求不得留下任何副作用。
    assert CodingSession.objects.filter(coding_plan_id=plan_id).count() == 0

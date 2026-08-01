"""惰性投影端点 ``POST /api/chat/coding-plans/from-artifact-version/``（Phase 109 · SPINE-01）。

覆盖 109-03 Task 3 的四条口径：

- **响应直接带正文**：七字段齐全，前端点「进入编码」后无需二次拉 runtime（UI-SPEC 契约 2）。
- **幂等**：同一方案版本连打两次只产一行，第二次 ``created is False``。
- **owner gate 与统一 404**：非 owner 与不存在**同体同文**，阻断 artifact_version_id
  枚举探测（T-109-03-01 / T-109-03-02），且越权不留下垃圾对象。
- **稳定机器码**：错误响应带 ``code``，前端按 ``code`` 分支而非 ``detail`` 文案。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from chat.models import CodingPlan, CodingPlanProvenance, Conversation
from chat.plan_projection_service import PlanProjectionService
from delivery.models import (
    Artifact,
    ArtifactVersion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    WorkItem,
    WorkItemOrigin,
)
from projects.models import Space

User = get_user_model()

pytestmark = pytest.mark.django_db(transaction=True)

_URL_NAME = "coding-plan-project-from-artifact-version"

_CONTENT: dict[str, Any] = {
    "title": "跨仓改造方案",
    "summary": "把 A 仓的接口改造后同步 B 仓调用方。",
    "execution_plan": [
        {
            "id": "t1",
            "name": "改造 A 仓接口",
            "repository_id": "11111111-1111-1111-1111-111111111111",
            "repository_name": "repo-a",
            "coding_instruction": "新增 v2 接口",
            "files": [
                {"path": "a/api_v2.py", "action": "create"},
                {"path": "a/router.py", "action": "modify"},
            ],
        },
        {
            "id": "t2",
            "name": "同步 B 仓调用方",
            "repository_id": "22222222-2222-2222-2222-222222222222",
            "repository_name": "repo-b",
            "coding_instruction": "切到 v2 接口",
            "files": [{"path": "b/client.ts", "action": "modify"}],
        },
    ],
}


# ============================================================================
# Fixtures
# ============================================================================


def _make_user(prefix: str) -> Any:
    return User.objects.create_user(
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@projection.local",
        password="testpass123",
    )


@pytest.fixture
def owner(db) -> Any:
    """编排会话对应 conversation 的创建者（owner gate 的通行身份）。"""
    return _make_user("projection_owner")


@pytest.fixture
def outsider(db) -> Any:
    return _make_user("projection_outsider")


@pytest.fixture
def conversation(db, owner) -> Conversation:
    suffix = uuid.uuid4().hex[:8]
    space = Space.objects.create(
        name=f"投影端点测试空间-{suffix}",
        feishu_project_key=f"projection-api-{suffix}",
    )
    return Conversation.objects.create(
        space=space,
        title="编排会话对应的 chat 对话",
        created_by=owner,
    )


def _make_session(conversation: Conversation | None) -> ConvergenceSession:
    return ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=(
            ConvergenceSessionEntrypoint.CHAT
            if conversation is not None
            else ConvergenceSessionEntrypoint.WORKFLOW
        ),
        current_stage="merge",
        status=ConvergenceSessionStatus.DONE,
        conversation_id=conversation.id if conversation is not None else None,
    )


def _make_artifact_version(session: ConvergenceSession) -> ArtifactVersion:
    work_item = WorkItem.objects.create(
        feishu_project_key=f"pk-{uuid.uuid4().hex[:8]}",
        work_item_type="story",
        work_item_id=int(uuid.uuid4().int % 10_000_000),
        origin=WorkItemOrigin.MANUAL,
        title="把 A 仓接口改造后同步 B 仓调用方",
    )
    artifact = Artifact.objects.create(
        artifact_type="technical_plan",
        work_item=work_item,
        title="跨仓改造方案",
    )
    return ArtifactVersion.objects.create(
        artifact=artifact,
        version_no=1,
        content=_CONTENT,
        produced_by_session_id=str(session.id),
    )


@pytest.fixture
def artifact_version(db, conversation: Conversation) -> ArtifactVersion:
    return _make_artifact_version(_make_session(conversation))


@pytest.fixture
def space_repositories(db, conversation: Conversation) -> list[Any]:
    """把 ``_CONTENT`` 里那两个 repository_id 造成 space 下的真实仓库。

    109-REVIEW HI-01：投影响应要回仓库**名字**，没有真实行就只能回空列表——那正是
    界面上「未找到匹配的仓库」的成因。
    """
    from repositories.models import Repository

    repos = []
    for repo_id, name in (
        ("11111111-1111-1111-1111-111111111111", "repo-a"),
        ("22222222-2222-2222-2222-222222222222", "repo-b"),
    ):
        repo = Repository.objects.create(
            id=repo_id,
            name=name,
            git_url=f"https://gitlab.com/test/{name}.git",
            git_platform="gitlab",
            default_branch="main",
        )
        conversation.space.repositories.add(repo)
        repos.append(repo)
    return repos


@pytest.fixture
def owner_client(db, owner) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=owner)
    return client


@pytest.fixture
def outsider_client(db, outsider) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=outsider)
    return client


def _post(client: APIClient, artifact_version_id: Any):
    return client.post(
        reverse(_URL_NAME),
        data={"artifact_version_id": str(artifact_version_id)},
        format="json",
    )


# ============================================================================
# 200 —— 响应直接带正文
# ============================================================================


def test_projection_returns_full_payload(
    owner_client: APIClient,
    artifact_version: ArtifactVersion,
    space_repositories: list[Any],
) -> None:
    """字段齐全且正文非空 —— 前端可就地内嵌卡片，不必二次拉 runtime。"""
    resp = _post(owner_client, artifact_version.id)

    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert set(body) == {
        "coding_plan_id",
        "created",
        "title",
        "tech_plan",
        "affected_files",
        "recommended_repository_ids",
        "recommended_repositories",
        "provenance",
        # 同步点 2 收尾：blueprint/v1 判别三键（v0 恒空串）。
        "schema_version",
        "blueprint_artifact_id",
        "current_status",
    }
    assert body["created"] is True
    assert body["title"] == "跨仓改造方案"
    assert body["tech_plan"]
    assert "跨仓改造方案" in body["tech_plan"]
    assert body["provenance"] == CodingPlanProvenance.ORCHESTRATED
    # ⭐ v0 来源版本：三键全空串 ⇒ 前端走既有 v0 渲染路径，逐字不变。
    assert body["schema_version"] == ""
    assert body["blueprint_artifact_id"] == ""
    assert body["current_status"] == ""

    # create → add 的枚举转换必须在响应里就已完成（前端不做兼容映射，UI-SPEC 第 19 条）。
    assert body["affected_files"] == [
        {"file_path": "a/api_v2.py", "change_type": "add"},
        {"file_path": "a/router.py", "change_type": "modify"},
        {"file_path": "b/client.ts", "change_type": "modify"},
    ]
    for entry in body["affected_files"]:
        assert set(entry) == {"file_path", "change_type"}
    assert body["recommended_repository_ids"] == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    # 🔴 109-REVIEW HI-01：只回 id 渲染不出任何一行可勾选的仓库 —— 交棒后的选仓面
    # 会变成「未找到匹配的仓库」，SC-1 的第一步在界面上不成立。
    assert sorted(r["name"] for r in body["recommended_repositories"]) == [
        "repo-a",
        "repo-b",
    ]
    for entry in body["recommended_repositories"]:
        assert set(entry) == {"id", "name"}

    plan = CodingPlan.objects.get(id=body["coding_plan_id"])
    assert str(plan.source_artifact_version_id) == str(artifact_version.id)
    assert plan.provenance == CodingPlanProvenance.ORCHESTRATED


def test_projection_marks_a_blueprint_source_version(
    owner_client: APIClient, artifact_version: ArtifactVersion
) -> None:
    """⭐ 同步点 2 收尾：来源版本是 blueprint/v1 ⇒ 判别三键如实回填。

    这三键是前端 ``TechPlanCard`` 唯一的判别依据。没有它们，从蓝图版本投影出来的
    CodingPlan 会被渲染成一份**结构合法而内容为空**的旧形态方案（``tech_plan`` 是 v0
    渲染器对 blueprint/v1 渲出的壳、``affected_files`` 恒 ``[]``，因为 blueprint/v1
    没有 ``execution_plan`` 顶层键），且不给任何信号 —— 与审计 §4.1 的 G3 同一形状。

    ⚠️ 与上一条 v0 用例**正反并列**：只断言蓝图这一档会漏掉「两档都回填」的假通过。
    """
    ArtifactVersion.objects.filter(id=artifact_version.id).update(
        content={"schema_version": "blueprint/v1", "meta": {"title": "跨仓改造蓝图"}}
    )
    Artifact.objects.filter(id=artifact_version.artifact_id).update(
        blueprint_status="pending_review"
    )

    resp = _post(owner_client, artifact_version.id)

    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["schema_version"] == "blueprint/v1"
    assert body["blueprint_artifact_id"] == str(artifact_version.artifact_id)
    assert body["current_status"] == "pending_review"
    # v0 映射器对蓝图的产出确实是空的——正因如此前端必须拿到判别信息才不会静默降级。
    assert body["affected_files"] == []


def test_projection_repository_names_tolerate_missing_and_invalid_ids(
    owner_client: APIClient, artifact_version: ArtifactVersion
) -> None:
    """无对应仓库行 / 非法 id 时只是名字为空，端点不得 500。

    ``recommended_repository_ids`` 来自半可信的 ``execution_plan[].repository_id``：
    不过筛就把它喂 ``filter(id__in=...)``，一个非 UUID 字面量会抛 ``ValidationError``
    （同 MN-03）。这里不造 Repository 行，断言退化路径干净。
    """
    ArtifactVersion.objects.filter(id=artifact_version.id).update(
        content={
            **_CONTENT,
            "execution_plan": [
                {**_CONTENT["execution_plan"][0], "repository_id": "not-a-uuid"},
                _CONTENT["execution_plan"][1],
            ],
        }
    )
    resp = _post(owner_client, artifact_version.id)

    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["recommended_repositories"] == []
    assert "not-a-uuid" in body["recommended_repository_ids"]


def test_projection_requires_authentication(artifact_version: ArtifactVersion) -> None:
    """未认证请求不得投影（permission_classes = [IsAuthenticated]）。"""
    resp = _post(APIClient(), artifact_version.id)
    assert resp.status_code in (
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    )
    assert CodingPlan.objects.count() == 0


# ============================================================================
# 幂等 —— 重复点击只产一行
# ============================================================================


def test_projection_is_idempotent_across_two_requests(
    owner_client: APIClient, artifact_version: ArtifactVersion
) -> None:
    first = _post(owner_client, artifact_version.id)
    second = _post(owner_client, artifact_version.id)

    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_200_OK
    assert first.json()["coding_plan_id"] == second.json()["coding_plan_id"]
    assert first.json()["created"] is True
    # 幂等命中是中性结果，不是错误：前端据此走「已复用既有编码方案」toast。
    assert second.json()["created"] is False
    assert CodingPlan.objects.filter(source_artifact_version_id=artifact_version.id).count() == 1


# ============================================================================
# 404 —— 非 owner 与不存在同体同文
# ============================================================================


def test_projection_by_non_owner_returns_404_without_plan_body(
    outsider_client: APIClient, artifact_version: ArtifactVersion
) -> None:
    """非 owner → 404（不是 403），响应体不含方案正文，且不留下任何投影对象。"""
    resp = _post(outsider_client, artifact_version.id)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    body = resp.json()
    assert body["code"] == "artifact_version_not_found"
    assert "tech_plan" not in body
    assert "跨仓改造方案" not in resp.content.decode()
    # 越权请求必须在投影之前被挡住（否则会在他人会话下留垃圾对象）。
    assert CodingPlan.objects.count() == 0


def test_projection_service_gate_still_returns_404_when_view_gate_bypassed(
    outsider_client: APIClient, artifact_version: ArtifactVersion, outsider: Any
) -> None:
    """视图侧 owner gate 被绕过时，service 内的归属判定仍把越权请求挡成 404。

    109-05 把归属判定下移进 ``PlanProjectionService``（工具路径与本端点共享同一道门），
    视图里的 gate 降级为第二道纵深。本用例伪造只读解析结果让视图 gate 放行，验证真正
    的门在 service：``artifact_version_forbidden`` 与「不存在」同形映射 404，响应体
    不含方案正文，且不留下任何投影对象。
    """
    from unittest.mock import AsyncMock, patch

    decoy = Conversation.objects.create(
        space=Space.objects.create(
            name=f"诱饵空间-{uuid.uuid4().hex[:6]}",
            feishu_project_key=f"decoy-{uuid.uuid4().hex[:6]}",
        ),
        title="让视图 gate 放行的诱饵会话",
        created_by=outsider,
    )

    with patch.object(
        PlanProjectionService,
        "aresolve_conversation",
        new=AsyncMock(return_value=decoy),
    ):
        resp = _post(outsider_client, artifact_version.id)

    assert resp.status_code == status.HTTP_404_NOT_FOUND
    body = resp.json()
    assert body["code"] == "artifact_version_not_found"
    assert "tech_plan" not in body
    assert "跨仓改造方案" not in resp.content.decode()
    assert CodingPlan.objects.count() == 0


def test_projection_of_unknown_version_matches_non_owner_response(
    owner_client: APIClient,
    outsider_client: APIClient,
    artifact_version: ArtifactVersion,
) -> None:
    """「不存在」与「无权限」两条响应逐字节一致 —— 否则可用响应差异枚举探测存在性。"""
    unknown = owner_client.post(
        reverse(_URL_NAME),
        data={"artifact_version_id": str(uuid.uuid4())},
        format="json",
    )
    forbidden = _post(outsider_client, artifact_version.id)

    assert unknown.status_code == forbidden.status_code == status.HTTP_404_NOT_FOUND
    assert unknown.json()["code"] == "artifact_version_not_found"
    assert unknown.json() == forbidden.json()


# ============================================================================
# 400 —— D-3 边界与输入校验
# ============================================================================


def test_projection_without_conversation_returns_stable_code(owner_client: APIClient, db) -> None:
    """workflow 入口的编排会话（无 conversation）→ 400 + 稳定机器码，不建合成会话。"""
    version = _make_artifact_version(_make_session(None))
    conversations_before = Conversation.objects.count()

    resp = _post(owner_client, version.id)

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "projection_requires_chat_entrypoint"
    assert Conversation.objects.count() == conversations_before
    assert CodingPlan.objects.count() == 0


def test_projection_rejects_non_uuid_artifact_version_id(owner_client: APIClient) -> None:
    """非 UUID 字面量在序列化层即 400，不进入 ORM 查询（V5 Input Validation）。"""
    resp = owner_client.post(
        reverse(_URL_NAME),
        data={"artifact_version_id": "not-a-uuid"},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_projection_request_body_ignores_client_supplied_conversation(
    owner_client: APIClient,
    outsider: Any,
    artifact_version: ArtifactVersion,
) -> None:
    """请求体不接受 ``conversation_id``：客户端无法把投影落到他人会话（T-109-03-03）。"""
    other_space = Space.objects.create(
        name=f"他人空间-{uuid.uuid4().hex[:6]}",
        feishu_project_key=f"other-{uuid.uuid4().hex[:6]}",
    )
    hijack_target = Conversation.objects.create(
        space=other_space, title="他人会话", created_by=outsider
    )

    resp = owner_client.post(
        reverse(_URL_NAME),
        data={
            "artifact_version_id": str(artifact_version.id),
            "conversation_id": str(hijack_target.id),
        },
        format="json",
    )

    assert resp.status_code == status.HTTP_200_OK
    plan = CodingPlan.objects.get(id=resp.json()["coding_plan_id"])
    # 落点由服务端经 produced_by_session_id 解析，客户端传的会话被完全忽略。
    assert plan.conversation_id != hijack_target.id

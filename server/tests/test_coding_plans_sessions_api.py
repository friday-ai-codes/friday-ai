"""POST /api/chat/coding-plans/{id}/sessions/ 批量创建 API 测试。

覆盖 6 类场景：
- 3 仓库全成功
- 部分成功（1 仓库已有 active session）
- 全部失败（3 仓库都已有 active）
- 越权（403）
- plan 不存在（404）
- 请求体校验失败（400，空列表 / 超 20 限制）
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework import status

from chat.models import CodingPlan, CodingSession, Conversation
from permissions.models import SpaceMembership, SpaceRole
from repositories.models import Repository

if TYPE_CHECKING:
    from rest_framework.test import APIClient


@pytest.fixture
def coding_plan(db, project, user):
    """创建 Conversation + CodingPlan（project 已有 user 作为 ADMIN by `project_memberships`）。

    ``provenance`` 显式置为 ``orchestrated``：本 fixture 服务的既有 6 类场景测的是
    fan-out 端点自身的语义（成功 / 部分成功 / 全失败 / 403 / 404 / 400），走 DB
    default ``draft`` 会被 109-07 的草稿 gate 整批拦下变 400。这是 gate 生效的预期连带
    影响，不是回归；草稿路径由下方 ``TestCodingPlansSessionsDraftGate`` 独立覆盖。
    """
    from chat.models import CodingPlanProvenance

    SpaceMembership.objects.get_or_create(
        user=user, space=project, defaults={"role": SpaceRole.ADMIN}
    )
    conversation = Conversation.objects.create(
        space=project, title="work item 测试对话", created_by=user
    )
    return CodingPlan.objects.create(
        conversation=conversation,
        tech_plan="## work item 多仓 fan-out 方案\n- 步骤 1\n- 步骤 2",
        affected_files=[{"file_path": "src/main.py", "change_type": "modify"}],
        title="work item 方案",
        provenance=CodingPlanProvenance.ORCHESTRATED,
    )


@pytest.fixture
def draft_coding_plan(db, coding_plan):
    """把 plan 回落为存量真实形态 ``provenance=draft``（迁移 default）。"""
    from chat.models import CodingPlanProvenance

    CodingPlan.objects.filter(id=coding_plan.id).update(provenance=CodingPlanProvenance.DRAFT)
    coding_plan.refresh_from_db()
    return coding_plan


@pytest.fixture
def three_repos(db, project):
    """创建 3 个 Repository 并 attach 到 coding_plan.conversation.space。"""
    repos = []
    for i, name in enumerate(["repo-a", "repo-b", "repo-c"]):
        r = Repository.objects.create(
            name=name,
            git_url=f"https://gitlab.com/test/{name}.git",
            git_platform="gitlab",
            default_branch="main",
        )
        project.repositories.add(r)
        repos.append(r)
    return repos


@pytest.fixture
def other_user_client(api_client, other_user):
    """非 project 成员的 APIClient。"""
    api_client.force_authenticate(user=other_user)
    return api_client


@pytest.mark.django_db(transaction=True)
class TestCodingPlansSessionsBatchAPI:
    """work item 批量创建 endpoint 全状态码覆盖。"""

    def _url(self, plan_id: object) -> str:
        return reverse(
            "coding-plan-sessions-batch", kwargs={"plan_id": str(plan_id)}
        )

    def test_success_all_three_repos_created(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """3 仓库均无 active session → created=3，failed=0。"""
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": [str(r.id) for r in three_repos]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["created"]) == 3
        assert len(body["failed"]) == 0
        assert (
            CodingSession.objects.filter(
                coding_plan=coding_plan, status=CodingSession.Status.DRAFT
            ).count()
            == 3
        )

    def test_partial_success_one_repo_already_active(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """repo_a 预置 RUNNING → 仅 repo_b/c created，repo_a failed。"""
        repo_a, _repo_b, _repo_c = three_repos
        CodingSession.objects.create(
            conversation=coding_plan.conversation,
            coding_plan=coding_plan,
            repository=repo_a,
            tech_plan="x",
            status=CodingSession.Status.RUNNING,
        )
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": [str(r.id) for r in three_repos]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["created"]) == 2
        assert len(body["failed"]) == 1
        assert body["failed"][0]["repository_id"] == str(repo_a.id)
        assert "进行中" in body["failed"][0]["error"]

    def test_all_fail_when_all_already_active(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """3 仓库都已有 active session → created=0，failed=3。"""
        for r in three_repos:
            CodingSession.objects.create(
                conversation=coding_plan.conversation,
                coding_plan=coding_plan,
                repository=r,
                tech_plan="x",
                status=CodingSession.Status.RUNNING,
            )
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": [str(r.id) for r in three_repos]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["created"]) == 0
        assert len(body["failed"]) == 3

    def test_forbidden_when_user_not_in_project(
        self,
        other_user_client: "APIClient",
        coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """非 owner（且非 project 成员）→ owner gate 先于 project 403 触发，统一 404（不泄漏存在性）。"""
        resp = other_user_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": [str(three_repos[0].id)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_not_found_when_plan_missing(
        self, authenticated_client: "APIClient"
    ) -> None:
        """plan_id 不存在 → 404。"""
        resp = authenticated_client.post(
            self._url(uuid4()),
            data={"repository_ids": [str(uuid4())]},
            format="json",
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_bad_request_empty_repository_ids(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
    ) -> None:
        """repository_ids=[] → 400。"""
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": []},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_bad_request_over_20_repository_ids(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
    ) -> None:
        """repository_ids 超 20 个 → 400。"""
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": [str(uuid4()) for _ in range(21)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_repository_not_in_project_collected_as_failed(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
    ) -> None:
        """repository_ids 含项目下不存在的 UUID → failed 列表收集（不阻塞整体）。"""
        ghost_id = uuid4()
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": [str(ghost_id)]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["failed"]) == 1
        assert body["failed"][0]["repository_id"] == str(ghost_id)
        assert "无权访问" in body["failed"][0]["error"]


@pytest.mark.django_db(transaction=True)
class TestCodingPlansSessionsDraftGate:
    """RELY-01 草稿送编码 gate —— 全部**直接打端点**（不经前端）。

    本类存在的理由：只在前端弹层做防护等于没做 —— 用户或脚本直接 POST fan-out 端点
    就能绕过。因此这里一条前端代码都不涉及，断言的是服务端在 HTTP 边界上 fail-closed，
    且拒绝时 DB 零写入。
    """

    def _url(self, plan_id: object) -> str:
        return reverse(
            "coding-plan-sessions-batch", kwargs={"plan_id": str(plan_id)}
        )

    def test_draft_gate_rejects_when_field_absent(
        self,
        authenticated_client: "APIClient",
        draft_coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """draft + 请求体不带 acknowledge_unresearched → 400 + 稳定机器码 + 零写入。"""
        before = CodingSession.objects.count()
        resp = authenticated_client.post(
            self._url(draft_coding_plan.id),
            data={"repository_ids": [str(r.id) for r in three_repos]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert body["code"] == "draft_requires_explicit_confirm"
        assert body["detail"]
        # fail-closed 的实质断言：gate 位于任何 session 创建之前。
        assert CodingSession.objects.count() == before

    def test_draft_gate_rejects_when_field_explicitly_false(
        self,
        authenticated_client: "APIClient",
        draft_coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """draft + acknowledge_unresearched=false → 同样 400（false 不等于确认）。"""
        resp = authenticated_client.post(
            self._url(draft_coding_plan.id),
            data={
                "repository_ids": [str(r.id) for r in three_repos],
                "acknowledge_unresearched": False,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "draft_requires_explicit_confirm"
        assert CodingSession.objects.filter(coding_plan=draft_coding_plan).count() == 0

    def test_draft_gate_allows_when_acknowledged_true(
        self,
        authenticated_client: "APIClient",
        draft_coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """draft + acknowledge_unresearched=true → 200 且 session 正常创建。"""
        resp = authenticated_client.post(
            self._url(draft_coding_plan.id),
            data={
                "repository_ids": [str(r.id) for r in three_repos],
                "acknowledge_unresearched": True,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["created"]) == 3
        assert len(body["failed"]) == 0
        assert CodingSession.objects.filter(coding_plan=draft_coding_plan).count() == 3

    def test_draft_gate_orchestrated_plan_without_field_succeeds(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """orchestrated + 不带该字段 → 200（编排方案零摩擦，行为与今日一致）。"""
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": [str(r.id) for r in three_repos]},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()["created"]) == 3

    def test_draft_gate_orchestrated_plan_ignores_acknowledge_flag(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """orchestrated + acknowledge_unresearched=true → 与不带时结果一致（字段被忽略）。

        这条是前端保守默认（缺 provenance 视为草稿 ⇒ 可能多带一次 ack）能安全落地的前提：
        该字段对非草稿方案必须是无操作的。
        """
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={
                "repository_ids": [str(r.id) for r in three_repos],
                "acknowledge_unresearched": True,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert len(body["created"]) == 3
        assert len(body["failed"]) == 0

    def test_draft_gate_unknown_provenance_requires_confirm(
        self,
        authenticated_client: "APIClient",
        coding_plan: CodingPlan,
        three_repos: list[Repository],
    ) -> None:
        """未知 provenance 取值 + 不带确认 → 400（允许清单的保守分支）。

        直接 ``queryset.update`` 绕过 choices 校验写入非法值，模拟未来新增枚举值 /
        数据被外部写坏。判定若用拒绝清单（``== draft`` 才拦）这里会静默放行。
        """
        CodingPlan.objects.filter(id=coding_plan.id).update(provenance="weird_value")
        resp = authenticated_client.post(
            self._url(coding_plan.id),
            data={"repository_ids": [str(r.id) for r in three_repos]},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == "draft_requires_explicit_confirm"
        assert CodingSession.objects.filter(coding_plan=coding_plan).count() == 0

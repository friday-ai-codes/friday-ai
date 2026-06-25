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
    """创建 Conversation + CodingPlan（project 已有 user 作为 ADMIN by `project_memberships`）。"""
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
    )


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

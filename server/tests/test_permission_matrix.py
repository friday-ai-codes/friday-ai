"""权限矩阵集成测试：角色 x 端点 x 期望状态码。"""

import pytest
from django.contrib.auth import get_user_model

from permissions.models import SpaceMembership, SpaceRole
from projects.models import Space

User = get_user_model()


@pytest.mark.django_db
class TestSystemSettingsPermissions:
    """系统设置端点权限测试。"""

    def test_superuser_can_list_settings(self, authenticated_admin_client, urls):
        """superuser 可以列出系统设置。"""
        response = authenticated_admin_client.get(urls.settings_list)
        assert response.status_code == 200

    def test_regular_user_cannot_list_settings(self, authenticated_client, urls):
        """普通用户不能列出系统设置。"""
        response = authenticated_client.get(urls.settings_list)
        assert response.status_code == 403

    def test_unauthenticated_cannot_list_settings(self, api_client, urls):
        """未认证用户不能列出系统设置。"""
        response = api_client.get(urls.settings_list)
        assert response.status_code in (401, 403)


@pytest.mark.django_db
class TestRunnerPermissions:
    """Runner 管理端点权限测试。"""

    def test_superuser_can_list_runners(self, authenticated_admin_client):
        """superuser 可以列出 Runner。"""
        response = authenticated_admin_client.get("/api/runners/")
        assert response.status_code == 200

    def test_regular_user_cannot_list_runners(self, authenticated_client):
        """普通用户不能列出 Runner。"""
        response = authenticated_client.get("/api/runners/")
        assert response.status_code == 403

    def test_superuser_can_list_registration_tokens(self, authenticated_admin_client):
        """superuser 可以列出注册令牌。"""
        response = authenticated_admin_client.get("/api/runners/tokens/")
        assert response.status_code == 200

    def test_regular_user_cannot_list_registration_tokens(self, authenticated_client):
        """普通用户不能列出注册令牌。"""
        response = authenticated_client.get("/api/runners/tokens/")
        assert response.status_code == 403


@pytest.mark.django_db
class TestProjectListPermissions:
    """项目列表权限测试。"""

    def test_superuser_sees_all_projects(
        self, authenticated_admin_client, project, second_project, urls
    ):
        """superuser 看到所有项目。"""
        response = authenticated_admin_client.get(urls.space_list)
        assert response.status_code == 200
        project_ids = {str(p["id"]) for p in response.data}
        assert str(project.id) in project_ids
        assert str(second_project.id) in project_ids

    def test_member_sees_only_own_projects(
        self,
        authenticated_member_client,
        project,
        second_project,
        project_memberships,
        urls,
    ):
        """member 只看到自己所属的项目。"""
        response = authenticated_member_client.get(urls.space_list)
        assert response.status_code == 200
        project_ids = {str(p["id"]) for p in response.data}
        assert str(project.id) in project_ids
        assert str(second_project.id) not in project_ids

    def test_non_member_sees_no_projects(
        self, api_client, other_user, project, second_project, urls
    ):
        """非成员看不到任何项目。"""
        api_client.force_authenticate(user=other_user)
        response = api_client.get(urls.space_list)
        assert response.status_code == 200
        assert len(response.data) == 0


@pytest.mark.django_db
class TestProjectCreationPermissions:
    """项目创建权限测试。"""

    def test_create_project_auto_assigns_admin(
        self, authenticated_client, user, urls
    ):
        """创建项目后创建者自动成为 admin。"""
        response = authenticated_client.post(
            urls.space_list,
            {
                "name": "New Space",
                "feishu_project_key": "new-project-key",
            },
            format="json",
        )
        assert response.status_code == 201

        # 验证创建者是 admin
        new_project = Space.objects.get(name="New Space")
        membership = SpaceMembership.objects.get(user=user, space=new_project)
        assert membership.role == SpaceRole.ADMIN


@pytest.mark.django_db
class TestTenantIsolationE2E:
    """租户隔离端到端测试。"""

    def test_cross_project_workflow_list_empty(
        self,
        api_client,
        project,
        second_project,
        project_memberships,
        member_user,
    ):
        """member_user 是 project 的成员，看不到 second_project 的工作流。"""
        from workflows.models import Workflow

        # 在 second_project 创建一个工作流
        wf = Workflow.objects.create(
            name="Secret Workflow",
            space=second_project,
        )

        api_client.force_authenticate(user=member_user)
        response = api_client.get("/api/workflows/")
        assert response.status_code == 200

        # member_user 不应该看到 second_project 的工作流
        workflow_ids = {str(w["id"]) for w in response.data}
        assert str(wf.id) not in workflow_ids

    def test_superuser_sees_all_workflows(
        self,
        authenticated_admin_client,
        project,
        second_project,
    ):
        """superuser 看到所有项目的工作流。"""
        from workflows.models import Workflow

        wf1 = Workflow.objects.create(name="WF1", space=project)
        wf2 = Workflow.objects.create(name="WF2", space=second_project)

        response = authenticated_admin_client.get("/api/workflows/")
        assert response.status_code == 200

        workflow_ids = {str(w["id"]) for w in response.data}
        assert str(wf1.id) in workflow_ids
        assert str(wf2.id) in workflow_ids

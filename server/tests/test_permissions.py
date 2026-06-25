"""权限引擎核心测试：PermissionService + 权限类 + Mixin。"""

import pytest
from django.contrib.auth import get_user_model

from permissions.models import SpaceRole
from permissions.services import PermissionService

User = get_user_model()


@pytest.mark.django_db
class TestPermissionServiceHasProjectAccess:
    """测试 PermissionService.has_project_access。"""

    def test_superuser_always_has_access(self, admin_user, project):
        """superuser 始终有权限，即使不是项目成员。"""
        assert PermissionService.has_project_access(admin_user, project) is True
        assert (
            PermissionService.has_project_access(
                admin_user, project, SpaceRole.ADMIN
            )
            is True
        )

    def test_admin_has_admin_access(self, user, project, project_memberships):
        """admin 角色满足 admin 最低要求。"""
        assert (
            PermissionService.has_project_access(user, project, SpaceRole.ADMIN)
            is True
        )

    def test_admin_has_member_access(self, user, project, project_memberships):
        """admin 角色满足 member 最低要求。"""
        assert (
            PermissionService.has_project_access(user, project, SpaceRole.MEMBER)
            is True
        )

    def test_admin_has_viewer_access(self, user, project, project_memberships):
        """admin 角色满足 viewer 最低要求。"""
        assert (
            PermissionService.has_project_access(user, project, SpaceRole.VIEWER)
            is True
        )

    def test_member_has_member_access(
        self, member_user, project, project_memberships
    ):
        """member 角色满足 member 最低要求。"""
        assert (
            PermissionService.has_project_access(
                member_user, project, SpaceRole.MEMBER
            )
            is True
        )

    def test_member_denied_admin_access(
        self, member_user, project, project_memberships
    ):
        """member 角色不满足 admin 最低要求。"""
        assert (
            PermissionService.has_project_access(
                member_user, project, SpaceRole.ADMIN
            )
            is False
        )

    def test_viewer_has_viewer_access(
        self, viewer_user, project, project_memberships
    ):
        """viewer 角色满足 viewer 最低要求。"""
        assert (
            PermissionService.has_project_access(
                viewer_user, project, SpaceRole.VIEWER
            )
            is True
        )

    def test_viewer_denied_member_access(
        self, viewer_user, project, project_memberships
    ):
        """viewer 角色不满足 member 最低要求。"""
        assert (
            PermissionService.has_project_access(
                viewer_user, project, SpaceRole.MEMBER
            )
            is False
        )

    def test_non_member_denied(self, other_user, project):
        """非成员无权限。"""
        assert (
            PermissionService.has_project_access(other_user, project) is False
        )

    def test_default_min_role_is_viewer(
        self, viewer_user, project, project_memberships
    ):
        """默认最低角色是 viewer。"""
        assert (
            PermissionService.has_project_access(viewer_user, project) is True
        )


@pytest.mark.django_db
class TestPermissionServiceGetUserRole:
    """测试 PermissionService.get_user_role。"""

    def test_returns_admin_role(self, user, project, project_memberships):
        assert PermissionService.get_user_role(user, project) == SpaceRole.ADMIN

    def test_returns_member_role(
        self, member_user, project, project_memberships
    ):
        assert (
            PermissionService.get_user_role(member_user, project)
            == SpaceRole.MEMBER
        )

    def test_returns_viewer_role(
        self, viewer_user, project, project_memberships
    ):
        assert (
            PermissionService.get_user_role(viewer_user, project)
            == SpaceRole.VIEWER
        )

    def test_returns_none_for_non_member(self, other_user, project):
        assert PermissionService.get_user_role(other_user, project) is None


@pytest.mark.django_db
class TestPermissionServiceGetUserProjects:
    """测试 PermissionService.get_user_projects。"""

    def test_superuser_sees_all_projects(
        self, admin_user, project, second_project
    ):
        """superuser 看到所有项目。"""
        projects = PermissionService.get_user_projects(admin_user)
        assert project in projects
        assert second_project in projects

    def test_member_sees_own_projects(
        self, member_user, project, second_project, project_memberships
    ):
        """普通用户只看到自己所属的项目。"""
        projects = PermissionService.get_user_projects(member_user)
        assert project in projects
        assert second_project not in projects

    def test_non_member_sees_no_projects(
        self, other_user, project, second_project
    ):
        """非成员看不到任何项目。"""
        projects = PermissionService.get_user_projects(other_user)
        assert projects.count() == 0


@pytest.mark.django_db
class TestIsSuperUser:
    """测试 IsSuperUser 权限类。"""

    def test_superuser_allowed(self, admin_user):
        from types import SimpleNamespace

        from permissions.api_permissions import IsSuperUser

        request = SimpleNamespace(user=admin_user)
        perm = IsSuperUser()
        assert perm.has_permission(request, None) is True

    def test_regular_user_denied(self, user):
        from types import SimpleNamespace

        from permissions.api_permissions import IsSuperUser

        request = SimpleNamespace(user=user)
        perm = IsSuperUser()
        assert perm.has_permission(request, None) is False

    def test_unauthenticated_denied(self):
        from types import SimpleNamespace

        from django.contrib.auth.models import AnonymousUser

        from permissions.api_permissions import IsSuperUser

        request = SimpleNamespace(user=AnonymousUser())
        perm = IsSuperUser()
        assert perm.has_permission(request, None) is False


@pytest.mark.django_db
class TestCrossProjectIsolation:
    """测试跨项目隔离。"""

    def test_user_cannot_access_other_project(
        self, member_user, second_project, project_memberships
    ):
        """member_user 是 project 的成员，但不是 second_project 的成员。"""
        assert (
            PermissionService.has_project_access(member_user, second_project)
            is False
        )

    def test_user_has_access_to_own_project(
        self, member_user, project, project_memberships
    ):
        """member_user 可以访问自己所属的项目。"""
        assert (
            PermissionService.has_project_access(member_user, project) is True
        )

    def test_superuser_can_access_any_project(
        self, admin_user, project, second_project
    ):
        """superuser 可以访问任何项目。"""
        assert (
            PermissionService.has_project_access(admin_user, project) is True
        )
        assert (
            PermissionService.has_project_access(admin_user, second_project)
            is True
        )

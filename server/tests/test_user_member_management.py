"""implementation 用户与成员管理测试。

覆盖需求：work item, work item, work item, work item, work item, work item, work item
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Invitation
from permissions.models import SpaceMembership

User = get_user_model()


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def invitation(db, admin_user):
    """创建一个有效的邀请令牌。"""
    return Invitation.objects.create(
        created_by=admin_user,
        email="newuser@example.com",
    )


@pytest.fixture
def expired_invitation(db, admin_user):
    """创建一个已过期的邀请令牌。"""
    # 直接操作数据库绕过 save() 自动设置 expires_at 的逻辑
    inv = Invitation.objects.create(
        created_by=admin_user,
        email="expired@example.com",
    )
    Invitation.objects.filter(pk=inv.pk).update(
        expires_at=timezone.now() - timezone.timedelta(hours=1)
    )
    inv.refresh_from_db()
    return inv


@pytest.fixture
def used_invitation(db, admin_user):
    """创建一个已使用的邀请令牌。"""
    inv = Invitation.objects.create(
        created_by=admin_user,
        email="used@example.com",
    )
    Invitation.objects.filter(pk=inv.pk).update(accepted_at=timezone.now())
    inv.refresh_from_db()
    return inv


# ============================================================================
# Invitation 模型单元测试
# ============================================================================

@pytest.mark.django_db
class TestInvitationModel:
    """Invitation 模型单元测试（work item）。"""

    def test_invitation_is_valid_when_unused_and_not_expired(self, invitation):
        """未使用且未过期的邀请令牌有效。"""
        assert invitation.is_valid() is True

    def test_invitation_invalid_when_accepted(self, used_invitation):
        """已接受的邀请令牌无效。"""
        assert used_invitation.is_valid() is False

    def test_invitation_invalid_when_expired(self, expired_invitation):
        """已过期的邀请令牌无效。"""
        assert expired_invitation.is_valid() is False

    def test_invitation_token_is_unique(self, db, admin_user):
        """令牌字段唯一性约束。"""
        inv1 = Invitation.objects.create(created_by=admin_user)
        inv2 = Invitation.objects.create(created_by=admin_user)
        assert inv1.token != inv2.token

    def test_invitation_default_expires_7_days(self, invitation):
        """默认过期时间为 7 天。"""
        delta = invitation.expires_at - invitation.created_at
        # 7 天 = 604800 秒，允许 5 秒误差
        assert abs(delta.total_seconds() - 7 * 24 * 3600) < 5


# ============================================================================
# 邀请 API 集成测试
# ============================================================================

@pytest.mark.django_db
class TestInvitationAPI:
    """邀请 API 端点测试（work item）。"""

    def test_admin_can_create_invitation(self, authenticated_admin_client):
        """管理员可创建邀请令牌。"""
        resp = authenticated_admin_client.post("/api/auth/invite/", {"email": "new@example.com"}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert "token" in resp.data
        assert resp.data["email"] == "new@example.com"

    def test_non_admin_cannot_create_invitation(self, authenticated_client):
        """非管理员无法创建邀请令牌。"""
        resp = authenticated_client.post("/api/auth/invite/", {"email": "new@example.com"}, format="json")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_create_invitation_without_email(self, authenticated_admin_client):
        """创建邀请令牌时邮箱可选。"""
        resp = authenticated_admin_client.post("/api/auth/invite/", {}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert "token" in resp.data

    def test_validate_valid_invitation(self, authenticated_admin_client, invitation):
        """校验有效的邀请令牌。"""
        resp = authenticated_admin_client.get(f"/api/auth/invite/?token={invitation.token}")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["token"] == invitation.token

    def test_validate_expired_invitation_returns_410(self, authenticated_admin_client, expired_invitation):
        """校验已过期的邀请令牌返回 410。"""
        resp = authenticated_admin_client.get(f"/api/auth/invite/?token={expired_invitation.token}")
        assert resp.status_code == status.HTTP_410_GONE

    def test_validate_nonexistent_token_returns_404(self, authenticated_admin_client):
        """校验不存在的令牌返回 404。"""
        resp = authenticated_admin_client.get("/api/auth/invite/?token=nonexistent-token-abc")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_accept_invitation_creates_user(self, api_client, invitation):
        """接受邀请令牌后创建新用户。"""
        resp = api_client.post("/api/auth/invite/accept/", {
            "token": invitation.token,
            "username": "newuser",
            "password": "securepassword123",
            "display_name": "New User",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["username"] == "newuser"
        assert resp.data["source"] == "invitation"
        created = User.objects.get(username="newuser")
        assert created.source == "invitation"

    def test_accept_invitation_marks_it_used(self, api_client, invitation):
        """接受邀请令牌后令牌被标记为已使用。"""
        api_client.post("/api/auth/invite/accept/", {
            "token": invitation.token,
            "username": "newuser2",
            "password": "securepassword123",
        }, format="json")
        invitation.refresh_from_db()
        assert invitation.accepted_at is not None
        assert invitation.is_valid() is False

    def test_accept_used_invitation_returns_410(self, api_client, used_invitation):
        """无法使用已使用的邀请令牌注册。"""
        resp = api_client.post("/api/auth/invite/accept/", {
            "token": used_invitation.token,
            "username": "anotheruser",
            "password": "securepassword123",
        }, format="json")
        assert resp.status_code == status.HTTP_410_GONE


# ============================================================================
# /me API 扩展测试
# ============================================================================

@pytest.mark.django_db
class TestMeApi:
    """扩展 /me API 测试（work item, work item）。"""

    def test_me_returns_gravatar_url(self, authenticated_client, user):
        """GET /me 返回 gravatar_url 字段。"""
        resp = authenticated_client.get("/api/auth/me/")
        assert resp.status_code == status.HTTP_200_OK
        assert "gravatar_url" in resp.data
        # user 有 email=test@example.com，应有 gravatar_url
        assert resp.data["gravatar_url"] is not None
        assert "gravatar.com/avatar/" in resp.data["gravatar_url"]

    def test_me_returns_project_memberships(self, authenticated_client, user, project_memberships):
        """GET /me 返回用户所属空间列表。"""
        resp = authenticated_client.get("/api/auth/me/")
        assert resp.status_code == status.HTTP_200_OK
        assert "space_memberships" in resp.data
        assert len(resp.data["space_memberships"]) >= 1
        membership = resp.data["space_memberships"][0]
        assert "space_id" in membership
        assert "space_name" in membership
        assert "role" in membership

    def test_me_profile_update(self, authenticated_client, user):
        """PATCH /me/profile 更新用户显示名。"""
        resp = authenticated_client.patch("/api/auth/me/profile/", {"display_name": "Updated Name"}, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["display_name"] == "Updated Name"
        user.refresh_from_db()
        assert user.display_name == "Updated Name"


# ============================================================================
# 系统用户管理测试
# ============================================================================

@pytest.mark.django_db
class TestUserManagement:
    """系统用户管理 API 测试（work item）。"""

    def test_admin_can_list_users(self, authenticated_admin_client, user):
        """管理员可查看用户列表。"""
        resp = authenticated_admin_client.get("/api/auth/users/")
        assert resp.status_code == status.HTTP_200_OK
        assert isinstance(resp.data, list)
        usernames = [u["username"] for u in resp.data]
        assert "testuser" in usernames or user.username in usernames

    def test_non_admin_cannot_list_users(self, authenticated_client):
        """非管理员无法查看用户列表。"""
        resp = authenticated_client.get("/api/auth/users/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_can_disable_user(self, authenticated_admin_client, user):
        """管理员可禁用用户账号。"""
        resp = authenticated_admin_client.patch(
            f"/api/auth/users/{user.pk}/",
            {"is_active": False},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_active"] is False
        user.refresh_from_db()
        assert user.is_active is False

    def test_admin_can_enable_user(self, authenticated_admin_client, user):
        """管理员可启用已禁用的用户账号。"""
        user.is_active = False
        user.save()
        resp = authenticated_admin_client.patch(
            f"/api/auth/users/{user.pk}/",
            {"is_active": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_active"] is True

    def test_admin_can_grant_superuser(self, authenticated_admin_client, user):
        """超级管理员可授予普通用户超级管理员身份。"""
        resp = authenticated_admin_client.patch(
            f"/api/auth/users/{user.pk}/",
            {"is_superuser": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superuser"] is True
        user.refresh_from_db()
        assert user.is_superuser is True

    def test_admin_can_revoke_other_superuser(self, authenticated_admin_client, user):
        """系统仍有其他超管时，可取消某个超管的身份。"""
        user.is_superuser = True
        user.save()
        resp = authenticated_admin_client.patch(
            f"/api/auth/users/{user.pk}/",
            {"is_superuser": False},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["is_superuser"] is False
        user.refresh_from_db()
        assert user.is_superuser is False

    def test_admin_cannot_revoke_own_superuser(self, authenticated_admin_client, admin_user, user):
        """超级管理员不能取消自己的超级管理员身份（防误操作锁死）。"""
        # 另造一个超管以排除「最后一个超管」因素，单独验证自我保护
        user.is_superuser = True
        user.save()
        resp = authenticated_admin_client.patch(
            f"/api/auth/users/{admin_user.pk}/",
            {"is_superuser": False},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        admin_user.refresh_from_db()
        assert admin_user.is_superuser is True

    def test_cannot_revoke_last_superuser(self, authenticated_admin_client, admin_user):
        """系统必须保留至少一个超级管理员：取消最后一个超管被拒。"""
        resp = authenticated_admin_client.patch(
            f"/api/auth/users/{admin_user.pk}/",
            {"is_superuser": False},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        admin_user.refresh_from_db()
        assert admin_user.is_superuser is True

    def test_non_admin_cannot_grant_superuser(self, authenticated_client, other_user):
        """非超级管理员无法授予超管身份。"""
        resp = authenticated_client.patch(
            f"/api/auth/users/{other_user.pk}/",
            {"is_superuser": True},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        other_user.refresh_from_db()
        assert other_user.is_superuser is False

    def test_admin_can_get_user_memberships(self, authenticated_admin_client, user, project):
        """超级管理员可查询某用户的跨空间成员关系。"""
        SpaceMembership.objects.create(user=user, space=project, role="member")
        resp = authenticated_admin_client.get(f"/api/auth/users/{user.pk}/memberships/")
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.data) == 1
        assert resp.data[0]["space_id"] == str(project.pk)
        assert resp.data[0]["space_name"] == project.name
        assert resp.data[0]["role"] == "member"

    def test_non_admin_cannot_get_user_memberships(self, authenticated_client, other_user):
        """非超级管理员无法查询他人成员关系。"""
        resp = authenticated_client.get(f"/api/auth/users/{other_user.pk}/memberships/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ============================================================================
# 项目成员 CRUD 测试
# ============================================================================

@pytest.mark.django_db
class TestProjectMembers:
    """项目成员 CRUD API 测试（work item, work item, work item）。"""

    def test_project_admin_can_list_members(self, authenticated_client, project, project_memberships):
        """项目 admin 可查看成员列表。"""
        resp = authenticated_client.get(f"/api/spaces/{project.pk}/members/")
        assert resp.status_code == status.HTTP_200_OK
        assert isinstance(resp.data, list)
        assert len(resp.data) >= 1

    def test_member_can_list_members(self, authenticated_member_client, project, project_memberships):
        """项目 member 可查看成员列表。"""
        resp = authenticated_member_client.get(f"/api/spaces/{project.pk}/members/")
        assert resp.status_code == status.HTTP_200_OK

    def test_non_member_cannot_list_members(self, api_client, other_user, project, project_memberships):
        """非成员无法查看成员列表。"""
        client = APIClient()
        client.force_authenticate(user=other_user)
        resp = client.get(f"/api/spaces/{project.pk}/members/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_project_admin_can_add_member(self, authenticated_client, project, other_user, project_memberships):
        """项目 admin 可添加新成员。"""
        resp = authenticated_client.post(
            f"/api/spaces/{project.pk}/members/",
            {"user_id": str(other_user.pk), "role": "member"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["role"] == "member"
        assert SpaceMembership.objects.filter(user=other_user, space=project).exists()

    def test_non_admin_cannot_add_member(self, authenticated_member_client, project, other_user, project_memberships):
        """非 admin 成员无法添加新成员。"""
        resp = authenticated_member_client.post(
            f"/api/spaces/{project.pk}/members/",
            {"user_id": str(other_user.pk), "role": "member"},
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_add_duplicate_member_returns_409(self, authenticated_client, project, member_user, project_memberships):
        """重复添加成员返回 409。"""
        resp = authenticated_client.post(
            f"/api/spaces/{project.pk}/members/",
            {"user_id": str(member_user.pk), "role": "viewer"},
            format="json",
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_project_admin_can_update_member_role(self, authenticated_client, project, member_user, project_memberships):
        """项目 admin 可变更成员角色。"""
        resp = authenticated_client.patch(
            f"/api/spaces/{project.pk}/members/{member_user.pk}/",
            {"role": "viewer"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["role"] == "viewer"
        membership = SpaceMembership.objects.get(user=member_user, space=project)
        assert membership.role == "viewer"

    def test_project_admin_can_remove_member(self, authenticated_client, project, member_user, project_memberships):
        """项目 admin 可移除成员。"""
        resp = authenticated_client.delete(f"/api/spaces/{project.pk}/members/{member_user.pk}/")
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        assert not SpaceMembership.objects.filter(user=member_user, space=project).exists()

    def test_non_admin_cannot_remove_member(self, authenticated_member_client, project, viewer_user, project_memberships):
        """非 admin 成员无法移除其他成员。"""
        resp = authenticated_member_client.delete(f"/api/spaces/{project.pk}/members/{viewer_user.pk}/")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_remove_nonexistent_member_returns_404(self, authenticated_client, project, other_user, project_memberships):
        """移除不存在的成员关系返回 404。"""
        resp = authenticated_client.delete(f"/api/spaces/{project.pk}/members/{other_user.pk}/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

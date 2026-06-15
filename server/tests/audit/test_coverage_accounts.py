"""审计 emit 覆盖测试 —— accounts / access_tokens / system apps。

覆盖 COV-01（用户管理）、COV-07（访问令牌）、COV-08（系统设置 + 供应商凭证）。
每个测试执行真实操作后 assert AuditEvent 存在。
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import UserSource
from audit.models import AuditEvent
from system.models import SettingKeys, SystemSetting

User = get_user_model()


def _make_user(**kwargs):
    """创建测试用户。"""
    defaults = {"username": f"testuser-{uuid.uuid4().hex[:8]}", "password": "testpass123"}
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def _make_superuser(**kwargs):
    """创建测试 superuser。"""
    defaults = {"username": f"admin-{uuid.uuid4().hex[:8]}", "password": "adminpass123"}
    defaults.update(kwargs)
    return User.objects.create_superuser(**defaults)


# ============================================================================
# COV-01: 用户管理
# ============================================================================


@pytest.mark.django_db
class TestUserLoginAudit:
    """COV-01: 用户登录产生审计事件。"""

    def test_login_emits_user_login_event(self):
        """LoginView.post 登录成功后 emit user.login。"""
        user = _make_user()
        client = APIClient()

        response = client.post("/api/auth/login/", {"username": user.username, "password": "testpass123"})
        assert response.status_code == 200

        event = AuditEvent.objects.filter(action="user.login", target_type="User").first()
        assert event is not None
        assert str(user.id) == event.target_id


@pytest.mark.django_db
class TestUserCreationAudit:
    """COV-01: 用户创建产生审计事件。"""

    def test_invitation_accept_emits_user_created_event(self):
        """InvitationAcceptView.post 接受邀请后 emit user.created。"""
        from accounts.models import Invitation

        inviter = _make_superuser()
        invitation = Invitation.objects.create(created_by=inviter, email="new@example.com")

        client = APIClient()
        response = client.post(
            "/api/auth/invite/accept/",
            {
                "token": invitation.token,
                "username": f"invited-{uuid.uuid4().hex[:6]}",
                "password": "newpass123",
                "display_name": "New User",
            },
        )
        assert response.status_code == 201

        event = AuditEvent.objects.filter(action="user.created", target_type="User").first()
        assert event is not None
        assert event.after.get("source") == UserSource.INVITATION.value


@pytest.mark.django_db
class TestUserUpdateAudit:
    """COV-01: 用户状态变更产生审计事件。"""

    def test_user_detail_patch_emits_user_updated_event(self):
        """UserDetailView.patch 修改 is_active 后 emit user.updated。"""
        admin = _make_superuser()
        target = _make_user()

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.patch(
            f"/api/auth/users/{target.id}/",
            {"is_active": False},
            format="json",
        )
        assert response.status_code == 200

        event = AuditEvent.objects.filter(
            action="user.updated", target_type="User", target_id=str(target.id)
        ).first()
        assert event is not None
        assert event.before.get("is_active") is True
        assert event.after.get("is_active") is False


@pytest.mark.django_db
class TestPasswordChangeAudit:
    """COV-01: 密码修改产生审计事件。"""

    def test_change_password_emits_event(self):
        """ChangePasswordView.post 修改密码后 emit user.password_changed。"""
        user = _make_user(password="oldpass123")

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/auth/change-password/",
            {"old_password": "oldpass123", "new_password": "newpass456"},
            format="json",
        )
        assert response.status_code == 200

        event = AuditEvent.objects.filter(
            action="user.password_changed", target_type="User", target_id=str(user.id)
        ).first()
        assert event is not None


@pytest.mark.django_db
class TestProfileUpdateAudit:
    """COV-01: 个人资料更新产生审计事件。"""

    def test_profile_update_emits_event(self):
        """ProfileUpdateView.patch 更新 display_name 后 emit user.updated。"""
        user = _make_user()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.patch(
            "/api/auth/me/profile/",
            {"display_name": "New Name"},
            format="json",
        )
        assert response.status_code == 200

        event = AuditEvent.objects.filter(
            action="user.updated", target_type="User", target_id=str(user.id)
        ).first()
        assert event is not None
        assert event.after.get("display_name") == "New Name"


# ============================================================================
# COV-07: 访问令牌
# ============================================================================


@pytest.mark.django_db
class TestAccessTokenAudit:
    """COV-07: 访问令牌操作产生审计事件。"""

    def test_create_token_emits_event(self):
        """AccessTokenViewSet.create 创建令牌后 emit access_token.created。"""
        user = _make_user()

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(
            "/api/access-tokens/",
            {"name": "test-token"},
            format="json",
        )
        assert response.status_code == 201

        event = AuditEvent.objects.filter(action="access_token.created").first()
        assert event is not None
        assert event.after.get("name") == "test-token"

    def test_revoke_token_emits_event(self):
        """AccessTokenViewSet.revoke 吊销令牌后 emit access_token.revoked。"""
        from access_tokens.models import AccessToken, generate_pat
        from runners.models import hash_token

        user = _make_user()
        plaintext = generate_pat()
        token = AccessToken.objects.create(
            name="revoke-test",
            token_hash=hash_token(plaintext),
            token_prefix=plaintext[:12],
            token_suffix=plaintext[-4:],
            created_by=user,
        )

        client = APIClient()
        client.force_authenticate(user=user)
        response = client.post(f"/api/access-tokens/{token.id}/revoke/")
        assert response.status_code == 200

        event = AuditEvent.objects.filter(action="access_token.revoked").first()
        assert event is not None
        assert str(token.id) == event.target_id


# ============================================================================
# COV-08: 系统设置
# ============================================================================


@pytest.mark.django_db
class TestSystemSettingAudit:
    """COV-08: 系统设置操作产生审计事件。"""

    def test_create_setting_emits_event(self):
        """SettingsListCreateView.post 创建设置后 emit system_setting.created。"""
        admin = _make_superuser()

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.post(
            "/api/settings/",
            {"key": "TEST_KEY", "value": "test_value", "description": "test"},
            format="json",
        )
        assert response.status_code == 201

        event = AuditEvent.objects.filter(
            action="system_setting.created", target_id="TEST_KEY"
        ).first()
        assert event is not None

    def test_update_setting_emits_event(self):
        """SettingsDetailView.put 更新设置后 emit system_setting.updated。"""
        admin = _make_superuser()
        SystemSetting.objects.create(key="UPD_KEY", value="old_value")

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.put(
            "/api/settings/UPD_KEY/",
            {"value": "new_value"},
            format="json",
        )
        assert response.status_code == 200

        event = AuditEvent.objects.filter(
            action="system_setting.updated", target_id="UPD_KEY"
        ).first()
        assert event is not None

    def test_delete_setting_emits_event(self):
        """SettingsDetailView.delete 删除设置后 emit system_setting.deleted。"""
        admin = _make_superuser()
        SystemSetting.objects.create(key="DEL_KEY", value="to_delete")

        client = APIClient()
        client.force_authenticate(user=admin)
        response = client.delete("/api/settings/DEL_KEY/")
        assert response.status_code == 204

        event = AuditEvent.objects.filter(
            action="system_setting.deleted", target_id="DEL_KEY"
        ).first()
        assert event is not None

"""Phase 用户与成员管理测试。
覆盖需求：,,,,,,
"""
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from accounts.models import Invitation
from permissions.models import ProjectMembership, ProjectRole
User = get_user_model
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
 # 直接操作数据库绕过 save 自动设置 expires_at 的逻辑
 inv = Invitation.objects.create(
 created_by=admin_user,
 email="expired@example.com",
 )
 Invitation.objects.filter(pk=inv.pk).update(
 expires_at=timezone.now - timezone.timedelta(hours=1)
 )
 inv.refresh_from_db
 return inv
@pytest.fixture
def used_invitation(db, admin_user):
 """创建一个已使用的邀请令牌。"""
 inv = Invitation.objects.create(
 created_by=admin_user,
 email="used@example.com",
 )
 Invitation.objects.filter(pk=inv.pk).update(accepted_at=timezone.now)
 inv.refresh_from_db
 return inv
# ============================================================================
#: Invitation 模型单元测试
# ============================================================================
@pytest.mark.django_db
class TestInvitationModel:
 """Invitation 模型单元测试。"""
 def test_invitation_is_valid_when_unused_and_not_expired(self, invitation):
 """未使用且未过期的邀请令牌有效。"""
 assert invitation.is_valid is True
 def test_invitation_invalid_when_accepted(self, used_invitation):
 """已接受的邀请令牌无效。"""
 assert used_invitation.is_valid is False
 def test_invitation_invalid_when_expired(self, expired_invitation):
 """已过期的邀请令牌无效。"""
 assert expired_invitation.is_valid is False
 def test_invitation_token_is_unique(self, db, admin_user):
 """令牌字段唯一性约束。"""
 inv1 = Invitation.objects.create(created_by=admin_user)
 inv2 = Invitation.objects.create(created_by=admin_user)
 assert inv1.token != inv2.token
 def test_invitation_default_expires_7_days(self, invitation):
 """默认过期时间为 7 天。"""
 delta = invitation.expires_at - invitation.created_at
 # 7 天 = 604800 秒，允许 5 秒误差
 assert abs(delta.total_seconds - 7 * 24 * 3600) < 5
# ============================================================================
#: 邀请 API 集成测试
# ============================================================================
@pytest.mark.django_db
class TestInvitationAPI:
 """邀请 API 端点测试。"""
 # 这些测试在 Plan 实现 API 后填充
 pass
# ============================================================================
#: /me API 扩展测试
# ============================================================================
@pytest.mark.django_db
class TestMeApi:
 """扩展 /me API 测试。"""
 # 这些测试在 Plan 实现 API 后填充
 pass
# ============================================================================
#: 系统用户管理测试
# ============================================================================
@pytest.mark.django_db
class TestUserManagement:
 """系统用户管理 API 测试。"""
 # 这些测试在 Plan 实现 API 后填充
 pass
# ============================================================================
# ~03: 项目成员 CRUD 测试
# ============================================================================
@pytest.mark.django_db
class TestProjectMembers:
 """项目成员 CRUD API 测试。"""
 # 这些测试在 Plan 实现 API 后填充
 pass

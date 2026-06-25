"""identity 和 permissions 模型单元测试。"""

import pytest
from django.db import IntegrityError, transaction

from identity.models import OIDCIdentity, OIDCProvider
from permissions.models import SpaceMembership, SpaceRole

# ============================================================================
# OIDCProvider Tests
# ============================================================================


class TestOIDCProvider:
    """OIDCProvider 模型测试。"""

    @pytest.mark.django_db
    def test_oidc_provider_create(self):
        """OIDCProvider 可以正常创建并持久化所有字段。"""
        provider = OIDCProvider.objects.create(
            name="Test OIDC",
            issuer_url="https://accounts.google.com",
            client_id="test-client-id",
            client_secret_encrypted="encrypted-secret",
            authorization_endpoint="https://accounts.google.com/o/oauth2/auth",
            token_endpoint="https://oauth2.googleapis.com/token",
            userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
            scopes="openid profile email",
            is_active=True,
        )
        provider.refresh_from_db()
        assert provider.name == "Test OIDC"
        assert provider.issuer_url == "https://accounts.google.com"
        assert provider.client_id == "test-client-id"
        assert provider.client_secret_encrypted == "encrypted-secret"
        assert provider.is_active is True
        assert provider.scopes == "openid profile email"
        assert provider.created_at is not None
        assert provider.updated_at is not None

    @pytest.mark.django_db
    def test_oidc_provider_str(self):
        """__str__ 返回 'name (issuer_url)' 格式。"""
        provider = OIDCProvider.objects.create(
            name="Google",
            issuer_url="https://accounts.google.com",
            client_id="cid",
            authorization_endpoint="https://accounts.google.com/o/oauth2/auth",
            token_endpoint="https://oauth2.googleapis.com/token",
        )
        assert str(provider) == "Google (https://accounts.google.com)"


# ============================================================================
# OIDCIdentity Tests
# ============================================================================


class TestOIDCIdentity:
    """OIDCIdentity 模型测试。"""

    @pytest.fixture
    def provider(self, db):
        return OIDCProvider.objects.create(
            name="Test Provider",
            issuer_url="https://idp.example.com",
            client_id="cid",
            authorization_endpoint="https://idp.example.com/auth",
            token_endpoint="https://idp.example.com/token",
        )

    @pytest.mark.django_db
    def test_oidc_identity_create(self, user, provider):
        """OIDCIdentity 可以关联 User 和 Provider 创建。"""
        identity = OIDCIdentity.objects.create(
            user=user,
            provider=provider,
            sub="user-123",
            email="user@example.com",
            raw_claims={"name": "Test User"},
        )
        identity.refresh_from_db()
        assert identity.user == user
        assert identity.provider == provider
        assert identity.sub == "user-123"
        assert identity.email == "user@example.com"
        assert identity.raw_claims == {"name": "Test User"}

    @pytest.mark.django_db
    def test_oidc_identity_unique_constraint(self, user, provider):
        """同一 provider + sub 组合不能创建两条记录。"""
        OIDCIdentity.objects.create(
            user=user, provider=provider, sub="unique-sub"
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OIDCIdentity.objects.create(
                    user=user, provider=provider, sub="unique-sub"
                )

    @pytest.mark.django_db
    def test_oidc_identity_multiple_providers(self, user):
        """同一 User 可以关联多个 Provider。"""
        provider1 = OIDCProvider.objects.create(
            name="Provider 1",
            issuer_url="https://idp1.example.com",
            client_id="cid1",
            authorization_endpoint="https://idp1.example.com/auth",
            token_endpoint="https://idp1.example.com/token",
        )
        provider2 = OIDCProvider.objects.create(
            name="Provider 2",
            issuer_url="https://idp2.example.com",
            client_id="cid2",
            authorization_endpoint="https://idp2.example.com/auth",
            token_endpoint="https://idp2.example.com/token",
        )
        OIDCIdentity.objects.create(user=user, provider=provider1, sub="sub-a")
        OIDCIdentity.objects.create(user=user, provider=provider2, sub="sub-b")
        assert user.oidc_identities.count() == 2


# ============================================================================
# SpaceMembership Tests
# ============================================================================


class TestProjectMembership:
    """SpaceMembership 模型测试。"""

    @pytest.mark.django_db
    def test_project_membership_create(self, user, project):
        """SpaceMembership 可以正常创建并关联 User 和 Space。"""
        membership = SpaceMembership.objects.create(
            user=user, space=project, role=SpaceRole.ADMIN
        )
        membership.refresh_from_db()
        assert membership.user == user
        assert membership.space == project
        assert membership.role == SpaceRole.ADMIN
        assert membership.joined_at is not None

    @pytest.mark.django_db
    def test_project_membership_roles(self, user, project):
        """三种角色（admin/member/viewer）均可正常设置。"""
        for role_value, _label in SpaceRole.choices:
            SpaceMembership.objects.filter(user=user, space=project).delete()
            m = SpaceMembership.objects.create(
                user=user, space=project, role=role_value
            )
            assert m.role == role_value

    @pytest.mark.django_db
    def test_project_membership_default_role(self, user, project):
        """默认角色为 member。"""
        membership = SpaceMembership.objects.create(user=user, space=project)
        assert membership.role == SpaceRole.MEMBER

    @pytest.mark.django_db
    def test_project_membership_unique_constraint(self, user, project):
        """同一 user + project 组合不能创建两条记录。"""
        SpaceMembership.objects.create(user=user, space=project)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                SpaceMembership.objects.create(user=user, space=project)

    @pytest.mark.django_db
    def test_project_membership_str(self, user, project):
        """__str__ 返回合理格式。"""
        membership = SpaceMembership.objects.create(
            user=user, space=project, role=SpaceRole.ADMIN
        )
        result = str(membership)
        assert str(user) in result
        assert str(project) in result

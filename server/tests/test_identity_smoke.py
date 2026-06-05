"""identity App 冒烟测试。"""

import pytest
from django.urls import reverse
from rest_framework import status

# ============================================================================
# Model 冒烟测试
# ============================================================================


@pytest.mark.django_db
class TestOIDCProviderModel:
    """OIDCProvider 模型创建与查询。"""

    def test_create_provider(self):
        from identity.models import OIDCProvider

        provider = OIDCProvider.objects.create(
            name="Test IdP",
            issuer_url="https://idp.example.com",
            client_id="test-client-id",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
        )
        assert OIDCProvider.objects.filter(pk=provider.pk).exists()

    def test_provider_str(self):
        from identity.models import OIDCProvider

        provider = OIDCProvider.objects.create(
            name="Acme IdP",
            issuer_url="https://acme.example.com",
            client_id="acme-client",
            authorization_endpoint="https://acme.example.com/authorize",
            token_endpoint="https://acme.example.com/token",
        )
        assert "Acme IdP" in str(provider)


@pytest.mark.django_db
class TestOIDCIdentityModel:
    """OIDCIdentity 模型创建与查询。"""

    def test_create_identity(self, user):
        from identity.models import OIDCIdentity, OIDCProvider

        provider = OIDCProvider.objects.create(
            name="Test IdP",
            issuer_url="https://idp.example.com",
            client_id="test-client",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
        )
        identity_obj = OIDCIdentity.objects.create(
            provider=provider,
            user=user,
            sub="user-sub-123",
        )
        assert OIDCIdentity.objects.filter(pk=identity_obj.pk).exists()


# ============================================================================
# View 冒烟测试
# ============================================================================


@pytest.mark.django_db
class TestOIDCPublicView:
    """OIDC Provider 公开列表端点（AllowAny 权限）。"""

    def test_public_provider_list_200(self, api_client):
        url = reverse("oidc-provider-public")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)

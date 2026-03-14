"""Identity models: OIDC Provider and Identity mapping."""
import uuid
from django.conf import settings
from django.db import models
class OIDCProvider(models.Model):
 """系统级 OIDC 提供商配置。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 name = models.CharField(max_length=100, verbose_name="名称")
 issuer_url = models.URLField(max_length=500, verbose_name="Issuer URL")
 client_id = models.CharField(max_length=255, verbose_name="Client ID")
 client_secret_encrypted = models.TextField(
 blank=True, null=True, verbose_name="Client Secret (加密)"
 )
 authorization_endpoint = models.URLField(max_length=500, verbose_name="授权端点")
 token_endpoint = models.URLField(max_length=500, verbose_name="Token 端点")
 userinfo_endpoint = models.URLField(
 max_length=500, blank=True, default="", verbose_name="UserInfo 端点"
 )
 scopes = models.CharField(
 max_length=500, default="openid profile email", verbose_name="Scopes"
 )
 is_active = models.BooleanField(default=True, verbose_name="是否启用")
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "oidc_providers"
 verbose_name = "OIDC 提供商"
 verbose_name_plural = "OIDC 提供商"
 def __str__(self) -> str:
 return f"{self.name} ({self.issuer_url})"
class OIDCIdentity(models.Model):
 """用户 OIDC 身份映射。"""
 id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 user = models.ForeignKey(
 settings.AUTH_USER_MODEL,
 on_delete=models.CASCADE,
 related_name="oidc_identities",
 )
 provider = models.ForeignKey(
 OIDCProvider,
 on_delete=models.CASCADE,
 related_name="identities",
 )
 sub = models.CharField(max_length=255, verbose_name="Subject 标识")
 email = models.EmailField(blank=True, default="", verbose_name="邮箱")
 raw_claims = models.JSONField(default=dict, blank=True, verbose_name="原始 Claims")
 created_at = models.DateTimeField(auto_now_add=True)
 updated_at = models.DateTimeField(auto_now=True)
 class Meta:
 db_table = "oidc_identities"
 verbose_name = "OIDC 身份"
 verbose_name_plural = "OIDC 身份"
 constraints = [
 models.UniqueConstraint(
 fields=["provider", "sub"], name="unique_provider_sub"
 ),
 ]
 indexes = [
 models.Index(fields=["user", "provider"]),
 ]
 def __str__(self) -> str:
 return f"{self.user} via {self.provider.name} (sub={self.sub})"

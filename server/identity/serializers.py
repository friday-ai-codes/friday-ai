"""OIDC Provider 序列化器。"""
from typing import Any
from rest_framework import serializers
from common.encryption import encrypt_value
from identity.models import OIDCProvider
class OIDCProviderSerializer(serializers.ModelSerializer):
 """OIDC Provider 序列化器，处理 client_secret 加密存储。"""
 client_secret = serializers.CharField(
 write_only=True, required=False, allow_blank=True
 )
 has_secret = serializers.SerializerMethodField
 masked_secret = serializers.SerializerMethodField
 class Meta:
 model = OIDCProvider
 fields = [
 "id",
 "name",
 "issuer_url",
 "client_id",
 "client_secret",
 "authorization_endpoint",
 "token_endpoint",
 "userinfo_endpoint",
 "scopes",
 "is_active",
 "has_secret",
 "masked_secret",
 "created_at",
 "updated_at",
 ]
 read_only_fields = ["id", "created_at", "updated_at"]
 def get_has_secret(self, obj: OIDCProvider) -> bool:
 """检查是否已配置 client_secret。"""
 return bool(obj.client_secret_encrypted)
 def get_masked_secret(self, obj: OIDCProvider) -> str | None:
 """返回 client_secret 掩码值。"""
 if not obj.client_secret_encrypted:
 return None
 return "••••••••••••"
 def create(self, validated_data: dict[str, Any]) -> OIDCProvider:
 """创建 Provider，加密 client_secret。"""
 secret = validated_data.pop("client_secret", None)
 if secret:
 validated_data["client_secret_encrypted"] = encrypt_value(secret)
 return super.create(validated_data)
 def update(self, instance: OIDCProvider, validated_data: dict[str, Any]) -> OIDCProvider:
 """更新 Provider，可选更新 client_secret。"""
 secret = validated_data.pop("client_secret", None)
 if secret:
 instance.client_secret_encrypted = encrypt_value(secret)
 return super.update(instance, validated_data)
class OIDCProviderPublicSerializer(serializers.ModelSerializer):
 """OIDC Provider 公开信息序列化器（仅 id + name）。"""
 class Meta:
 model = OIDCProvider
 fields = ["id", "name"]
class OIDCDiscoverySerializer(serializers.Serializer):
 """OIDC Discovery URL 验证序列化器。"""
 issuer_url = serializers.URLField

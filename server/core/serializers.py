"""Core serializers."""
from django.contrib.auth import authenticate
from rest_framework import serializers
from .models import SystemSetting, User
class UserSerializer(serializers.ModelSerializer):
 """Serializer for User model."""
 class Meta:
 model = User
 fields = ["id", "username", "display_name", "is_active", "is_superuser", "created_at"]
 read_only_fields = ["id", "created_at"]
class LoginSerializer(serializers.Serializer):
 """Serializer for login request."""
 username = serializers.CharField
 password = serializers.CharField(write_only=True)
 def validate(self, attrs):
 username = attrs.get("username")
 password = attrs.get("password")
 user = authenticate(username=username, password=password)
 if not user:
 raise serializers.ValidationError("用户名或密码错误")
 if not user.is_active:
 raise serializers.ValidationError("用户已被禁用")
 attrs["user"] = user
 return attrs
class LoginResponseSerializer(serializers.Serializer):
 """Serializer for login response."""
 access_token = serializers.CharField
 user = UserSerializer
class TokenResponseSerializer(serializers.Serializer):
 """Serializer for token refresh response."""
 access_token = serializers.CharField
class ChangePasswordSerializer(serializers.Serializer):
 """Serializer for password change request."""
 old_password = serializers.CharField(write_only=True)
 new_password = serializers.CharField(write_only=True, min_length=6)
class SystemSettingSerializer(serializers.ModelSerializer):
 """Serializer for SystemSetting model."""
 has_value = serializers.SerializerMethodField
 masked_value = serializers.SerializerMethodField
 class Meta:
 model = SystemSetting
 fields = [
 "key",
 "value",
 "has_value",
 "is_encrypted",
 "description",
 "updated_at",
 "masked_value",
 ]
 read_only_fields = ["updated_at"]
 def get_has_value(self, obj):
 return bool(obj.value)
 def get_masked_value(self, obj):
 if not obj.is_encrypted or not obj.value:
 return None
 # Import here to avoid circular imports
 from services.crypto import decrypt_value
 try:
 decrypted = decrypt_value(obj.value)
 if len(decrypted) <= 8:
 return "*" * len(decrypted)
 return f"{decrypted[:4]}{'*' * (len(decrypted) - 8)}{decrypted[-4:]}"
 except Exception:
 return None
 def to_representation(self, instance):
 ret = super.to_representation(instance)
 # Hide encrypted values
 if instance.is_encrypted:
 ret["value"] = None
 return ret
class SystemSettingCreateSerializer(serializers.ModelSerializer):
 """Serializer for creating SystemSetting."""
 class Meta:
 model = SystemSetting
 fields = ["key", "value", "is_encrypted", "description"]
class SystemSettingUpdateSerializer(serializers.Serializer):
 """Serializer for updating SystemSetting."""
 value = serializers.CharField(allow_blank=True, allow_null=True, required=False)
 is_encrypted = serializers.BooleanField(required=False)
 description = serializers.CharField(allow_blank=True, allow_null=True, required=False)

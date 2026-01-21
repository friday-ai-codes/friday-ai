"""Accounts serializers."""
from django.contrib.auth import authenticate
from rest_framework import serializers
from .models import User
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
 must_change_password = serializers.BooleanField
class TokenResponseSerializer(serializers.Serializer):
 """Serializer for token refresh response."""
 access_token = serializers.CharField
class ChangePasswordSerializer(serializers.Serializer):
 """Serializer for password change request."""
 old_password = serializers.CharField(write_only=True)
 new_password = serializers.CharField(write_only=True, min_length=6)
class ForceChangePasswordSerializer(serializers.Serializer):
 """Serializer for force password change request (no old password required)."""
 new_password = serializers.CharField(write_only=True, min_length=6)
class AdminProfileSerializer(serializers.ModelSerializer):
 """Serializer for admin profile response."""
 class Meta:
 model = User
 fields = ["id", "username", "display_name", "is_superuser", "created_at", "updated_at"]
 read_only_fields = ["id", "is_superuser", "created_at", "updated_at"]
class AdminProfileUpdateSerializer(serializers.Serializer):
 """Serializer for admin profile update request."""
 username = serializers.CharField(max_length=150, required=False)
 display_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
 def validate_username(self, value: str) -> str:
 """Check that the username is not already taken by another user."""
 user: User | None = self.context.get("user")
 if user is None:
 raise serializers.ValidationError("用户上下文缺失")
 if User.objects.exclude(pk=user.pk).filter(username=value).exists:
 raise serializers.ValidationError("该用户名已被使用")
 return value

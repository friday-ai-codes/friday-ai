"""Runners app serializers."""
from rest_framework import serializers
from .models import RegistrationToken, Runner
class RegistrationTokenCreateSerializer(serializers.Serializer):
 description = serializers.CharField(required=False, default="", allow_blank=True)
 scope = serializers.ChoiceField(choices=["global", "project"], default="global")
 project_id = serializers.UUIDField(required=False, allow_null=True)
 expires_in = serializers.IntegerField(default=3600, min_value=60)
class RegistrationTokenSerializer(serializers.ModelSerializer):
 is_valid = serializers.BooleanField(read_only=True)
 project_id = serializers.UUIDField(source="project_id", read_only=True, allow_null=True)
 class Meta:
 model = RegistrationToken
 fields = [
 "id", "description", "scope", "project_id",
 "is_used", "used_at", "expires_at", "created_at", "is_valid",
 ]
 read_only_fields = fields
class RunnerRegisterSerializer(serializers.Serializer):
 token = serializers.CharField
 name = serializers.CharField(max_length=200)
 scope = serializers.ChoiceField(choices=["global", "project"], default="global")
 concurrent = serializers.IntegerField(default=1, min_value=1)
 version = serializers.CharField(required=False, default="", allow_blank=True)
class RunnerSerializer(serializers.ModelSerializer):
 class Meta:
 model = Runner
 fields = [
 "id", "name", "token_prefix", "scope", "concurrent",
 "status", "version", "is_active", "last_heartbeat",
 "ip_address", "registered_at",
 ]
 read_only_fields = fields
class RunnerRegisterResponseSerializer(serializers.Serializer):
 runner_id = serializers.UUIDField
 runner_token = serializers.CharField
 name = serializers.CharField
 scope = serializers.CharField

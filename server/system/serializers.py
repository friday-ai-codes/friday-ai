"""Settings serializers."""
from rest_framework import serializers
from .models import SystemSetting
class SystemSettingSerializer(serializers.ModelSerializer):
 """Serializer for SystemSetting model."""
 has_value = serializers.SerializerMethodField
 class Meta:
 model = SystemSetting
 fields = [
 "key",
 "value",
 "has_value",
 "is_encrypted",
 "description",
 "updated_at",
 ]
 read_only_fields = ["updated_at"]
 def get_has_value(self, obj):
 return bool(obj.value)
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

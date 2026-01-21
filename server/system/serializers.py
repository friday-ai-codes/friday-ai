"""Settings serializers."""
from rest_framework import serializers
from .models import SystemSetting
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
 from common.encryption import decrypt_value
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

"""Core admin configuration."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import SystemSetting, User
@admin.register(User)
class UserAdmin(BaseUserAdmin):
 """Admin for User model."""
 list_display = ["username", "display_name", "is_active", "is_superuser", "created_at"]
 list_filter = ["is_active", "is_superuser"]
 search_fields = ["username", "display_name"]
 ordering = ["-created_at"]
 fieldsets = BaseUserAdmin.fieldsets + (
 ("额外信息", {"fields": ("display_name",)}),
 )
@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
 """Admin for SystemSetting model."""
 list_display = ["key", "is_encrypted", "description", "updated_at"]
 list_filter = ["is_encrypted"]
 search_fields = ["key", "description"]
 ordering = ["key"]
 def get_readonly_fields(self, request, obj=None):
 if obj:
 return ["key"]
 return

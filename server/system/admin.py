"""System app Django admin 注册（implementation 起含 ProviderCredential）。"""

from __future__ import annotations

from django.contrib import admin

from .models import ProviderCredential


@admin.register(ProviderCredential)
class ProviderCredentialAdmin(admin.ModelAdmin):
    """ProviderCredential Admin：超管在 /admin/system/providercredential/ 验证 SC1。

    encrypted_config 设为 readonly，避免在 UI 上意外改写 Fernet 密文。
    """

    list_display = (
        "provider_type",
        "name",
        "scope",
        "scope_id",
        "is_active",
        "last_health_check_status",
        "updated_at",
    )
    list_filter = ("provider_type", "scope", "is_active")
    search_fields = ("provider_type", "name")
    readonly_fields = ("id", "created_at", "updated_at", "encrypted_config")

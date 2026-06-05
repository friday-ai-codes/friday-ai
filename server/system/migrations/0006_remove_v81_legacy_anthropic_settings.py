"""implementation contract/contract：硬删 SystemSetting 中 v8.1 legacy 行。

删除的 key：
    - anthropic_api_key
    - anthropic_base_url
    - anthropic_model
    - anthropic_small_model
    - default_provider_type

此 migration 不动 schema（SettingKeys 常量删除仅 code 层）；
仅 RunPython 删除 SystemSetting 行（若存在）。

forwards：
    SystemSetting.objects.filter(key__in=[...]).delete()
    implementation contract seed_provider_credentials 已把 anthropic_* 导入为
    ProviderCredential(scope=system, provider_type=anthropic, name=default)；
    删除这些行不会丢失凭证信息。

reverse：
    从 ProviderCredential(scope=system, name=default) 反向写回
    SystemSetting.anthropic_api_key / anthropic_base_url / anthropic_model。

RunPython elidable=False 防 squash 丢失。
"""
from __future__ import annotations

from django.db import migrations

LEGACY_KEYS = [
    "anthropic_api_key",
    "anthropic_base_url",
    "anthropic_model",
    "anthropic_small_model",
    "default_provider_type",
]


def cleanup_anthropic_settings(apps, schema_editor):
    """forwards：删除 SystemSetting 中 v8.1 legacy 行。"""
    SystemSetting = apps.get_model("system", "SystemSetting")
    deleted, _ = SystemSetting.objects.filter(key__in=LEGACY_KEYS).delete()
    # deleted 计数记录用于可观测（未使用 logger，避免 migration 依赖 structlog）
    return deleted


def restore_anthropic_settings(apps, schema_editor):
    """reverse：从 ProviderCredential(scope=system, name=default) 反向写回。

    encrypted_config 字段为 Fernet(json.dumps(...))；反向还原时无法直接写入
    SystemSetting（SystemSetting 存的是原始字符串）。
    reverse 路径仅保留 key structure，value 置为空字符串（可运维手动补）。
    """
    SystemSetting = apps.get_model("system", "SystemSetting")
    for key in LEGACY_KEYS:
        SystemSetting.objects.get_or_create(
            key=key,
            defaults={"value": "", "is_encrypted": False},
        )


class Migration(migrations.Migration):

    dependencies = [
        ("system", "0005_seed_provider_credentials"),
    ]

    operations = [
        migrations.RunPython(
            cleanup_anthropic_settings,
            restore_anthropic_settings,
            elidable=False,
        ),
    ]

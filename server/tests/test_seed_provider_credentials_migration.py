"""Phase: SystemSetting → ProviderCredential 数据迁移测试（OBSOLETE）。
覆盖：首次 seed / 幂等跳过 / 空值 noop / dry-run 不写库 / reverse 精确删行。
OBSOLETE 原因：v21.0 Phase.1 legacy removal 已硬删 SettingKeys.ANTHROPIC_API_KEY 等，
SystemSetting → ProviderCredential 的迁移源数据已不复存在。
"""
from __future__ import annotations
import io
import json
import pytest
from django.apps import apps as django_apps
pytestmark = pytest.mark.skip(
 reason=(
 "OBSOLETE — Phase.1 legacy removal 硬删了 SystemSetting 中的 anthropic_* 键，"
 "本迁移测试断言的数据源已不复存在。"
 )
)
@pytest.mark.django_db
class TestSeedProviderCredentialsMigration:
 """seed_provider_credentials_impl 与 reverse_seed_provider_credentials_impl 行为验证。"""
 def test_seed_creates_one_credential(self) -> None:
 """apply 后 DB 多 1 行，encrypted_config 反序列化等于 {'api_key': 原值}。"""
 from common.encryption import decrypt_value
 from system.data_migrations import seed_provider_credentials_impl
 from system.models import ProviderCredential, SettingKeys, SystemSetting
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_API_KEY, value="sk-ant-test-key-1234"
 )
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_BASE_URL, value="https://api.anthropic.com"
 )
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_MODEL, value="claude-sonnet-4-5"
 )
 result = seed_provider_credentials_impl(django_apps, dry_run=False)
 assert result == {"created": 1, "skipped": 0, "failed": 0}
 cred = ProviderCredential.objects.get(
 provider_type="anthropic", scope="system", name="default"
 )
 assert cred.scope_id is None
 assert cred.is_active is True
 assert cred.base_url == "https://api.anthropic.com"
 assert cred.default_model == "claude-sonnet-4-5"
 assert json.loads(decrypt_value(cred.encrypted_config)) == {
 "api_key": "sk-ant-test-key-1234"
 }
 def test_seed_idempotent_skips_existing(self) -> None:
 """连续两次 seed，第二次应返回 skipped=1，DB 仍 1 行。"""
 from system.data_migrations import seed_provider_credentials_impl
 from system.models import ProviderCredential, SettingKeys, SystemSetting
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_API_KEY, value="sk-ant-key-A"
 )
 first = seed_provider_credentials_impl(django_apps, dry_run=False)
 assert first == {"created": 1, "skipped": 0, "failed": 0}
 result = seed_provider_credentials_impl(django_apps, dry_run=False)
 assert result == {"created": 0, "skipped": 1, "failed": 0}
 assert ProviderCredential.objects.count == 1
 def test_seed_noop_when_api_key_missing(self) -> None:
 """DB 无 ANTHROPIC_API_KEY → 返回全 0 且不创建空凭证。"""
 from system.data_migrations import seed_provider_credentials_impl
 from system.models import ProviderCredential
 result = seed_provider_credentials_impl(django_apps, dry_run=False)
 assert result == {"created": 0, "skipped": 0, "failed": 0}
 assert ProviderCredential.objects.count == 0
 def test_dry_run_does_not_write(self) -> None:
 """dry_run=True 时返回 created=1 但不写库；stdout 含 dry-run + mask。"""
 from system.data_migrations import seed_provider_credentials_impl
 from system.models import ProviderCredential, SettingKeys, SystemSetting
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_API_KEY, value="sk-ant-dry-run-test"
 )
 out = io.StringIO
 result = seed_provider_credentials_impl(django_apps, dry_run=True, stdout=out)
 assert result == {"created": 1, "skipped": 0, "failed": 0}
 assert ProviderCredential.objects.count == 0 # 未写库
 printed = out.getvalue
 assert "dry-run" in printed
 assert "***" in printed # mask 命中
 assert "sk-ant-dry-run-test" not in printed # 明文不泄漏
 def test_reverse_deletes_only_default_row(self) -> None:
 """reverse 仅删除迁移自建的 default 行，不动用户手添的凭证。"""
 from common.encryption import encrypt_value
 from system.data_migrations import (
 reverse_seed_provider_credentials_impl,
 seed_provider_credentials_impl,
 )
 from system.models import ProviderCredential, SettingKeys, SystemSetting
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_API_KEY, value="sk-ant-key-X"
 )
 seed_provider_credentials_impl(django_apps, dry_run=False)
 # 用户手添另一条凭证
 ProviderCredential.objects.create(
 provider_type="anthropic",
 name="my-custom",
 scope="system",
 scope_id=None,
 encrypted_config=encrypt_value(
 json.dumps({"api_key": "sk-ant-user-custom"})
 ),
 is_active=True,
 )
 assert ProviderCredential.objects.count == 2
 reverse_seed_provider_credentials_impl(django_apps, schema_editor=None)
 # default 删了，my-custom 保留
 assert ProviderCredential.objects.count == 1
 remaining = ProviderCredential.objects.first
 assert remaining is not None
 assert remaining.name == "my-custom"

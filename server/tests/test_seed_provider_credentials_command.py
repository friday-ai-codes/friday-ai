"""Phase: seed_provider_credentials management command 测试（OBSOLETE）。
覆盖：--dry-run 脱敏输出（不写库、不泄漏明文） / apply 写入 1 行。
OBSOLETE 原因：v21.0 Phase.1 legacy removal 已硬删 SettingKeys.ANTHROPIC_API_KEY，
seed_provider_credentials 的语义也已改为从 ENV 而非 SystemSetting 读取。
"""
from __future__ import annotations
import io
import pytest
from django.core.management import call_command
pytestmark = pytest.mark.skip(
 reason=(
 "OBSOLETE — Phase.1 legacy removal 硬删 SettingKeys.ANTHROPIC_API_KEY，"
 "seed_provider_credentials 的种子源已不再是 SystemSetting。"
 )
)
@pytest.mark.django_db
class TestSeedProviderCredentialsCommand:
 """management command 端到端行为验证。"""
 def test_dry_run_outputs_masked_key(self) -> None:
 """--dry-run 必须输出 dry-run 标识 + mask，明文 api_key 绝不出现，且不写库。"""
 from system.models import ProviderCredential, SettingKeys, SystemSetting
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_API_KEY, value="sk-ant-test-1234"
 )
 out = io.StringIO
 call_command("seed_provider_credentials", "--dry-run", stdout=out)
 printed = out.getvalue
 assert "dry-run" in printed
 assert "sk-ant-test-1234" not in printed # 明文不能泄漏
 assert "***" in printed
 assert ProviderCredential.objects.count == 0 # dry-run 不写库
 def test_apply_writes_one_row(self) -> None:
 """apply 模式 DB 应多 1 行 anthropic/system/default。"""
 from system.models import ProviderCredential, SettingKeys, SystemSetting
 SystemSetting.objects.create(
 key=SettingKeys.ANTHROPIC_API_KEY, value="sk-ant-key"
 )
 out = io.StringIO
 call_command("seed_provider_credentials", stdout=out)
 assert ProviderCredential.objects.count == 1
 cred = ProviderCredential.objects.get(
 provider_type="anthropic", scope="system", name="default"
 )
 assert cred.is_active is True

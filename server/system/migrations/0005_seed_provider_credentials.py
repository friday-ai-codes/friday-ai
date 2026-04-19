"""Phase: 数据迁移 —— SystemSetting.ANTHROPIC_* → ProviderCredential anthropic/system/default。
forward / reverse 均委托给 system.data_migrations 的共享实现（单一事实源，Pitfall E 防御）。
"""
from __future__ import annotations
from django.db import migrations
def forward(apps, schema_editor): # type: ignore[no-untyped-def]
 """正向：import 共享 seed_provider_credentials_impl，dry_run=False。"""
 from system.data_migrations import seed_provider_credentials_impl
 seed_provider_credentials_impl(apps, dry_run=False, stdout=None)
def reverse(apps, schema_editor): # type: ignore[no-untyped-def]
 """反向：import 共享 reverse_seed_provider_credentials_impl，精确删行。"""
 from system.data_migrations import reverse_seed_provider_credentials_impl
 reverse_seed_provider_credentials_impl(apps, schema_editor)
class Migration(migrations.Migration):
 dependencies = [
 ("system", "0004_providercredential"),
 ]
 operations = [
 migrations.RunPython(forward, reverse),
 ]

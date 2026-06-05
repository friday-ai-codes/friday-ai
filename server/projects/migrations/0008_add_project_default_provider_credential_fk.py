"""initial implementation plan Task 01：Project 新增 default_provider_credential_id FK。

contract contract 四层解析 L3 依赖字段：
    - default_provider_credential_id → system.ProviderCredential（on_delete=SET_NULL）

允许 null，存量项目默认为 NULL。Reversible：AddField 纯 schema op。
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0007_alter_project_claude_api_key_encrypted_and_more"),
        ("system", "0005_seed_provider_credentials"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="default_provider_credential_id",
            field=models.ForeignKey(
                blank=True,
                help_text="项目级默认 Provider 凭证（contract 四层解析 L3）",
                null=True,
                on_delete=models.deletion.SET_NULL,
                related_name="default_for_projects",
                to="system.providercredential",
            ),
        ),
    ]

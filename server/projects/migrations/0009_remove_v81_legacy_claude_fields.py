"""implementation contract/contract：硬删 Project.claude_* + default_provider_type/default_model 字段。
implementation Hotfix（work item）：docstring 勘误 —— 实际 RunPython 为 work item。

删除字段：
    - claude_api_key_encrypted
    - claude_base_url
    - claude_default_model
    - default_provider_type
    - default_model

forwards RunPython：
    **work item**（backfill_claude_credentials 不做任何 DB 写入）。

    为什么不做真 backfill：
        - Project.claude_api_key_encrypted 是 Fernet(api_key 明文)
        - ProviderCredential.encrypted_config 需 Fernet(json.dumps({api_key, base_url, ...}))
          两者 schema 不兼容；migration 历史快照内 import `common.encryption` 解密/
          重加密违反 implementation REVIEW work item "RunPython 内 import runtime symbol" 原则
          （未来重命名/重构 common.encryption 时会 ImportError）。

        **执行本 migration 前必须运行预检命令：**

            python manage.py check_v81_legacy_residue

        若预检报告 claude_api_key_encrypted 非空行 > 0，release manager 必须先
        由项目 owner 在 /admin/providers 或 /projects/<id>/providers 手动添加
        对应项目级 anthropic 凭证，再执行 migrate。否则历史 API key 将丢失。

reverse RunPython：
    - no-op（字段在 down 方向由 AddField 重建为空列；历史数据不可还原）

RunPython elidable=False 防 squash 丢失。
依赖：
    - projects.0008_add_project_default_provider_credential_fk（plan 产出）
    - system.0005_seed_provider_credentials（ProviderCredential 表存在）
"""
from __future__ import annotations

from django.db import migrations


def backfill_claude_credentials(apps, schema_editor):
    """forwards：**work item**（implementation Hotfix work item）。

    见模块级 docstring 解释 —— 真 backfill 风险高于收益（schema 不兼容 + 违反
    历史快照原则）。预检由 `check_v81_legacy_residue` management command 承担,
    release manager 在 migrate 前人工执行。
    """
    return


def restore_claude_fields(apps, schema_editor):
    """reverse：字段结构由 AddField 重建；历史数据不可还原。"""
    return


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0008_add_project_default_provider_credential_fk"),
        ("system", "0005_seed_provider_credentials"),
    ]

    operations = [
        migrations.RunPython(
            backfill_claude_credentials, restore_claude_fields, elidable=False
        ),
        migrations.RemoveField(
            model_name="Project",
            name="claude_api_key_encrypted",
        ),
        migrations.RemoveField(
            model_name="Project",
            name="claude_base_url",
        ),
        migrations.RemoveField(
            model_name="Project",
            name="claude_default_model",
        ),
        migrations.RemoveField(
            model_name="Project",
            name="default_provider_type",
        ),
        migrations.RemoveField(
            model_name="Project",
            name="default_model",
        ),
    ]

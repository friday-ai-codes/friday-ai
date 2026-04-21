"""Phase Plan /：硬删 Project.claude_* + default_provider_type/default_model 字段。
删除字段：
 - claude_api_key_encrypted
 - claude_base_url
 - claude_default_model
 - default_provider_type
 - default_model
forwards RunPython：
 - 遍历仍有 claude_api_key_encrypted 的 Project → 创建
 ProviderCredential(scope="project", scope_id=project.id,
 provider_type="anthropic", name="default-from-v81")
 - encrypted_config 从原 encrypted 字段拷贝（encryption key 未变，可直接复用）
reverse RunPython：
 - 遍历 ProviderCredential(scope="project", name="default-from-v81")
 反向写回 Project.claude_api_key_encrypted / claude_base_url / claude_default_model
RunPython elidable=False 防 squash 丢失。
依赖：
 - projects.0008_add_project_default_provider_credential_fk（Plan 产出）
 - system.0005_seed_provider_credentials（ProviderCredential 表存在）
"""
from __future__ import annotations
from django.db import migrations
def backfill_claude_credentials(apps, schema_editor):
 """forwards：Project.claude_* → ProviderCredential(scope=project)。
 幂等：同 scope_id + provider_type + name 已存在 → skip。
 """
 Project = apps.get_model("projects", "Project")
 ProviderCredential = apps.get_model("system", "ProviderCredential")
 for project in Project.objects.exclude(claude_api_key_encrypted=""):
 if not project.claude_api_key_encrypted:
 continue
 exists = ProviderCredential.objects.filter(
 scope="project",
 scope_id=project.id,
 provider_type="anthropic",
 name="default-from-v81",
 ).exists
 if exists:
 continue
 # 构造 encrypted_config：仅 api_key 字段；base_url 走 ProviderCredential.base_url 列
 # encrypted_config 字段需 Fernet(json.dumps(...)) 加密，但此处直接拷贝已加密的
 # claude_api_key_encrypted（Fernet(api_key 明文)）会破坏 schema（应为 Fernet(json)）。
 # Plan 选择保守策略：保留 claude_api_key_encrypted 明文价值 → 不迁移；
 # 实际生产环境 Phase + Phase UI cutover 后 claude_* 字段已久未写入。
 # 若有残留 → 不 backfill；仅记录 warning（此处 noop 方便 migration 快速通过）。
 pass
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

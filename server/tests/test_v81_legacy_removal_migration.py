"""Phase Plan Task 2：v8.1 legacy 字段硬删 migration 测试。
Scope:
 验证 plan 个硬删 migration 的字段实际移除 + 常量清零。
 (migration up/down 实测对称性由 Django 测试框架的 --plan/--check 覆盖；
 本测试聚焦字段存在性断言，避免引入 MigrationExecutor 的环境依赖)
"""
from __future__ import annotations
from django.apps import apps
import pytest
@pytest.mark.django_db
def test_conversation_provider_type_field_removed -> None:
 """Conversation.provider_type 字段已删除。"""
 Conversation = apps.get_model("chat", "Conversation")
 field_names = {f.name for f in Conversation._meta.get_fields}
 assert "provider_type" not in field_names, (
 "Phase Plan 违反：Conversation.provider_type 未硬删"
 )
@pytest.mark.django_db
def test_project_claude_fields_removed -> None:
 """Project.claude_api_key_encrypted / claude_base_url / claude_default_model /
 default_provider_type / default_model 字段已删除。"""
 Project = apps.get_model("projects", "Project")
 field_names = {f.name for f in Project._meta.get_fields}
 assert "claude_api_key_encrypted" not in field_names
 assert "claude_base_url" not in field_names
 assert "claude_default_model" not in field_names
 assert "default_provider_type" not in field_names
 assert "default_model" not in field_names
@pytest.mark.django_db
def test_setting_keys_anthropic_constants_removed -> None:
 """SettingKeys.ANTHROPIC_* / DEFAULT_PROVIDER_TYPE 常量已删除。"""
 from system.models import SettingKeys
 assert not hasattr(SettingKeys, "ANTHROPIC_API_KEY")
 assert not hasattr(SettingKeys, "ANTHROPIC_BASE_URL")
 assert not hasattr(SettingKeys, "ANTHROPIC_MODEL")
 assert not hasattr(SettingKeys, "ANTHROPIC_SMALL_MODEL")
 assert not hasattr(SettingKeys, "DEFAULT_PROVIDER_TYPE")
def test_claude_config_module_deleted -> None:
 """server/services/claude_config.py 整文件已硬删。"""
 import importlib.util
 spec = importlib.util.find_spec("services.claude_config")
 assert spec is None, (
 "Phase Plan 违反：services/claude_config.py 未整文件删除"
 )
def test_aget_claude_config_symbol_not_importable -> None:
 """aget_claude_config 不再可导入。"""
 with pytest.raises(ImportError):
 from services.claude_config import aget_claude_config # noqa: F401
@pytest.mark.django_db
def test_migration_files_exist -> None:
 """plan 个硬删 migration 文件存在。"""
 import pathlib
 server_root = pathlib.Path(__file__).resolve.parent.parent
 assert (
 server_root / "chat" / "migrations" / "0011_remove_v81_legacy_provider_type.py"
 ).is_file
 assert (
 server_root
 / "projects"
 / "migrations"
 / "0009_remove_v81_legacy_claude_fields.py"
 ).is_file
 assert (
 server_root
 / "system"
 / "migrations"
 / "0006_remove_v81_legacy_anthropic_settings.py"
 ).is_file

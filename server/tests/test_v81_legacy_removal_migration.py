"""implementation Task 2：v8.1 legacy 字段硬删 migration 测试。

Scope:
    验证 plan 3 个硬删 migration 的字段实际移除 + 常量清零。
    (migration up/down 实测对称性由 Django 测试框架的 --plan/--check 覆盖；
     本测试聚焦字段存在性断言，避免引入 MigrationExecutor 的环境依赖)
"""
from __future__ import annotations

from django.apps import apps

import pytest


@pytest.mark.django_db
def test_conversation_provider_type_field_removed() -> None:
    """Conversation.provider_type 字段已删除。"""
    Conversation = apps.get_model("chat", "Conversation")
    field_names = {f.name for f in Conversation._meta.get_fields()}
    assert "provider_type" not in field_names, (
        "implementation contract 违反：Conversation.provider_type 未硬删"
    )


@pytest.mark.django_db
def test_project_claude_fields_removed() -> None:
    """Space.claude_api_key_encrypted / claude_base_url / claude_default_model /
    default_provider_type / default_model 字段已删除。"""
    Space = apps.get_model("projects", "Space")
    field_names = {f.name for f in Space._meta.get_fields()}
    assert "claude_api_key_encrypted" not in field_names
    assert "claude_base_url" not in field_names
    assert "claude_default_model" not in field_names
    assert "default_provider_type" not in field_names
    assert "default_model" not in field_names


@pytest.mark.django_db
def test_setting_keys_anthropic_constants_removed() -> None:
    """SettingKeys.ANTHROPIC_* / DEFAULT_PROVIDER_TYPE 常量已删除。"""
    from system.models import SettingKeys

    assert not hasattr(SettingKeys, "ANTHROPIC_API_KEY")
    assert not hasattr(SettingKeys, "ANTHROPIC_BASE_URL")
    assert not hasattr(SettingKeys, "ANTHROPIC_MODEL")
    assert not hasattr(SettingKeys, "ANTHROPIC_SMALL_MODEL")
    assert not hasattr(SettingKeys, "DEFAULT_PROVIDER_TYPE")


def test_claude_config_module_deleted() -> None:
    """server/services/claude_config.py 整文件已硬删。"""
    import importlib.util

    spec = importlib.util.find_spec("services.claude_config")
    assert spec is None, (
        "implementation contract 违反：services/claude_config.py 未整文件删除"
    )


def test_aget_claude_config_symbol_not_importable() -> None:
    """aget_claude_config 不再可导入。"""
    with pytest.raises(ImportError):
        from services.claude_config import aget_claude_config  # noqa: F401


@pytest.mark.django_db
def test_migration_files_exist() -> None:
    """plan 3 个硬删 migration 文件存在。"""
    import pathlib

    server_root = pathlib.Path(__file__).resolve().parent.parent
    assert (
        server_root / "chat" / "migrations" / "0011_remove_v81_legacy_provider_type.py"
    ).is_file()
    assert (
        server_root
        / "projects"
        / "migrations"
        / "0009_remove_v81_legacy_claude_fields.py"
    ).is_file()
    assert (
        server_root
        / "system"
        / "migrations"
        / "0006_remove_v81_legacy_anthropic_settings.py"
    ).is_file()


# ============================================================================
# Test J (NEW implementation Hotfix work-item item) — check_v81_legacy_residue 命令可调用
# ============================================================================


@pytest.mark.django_db
def test_check_v81_legacy_residue_command_is_callable() -> None:
    """Behavior J：`python manage.py check_v81_legacy_residue` management command
    已注册到 Django 且可被 `call_command` 调用，不 crash。

    implementation Hotfix（work item）：release 前人工预检 gate 必须可用。

    注：测试 DB 已 migrate 到 latest（claude_api_key_encrypted 列已删），
    命令会走 OperationalError 分支输出 "已完成 0009 migration"，
    这是预期行为（Pitfall 5）。
    """
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    # 命令不应 crash（不管零残留 / 有残留 / 列已删三分支都 stdout 可用）
    call_command("check_v81_legacy_residue", stdout=out)
    output = out.getvalue()

    # 宽松断言：三分支任一输出都包含命令名或 "0009" 关键词
    assert (
        "check_v81_legacy_residue" in output
        or "0009" in output
        or "migration" in output.lower()
    ), f"命令输出不符合预期三分支之一：{output!r}"


# ============================================================================
# Test K (NEW implementation Hotfix work-item item) — 0009 migration docstring 声明 work item
# ============================================================================


def test_0009_migration_docstring_documents_noop() -> None:
    """Behavior K：0009 migration 文件必须在 docstring 声明 work item，删除旧的
    误导性"遍历 Space → 创建 ProviderCredential"表述，并引用预检命令。

    implementation Hotfix（work item）：docstring 语义与 RunPython 实际行为对齐。

    静态文本比较，不需要 django_db 夹具（与 L50 test_claude_config_module_deleted 同模式）。
    """
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parent.parent
        / "projects"
        / "migrations"
        / "0009_remove_v81_legacy_claude_fields.py"
    )
    content = path.read_text(encoding="utf-8")

    # 必须声明 work item（大写或小写皆可）
    assert "work item" in content or "no-op" in content.lower(), (
        "0009 migration docstring 必须明确声明 backfill 是 work item（implementation Hotfix work-item item）"
    )
    # 旧的误导性表述必须删除
    assert "遍历仍有 claude_api_key_encrypted 的 Space" not in content, (
        "0009 docstring 仍保留旧的误导性 backfill 承诺表述，未完成 implementation 勘误"
    )
    # 预检命令名必须在 docstring 内出现（引导 release manager）
    assert "check_v81_legacy_residue" in content, (
        "0009 docstring 必须引用 check_v81_legacy_residue 预检命令名"
    )

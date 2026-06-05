"""数据迁移共享函数 —— 被 0005 RunPython 与 management command 双方 import。

initial implementation 引入：seed_provider_credentials_impl 把 SystemSetting.ANTHROPIC_* 4 个 key
导入为一条 anthropic/system/default 凭证（幂等 + 反向 + dry-run）。

设计要点：
- 迁移函数通过 apps.get_model 获取历史模型快照（Pitfall D 防御，禁止直接
  import system.models.ProviderCredential）；
- encrypt_value 是纯函数 import，不依赖模型 schema，允许直接 import；
- dry-run 与 apply 行为字段集完全一致（单一事实源，Pitfall E 防御）；
- mask_api_key 仅供日志/stdout 脱敏，禁止用于返回给前端或任何业务判断。
"""

from __future__ import annotations

import json
from typing import IO, Any

import structlog

logger = structlog.get_logger(__name__)


def mask_api_key(value: str) -> str:
    """日志/stdout 场景下脱敏 api_key；禁止用于业务判断或返回前端。

    规则：
    - 空值 → "<empty>"
    - 长度 ≤ 8 → "***"
    - 以 'sk-ant-' 开头（Anthropic 格式） → f"{value[:7]}***...{value[-4:]}"
    - 其他 → f"{value[:3]}***...{value[-4:]}"
    """
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "***"
    if value.startswith("sk-ant-"):
        return f"{value[:7]}***...{value[-4:]}"
    return f"{value[:3]}***...{value[-4:]}"


def _get_setting_value(SystemSetting: Any, key: str) -> str:
    """读取 SystemSetting 指定 key 的值，带 A3 假设防御。

    A3 防御：若历史数据手动改过 is_encrypted=True，走 decrypt_value 兜底；
    否则（默认 is_encrypted=False）直接返回 value 原文。
    """
    setting = SystemSetting.objects.filter(key=key).first()
    if setting is None or setting.value is None:
        return ""
    raw = setting.value
    if getattr(setting, "is_encrypted", False):
        # A3 防御：兜底处理 is_encrypted=True 的边界历史数据
        from common.encryption import decrypt_value

        return decrypt_value(raw)
    return raw


def seed_provider_credentials_impl(
    apps: Any,  # type: ignore[no-untyped-def]
    *,
    dry_run: bool,
    stdout: IO[str] | None = None,
) -> dict[str, int]:
    """从 SystemSetting.ANTHROPIC_* 导入为 anthropic/system/default 凭证。

    参数：
        apps: Django apps registry（RunPython 历史快照或 django.apps.apps）
        dry_run: True 时仅打印将要执行的操作，不写库
        stdout: 可选 IO 写入端（None 时静默）

    返回：
        {"created": int, "skipped": int, "failed": int}

    语义：
    - 目标凭证已存在 → skip（不覆盖用户手填）
    - ANTHROPIC_API_KEY 为空或缺失 → 整体 noop，warning 日志
    - dry-run 时打印 mask 后 api_key + 模式=dry-run，不写库
    - apply 时 encrypt_value(json.dumps({"api_key": ...})) 写入

    initial implementation plan（contract/contract）：SettingKeys.ANTHROPIC_* 常量硬删后，
    此 seed 命令仍接受 SystemSetting 行（key 为字面量字符串 "anthropic_*"），
    供 initial implementation contract 历史 migration 兼容调用。
    """
    # initial implementation plan：直接字面量 key，不再引用 SettingKeys.ANTHROPIC_* 常量
    _ANTHROPIC_API_KEY = "anthropic_api_key"
    _ANTHROPIC_BASE_URL = "anthropic_base_url"
    _ANTHROPIC_MODEL = "anthropic_model"

    SystemSetting = apps.get_model("system", "SystemSetting")
    ProviderCredential = apps.get_model("system", "ProviderCredential")

    api_key = _get_setting_value(SystemSetting, _ANTHROPIC_API_KEY)
    if not api_key or not api_key.strip():
        logger.warning(
            "provider_credential_seed_skipped",
            reason="anthropic_api_key_missing",
        )
        if stdout is not None:
            stdout.write("[seed_provider_credentials] noop: anthropic_api_key empty\n")
        return {"created": 0, "skipped": 0, "failed": 0}

    base_url_value = _get_setting_value(SystemSetting, _ANTHROPIC_BASE_URL)
    default_model_value = _get_setting_value(
        SystemSetting, _ANTHROPIC_MODEL
    )

    # CONTEXT 决策 3：禁用 update_or_create 覆盖语义，先查询再决定 skip vs create
    existing = ProviderCredential.objects.filter(
        provider_type="anthropic",
        scope="system",
        scope_id=None,
        name="default",
    ).first()
    if existing is not None:
        logger.info(
            "provider_credential_seed_skipped",
            reason="target_already_exists",
            credential_id=str(existing.id),
        )
        if stdout is not None:
            stdout.write(
                f"[seed_provider_credentials] skip anthropic/system/default "
                f"(already exists, id={existing.id})\n"
            )
        return {"created": 0, "skipped": 1, "failed": 0}

    payload = {"api_key": api_key}
    masked = mask_api_key(api_key)

    if dry_run:
        if stdout is not None:
            stdout.write(
                "[seed_provider_credentials] mode=dry-run\n"
                f"  + create  anthropic/system/default  "
                f"api_key={masked}  base_url={base_url_value}  "
                f"default_model={default_model_value}\n"
                "  (dry-run, no DB write)\n"
            )
        return {"created": 1, "skipped": 0, "failed": 0}

    # apply 分支：真 Fernet 加密写入
    from common.encryption import encrypt_value

    ProviderCredential.objects.create(
        provider_type="anthropic",
        name="default",
        scope="system",
        scope_id=None,
        encrypted_config=encrypt_value(json.dumps(payload)),
        base_url=base_url_value,
        default_model=default_model_value,
        is_active=True,
    )
    logger.info(
        "provider_credential_seed_completed",
        provider_type="anthropic",
        scope="system",
        name="default",
    )
    if stdout is not None:
        stdout.write(
            "[seed_provider_credentials] mode=apply\n"
            f"  + create  anthropic/system/default  "
            f"api_key={masked}  base_url={base_url_value}  "
            f"default_model={default_model_value}\n"
            "  done. 1 created, 0 skipped, 0 failed.\n"
        )
    return {"created": 1, "skipped": 0, "failed": 0}


def reverse_seed_provider_credentials_impl(
    apps: Any,  # type: ignore[no-untyped-def]
    schema_editor: Any,
) -> None:
    """反向迁移：按精确条件仅删除迁移自建的 default 行，不动用户手添凭证。"""
    ProviderCredential = apps.get_model("system", "ProviderCredential")
    deleted_count, _ = ProviderCredential.objects.filter(
        provider_type="anthropic",
        scope="system",
        scope_id=None,
        name="default",
    ).delete()
    logger.info(
        "provider_credential_seed_reversed",
        deleted_count=deleted_count,
    )

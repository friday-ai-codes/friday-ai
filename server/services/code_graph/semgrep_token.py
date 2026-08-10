"""SEMGREP_APP_TOKEN Fernet 写读（Phase 127 / D-09 / T-127-01）。

Pro opt-in token 仅经本模块读写：写入强制 ``encrypt_value`` + ``is_encrypted=True``；
读取解密后仅注入扫描子进程 env。⛔ 永不把返回值写入日志 / MR / ledger。
"""

from __future__ import annotations

from django.conf import settings

from common.encryption import decrypt_value, encrypt_value
from system.models import SettingKeys, SystemSetting

__all__ = [
    "set_semgrep_app_token",
    "get_semgrep_app_token",
    "resolve_semgrep_app_token",
    "is_semgrep_pro_enabled",
]


def set_semgrep_app_token(plaintext: str) -> None:
    """加密写入 ``SettingKeys.SEMGREP_APP_TOKEN``；空串清除（CE 路径）。"""
    text = (plaintext or "").strip()
    if not text:
        SystemSetting.objects.filter(key=SettingKeys.SEMGREP_APP_TOKEN).delete()
        return

    SystemSetting.objects.update_or_create(
        key=SettingKeys.SEMGREP_APP_TOKEN,
        defaults={
            "value": encrypt_value(text),
            "is_encrypted": True,
            "description": "Semgrep App Token (Pro opt-in; Fernet encrypted)",
        },
    )


def get_semgrep_app_token() -> str:
    """解密读取 token；缺失/空返回 \"\"（纯 CE）。永不记录返回值。"""
    try:
        setting = SystemSetting.objects.get(key=SettingKeys.SEMGREP_APP_TOKEN)
    except SystemSetting.DoesNotExist:
        return ""

    value = setting.value or ""
    if not value:
        return ""
    if setting.is_encrypted:
        return decrypt_value(value) or ""
    # 不应出现明文行；若历史脏数据则原样返回供调用方注入（仍禁止打日志）。
    return value


def resolve_semgrep_app_token() -> str:
    """Pro token 的**唯一**判定入口：加密 SystemSetting 优先，其次 env escape hatch。

    扫描注入与 MR 段的 Pro 诚实声明必须问同一个函数，否则「仅用 env 打开 Pro」时
    Semgrep 跑的是 Pro 而 MR 段却不声明（D-09 口径不一致）。⛔ 返回值永不入日志。
    """
    token = (get_semgrep_app_token() or "").strip()
    if token:
        return token
    return (getattr(settings, "SEMGREP_APP_TOKEN_ENV", "") or "").strip()


def is_semgrep_pro_enabled() -> bool:
    """Pro 是否启用（含 env escape hatch）；只返回布尔，不泄漏 token 值。"""
    try:
        return bool(resolve_semgrep_app_token())
    except Exception:  # noqa: BLE001 — 判定失败按 CE 处理，不阻断建 MR
        return False

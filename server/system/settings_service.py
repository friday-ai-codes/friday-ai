"""System settings runtime accessor.

Provides type-safe, cached read access to SystemSetting values.
All migrated env configs should be read through this module instead of
Django settings to allow admin runtime modification.
"""

from __future__ import annotations

import json
from typing import TypeVar

from django.core.cache import cache

from .models import SystemSetting

T = TypeVar("T", str, bool, int)

CACHE_PREFIX = "sys_setting:"
CACHE_TIMEOUT = 60  # 1 minute cache for settings


def _cache_key(key: str) -> str:
    return f"{CACHE_PREFIX}{key}"


def _get_raw(key: str) -> str | None:
    """Fetch raw value from DB with short-lived cache."""
    cache_key = _cache_key(key)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != "__none__" else None

    try:
        setting = SystemSetting.objects.filter(key=key).first()
    except Exception:
        return None

    value = setting.value if setting else None
    cache.set(cache_key, value if value is not None else "__none__", CACHE_TIMEOUT)
    return value


def get_setting(key: str, default: str = "") -> str:
    """Read string setting from SystemSetting."""
    value = _get_raw(key)
    return value if value is not None else default


def get_bool_setting(key: str, default: bool = False) -> bool:
    """Read boolean setting from SystemSetting."""
    value = _get_raw(key)
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def get_int_setting(key: str, default: int = 0) -> int:
    """Read integer setting from SystemSetting."""
    value = _get_raw(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def get_float_setting(key: str, default: float = 0.0) -> float:
    """Read float setting from SystemSetting（沿用 _get_raw 缓存；失败回默认）。"""
    value = _get_raw(key)
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def get_json_setting(key: str, default: dict | None = None) -> dict:
    """Read JSON(object) setting from SystemSetting（json.loads；失败/非 dict 回默认）。

    供 common.logging / log_sink 读取运行时日志配置（如分组件级别 map）。
    """
    fallback = dict(default) if default else {}
    value = _get_raw(key)
    if value is None:
        return fallback
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return fallback
    return parsed if isinstance(parsed, dict) else fallback


async def aget_setting(key: str, default: str = "") -> str:
    """Async version of get_setting."""
    try:
        setting = await SystemSetting.objects.filter(key=key).afirst()
    except Exception:
        return default
    return setting.value if setting and setting.value is not None else default


async def aget_bool_setting(key: str, default: bool = False) -> bool:
    """Async version of get_bool_setting."""
    value = await aget_setting(key, "")
    if not value:
        return default
    return value.lower() in ("true", "1", "yes", "on")


async def aget_int_setting(key: str, default: int = 0) -> int:
    """Async version of get_int_setting."""
    value = await aget_setting(key, "")
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


async def aget_float_setting(key: str, default: float = 0.0) -> float:
    """Async version of get_float_setting（语义与同步版一致：非法值回默认）。

    沿 aget_* 既有约定不走 60s 缓存，每次 afirst() 打 DB；供 async stage handler
    读运行时阈值（如 blueprint.spec_gate.config 的 threshold 兜底路径）。
    """
    value = await aget_setting(key, "")
    if not value:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


async def aget_json_setting(key: str, default: dict | None = None) -> dict:
    """Async version of get_json_setting（语义与同步版一致：失败/非 dict 回默认，绝不抛）。

    沿 aget_* 既有约定不走 60s 缓存；供 async stage handler 读运行时权重 map
    （blueprint.spec_gate.config / blueprint.route.weights）。
    """
    fallback = dict(default) if default else {}
    value = await aget_setting(key, "")
    if not value:
        return fallback
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return fallback
    return parsed if isinstance(parsed, dict) else fallback

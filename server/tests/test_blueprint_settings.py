"""蓝图规格门/路由运行时配置键测试（PLAN 112-01 Task 2，FLOW-01 / CHARTER-02）。

守三件事：

1. 两个新点分键（``blueprint.spec_gate.config`` / ``blueprint.route.weights``）缺配置
   时 getter 回传入默认（同步 + async 两条路径语义一致）；
2. 畸形配置逐项降级绝不抛：非 JSON 字符串 / JSON 顶层为 list / 空字符串三例都回默认；
3. 新增的 ``aget_float_setting`` / ``aget_json_setting`` 与同步版行为对齐，两键并存互不干扰。

范式照 ``test_log_runtime_config.py``：``_save_setting`` 用 ``instance.save()`` 触发
signal，autouse ``_isolate`` 前后各清 60s 缓存。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.cache import cache

from system.models import SettingKeys, SystemSetting
from system.settings_service import (
    _cache_key,
    aget_float_setting,
    aget_json_setting,
    get_float_setting,
    get_json_setting,
)

_BLUEPRINT_KEYS = [
    SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG,
    SettingKeys.BLUEPRINT_ROUTE_WEIGHTS,
]

# 消费侧（112-02/112-03）默认值形状快照，测试内当作「传入默认」使用。
_DEFAULT_SPEC_GATE: dict[str, Any] = {
    "threshold": 0.20,
    "weights": {"goal": 0.30, "boundary": 0.25, "constraint": 0.20, "acceptance": 0.25},
}
_DEFAULT_ROUTE_WEIGHTS: dict[str, Any] = {
    "greenfield": {"router_base": 0.40, "charter_match": 0.35, "history_match": 0.25},
    "brownfield": {"router_base": 0.60, "charter_match": 0.20, "history_match": 0.20},
    "fix": {"router_base": 0.70, "charter_match": 0.15, "history_match": 0.15},
}


def _clear_caches() -> None:
    for key in _BLUEPRINT_KEYS:
        try:
            cache.delete(_cache_key(key))
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(autouse=True)
def _isolate() -> Any:
    """隔离：前后各清两个新键的 60s 缓存，避免跨测试污染。"""
    _clear_caches()
    yield
    _clear_caches()


def _save_setting(key: str, value: str) -> None:
    """写设置并触发 post_save signal（用 instance.save()，非 queryset.update()）。"""
    obj, created = SystemSetting.objects.get_or_create(key=key, defaults={"value": value})
    if not created:
        obj.value = value
        obj.save()


# === 键注册与缺键回默认 ===


def test_setting_keys_registered() -> None:
    """点分键值冻结快照（消费方 112-02/03 按此字面值读取）。"""
    assert SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG == "blueprint.spec_gate.config"
    assert SettingKeys.BLUEPRINT_ROUTE_WEIGHTS == "blueprint.route.weights"


@pytest.mark.django_db
def test_spec_gate_config_missing_returns_default() -> None:
    """不建 SystemSetting 行 → 同步 getter 回传入默认（阈值 0.20 可见）。"""
    got = get_json_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, _DEFAULT_SPEC_GATE)
    assert got == _DEFAULT_SPEC_GATE
    assert got["threshold"] == 0.20


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_spec_gate_config_missing_returns_default_async() -> None:
    """async 版语义与同步版一致：缺键回传入默认。"""
    got = await aget_json_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, _DEFAULT_SPEC_GATE)
    assert got == _DEFAULT_SPEC_GATE


@pytest.mark.django_db
def test_route_weights_missing_returns_default() -> None:
    got = get_json_setting(SettingKeys.BLUEPRINT_ROUTE_WEIGHTS, _DEFAULT_ROUTE_WEIGHTS)
    assert got == _DEFAULT_ROUTE_WEIGHTS
    assert got["greenfield"]["charter_match"] > got["fix"]["charter_match"]


@pytest.mark.django_db
def test_json_setting_default_none_returns_empty_dict() -> None:
    """default 省略 → 回 {}（绝不返回 None，消费侧无需判空）。"""
    assert get_json_setting(SettingKeys.BLUEPRINT_ROUTE_WEIGHTS) == {}


# === 合法配置生效（运行时可调）===


@pytest.mark.django_db
def test_spec_gate_config_override_visible() -> None:
    """配置合法 JSON 后同步 getter 读到新值（threshold 从 0.20 改 0.5）。"""
    _save_setting(
        SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG,
        json.dumps({"threshold": 0.5, "weights": {"goal": 1.0}}),
    )
    got = get_json_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, _DEFAULT_SPEC_GATE)
    assert got["threshold"] == 0.5
    assert got["weights"] == {"goal": 1.0}


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_spec_gate_config_override_visible_async() -> None:
    """async 版同样读到运行时新值（不走 60s 缓存，每次打 DB）。"""
    from asgiref.sync import sync_to_async

    await sync_to_async(_save_setting)(
        SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG,
        json.dumps({"threshold": 0.5}),
    )
    got = await aget_json_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, _DEFAULT_SPEC_GATE)
    assert got["threshold"] == 0.5


# === 畸形配置逐项回默认（绝不抛）===


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad_value",
    ["not-json-at-all", "[1, 2, 3]", ""],
    ids=["non_json", "json_but_list", "empty_string"],
)
def test_malformed_spec_gate_config_falls_back(bad_value: str) -> None:
    """非 JSON / JSON 但顶层是 list / 空字符串 → 一律回默认，绝不抛。"""
    _save_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, bad_value)
    assert get_json_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, _DEFAULT_SPEC_GATE) == (
        _DEFAULT_SPEC_GATE
    )


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_value",
    ["not-json-at-all", "[1, 2, 3]", ""],
    ids=["non_json", "json_but_list", "empty_string"],
)
async def test_malformed_spec_gate_config_falls_back_async(bad_value: str) -> None:
    from asgiref.sync import sync_to_async

    await sync_to_async(_save_setting)(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, bad_value)
    got = await aget_json_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, _DEFAULT_SPEC_GATE)
    assert got == _DEFAULT_SPEC_GATE


# === aget_float_setting ===


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_aget_float_missing_returns_default() -> None:
    assert await aget_float_setting("blueprint.spec_gate.threshold_probe", 0.20) == 0.20


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_aget_float_valid_value_applied() -> None:
    from asgiref.sync import sync_to_async

    await sync_to_async(_save_setting)(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, "0.45")
    assert await aget_float_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, 0.20) == 0.45


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_aget_float_invalid_value_returns_default() -> None:
    """非数值字符串回默认，语义与同步 get_float_setting 一致。"""
    from asgiref.sync import sync_to_async

    await sync_to_async(_save_setting)(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, "abc")
    assert await aget_float_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, 0.20) == 0.20
    assert get_float_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, 0.20) == 0.20


# === 两键并存互不干扰 ===


@pytest.mark.django_db
def test_two_keys_are_independent() -> None:
    """设 route.weights 不影响 spec_gate.config 的读取（键空间隔离）。"""
    _save_setting(
        SettingKeys.BLUEPRINT_ROUTE_WEIGHTS,
        json.dumps({"greenfield": {"router_base": 0.1}}),
    )
    assert get_json_setting(SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, _DEFAULT_SPEC_GATE) == (
        _DEFAULT_SPEC_GATE
    )
    assert get_json_setting(SettingKeys.BLUEPRINT_ROUTE_WEIGHTS, _DEFAULT_ROUTE_WEIGHTS) == {
        "greenfield": {"router_base": 0.1}
    }

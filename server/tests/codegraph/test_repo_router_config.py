"""repo_router_config loader/校验单点测试（Phase 106-02，ROUTE-06）。

覆盖三条防线：
1. validate_weight_config 校验矩阵——网格白名单 / INV-R2 相对形式 / 常数范围 /
   结构错误逐条报错；DEFAULT_WEIGHT_CONFIG 自洽（错误列表空）。
2. load_weight_config 回退语义——无行 / 校验失败均回默认（永不反噬路由），
   校验失败记 warning 事件 repo_router_weight_config_invalid。
3. 「保存即生效」链路——写 SystemSetting 行触发 post_save signal 失效
   settings_service 60s 缓存，下一次 load 立即读到新值（无需发版/重启）。
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from django.core.cache import cache
from structlog.testing import capture_logs

from codegraph.services.repo_router_config import (
    WEIGHT_GRID,
    aload_weight_config,
    load_nr_snapshot,
    load_weight_config,
    validate_weight_config,
)
from codegraph.services.repo_router_scoring import DEFAULT_WEIGHT_CONFIG
from system.models import SettingKeys, SystemSetting
from system.settings_service import _cache_key


@pytest.fixture(autouse=True)
def _clear_setting_cache():
    """settings_service 缓存跨用例共享（locmem 不随测试事务回滚），前后各清一次。"""
    for key in (SettingKeys.REPO_ROUTER_WEIGHT_CONFIG, SettingKeys.REPO_ROUTER_NR_SNAPSHOT):
        cache.delete(_cache_key(key))
    yield
    for key in (SettingKeys.REPO_ROUTER_WEIGHT_CONFIG, SettingKeys.REPO_ROUTER_NR_SNAPSHOT):
        cache.delete(_cache_key(key))


def _make_config(
    *,
    weights: dict[str, float] | None = None,
    constants: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """从 DEFAULT 深拷贝出一份配置并做局部覆盖（保持其余字段合法）。"""
    cfg = copy.deepcopy(DEFAULT_WEIGHT_CONFIG)
    if weights:
        cfg["weights"].update(weights)
    if constants:
        cfg["constants"].update(constants)
    cfg.update(overrides)
    return cfg


# ============================================================================
# SettingKeys 三键定版（106-04/05/06 只消费不再改 system/models.py）
# ============================================================================


class TestSettingKeys:
    def test_three_keys_defined(self):
        assert SettingKeys.REPO_ROUTER_WEIGHT_CONFIG == "repo_router.weight_config"
        assert SettingKeys.REPO_ROUTER_NR_SNAPSHOT == "repo_router.nr_snapshot"
        assert SettingKeys.REPO_ROUTER_ALIAS_DICT == "repo_router.alias_dict"


# ============================================================================
# validate_weight_config 校验矩阵
# ============================================================================


class TestValidateWeightConfig:
    def test_default_config_is_self_consistent(self):
        """DEFAULT_WEIGHT_CONFIG 原样通过（默认配置自洽，错误列表空）。"""
        normalized, errors = validate_weight_config(copy.deepcopy(DEFAULT_WEIGHT_CONFIG))
        assert errors == []
        assert normalized["weights"] == DEFAULT_WEIGHT_CONFIG["weights"]
        assert normalized["constants"]["half_life_days"] == 180.0

    def test_non_dict_input_rejected(self):
        normalized, errors = validate_weight_config(["not", "a", "dict"])
        assert errors
        # 错误时第一元素仍为可用的规范化尝试（回退 DEFAULT 形状）
        assert isinstance(normalized, dict)
        assert "weights" in normalized

    def test_off_grid_weight_rejected(self):
        """权重 0.13 不在离散网格 → 报错（防过拟合四道闸之一）。"""
        assert not any(abs(0.13 - g) < 1e-9 for g in WEIGHT_GRID)
        _, errors = validate_weight_config(_make_config(weights={"domain": 0.13}))
        assert any("domain" in e for e in errors)

    def test_missing_weight_key_rejected(self):
        """weights 缺 team 键 → 报错（键集合必须恰为 5 信号）。"""
        cfg = _make_config()
        del cfg["weights"]["team"]
        _, errors = validate_weight_config(cfg)
        assert any("team" in e for e in errors)

    def test_unknown_weight_key_rejected(self):
        cfg = _make_config()
        cfg["weights"]["criticality"] = 0.05
        _, errors = validate_weight_config(cfg)
        assert any("criticality" in e for e in errors)

    def test_inv_r2_relative_violation_rejected(self):
        """元数据权重相对和 > 0.5×总和 → 报错 INV-R2（文本主导不变量）。

        注意构造：plan 字面样例 domain=0.30/stack=0.20/team=0.15 在默认
        text=0.55/act=0.12 下相对和 0.65/1.32≈0.492 ≤ 0.5，并不违反相对形式，
        故此处用 0.40/0.30/0.20（均在网格内；0.90/1.57≈0.573 > 0.5）。
        """
        cfg = _make_config(weights={"domain": 0.40, "stack": 0.30, "team": 0.20})
        _, errors = validate_weight_config(cfg)
        assert any("INV-R2" in e for e in errors)

    def test_inv_r2_boundary_passes(self):
        """相对和恰好 ≤ 0.5×总和的合法配置通过（默认配置 0.28/0.95≈0.295）。"""
        _, errors = validate_weight_config(_make_config())
        assert errors == []

    @pytest.mark.parametrize(
        ("constants", "needle"),
        [
            ({"half_life_days": 0}, "half_life_days"),
            ({"s_top_c_lo": 0.55, "s_top_c_hi": 0.55}, "s_top_c"),
            ({"t2_c_lo": 0.6, "t2_c_hi": 0.5}, "t2_c"),
            ({"crit_band": 0}, "crit_band"),
            ({"p": 0.5}, "p"),
            ({"b": 1.5}, "b"),
            ({"lam": -0.1}, "lam"),
            ({"n_cap": 0}, "n_cap"),
            ({"offset_days": -1}, "offset_days"),
            ({"activity_floor": 2}, "activity_floor"),
            ({"deprecated_cap": -0.2}, "deprecated_cap"),
        ],
    )
    def test_constant_range_violations_rejected(self, constants, needle):
        _, errors = validate_weight_config(_make_config(constants=constants))
        assert any(needle in e for e in errors), errors

    def test_unknown_constant_key_rejected(self):
        cfg = _make_config()
        cfg["constants"]["mystery_knob"] = 1.0
        _, errors = validate_weight_config(cfg)
        assert any("mystery_knob" in e for e in errors)

    def test_empty_weight_set_version_rejected(self):
        _, errors = validate_weight_config(_make_config(weight_set_version=""))
        assert any("weight_set_version" in e for e in errors)

    def test_t2_disabled_facets_non_string_rejected(self):
        _, errors = validate_weight_config(_make_config(t2_disabled_facets=["domain", 42]))
        assert any("t2_disabled_facets" in e for e in errors)

    def test_t2_disabled_facets_unknown_value_rejected(self):
        """MJ-02：枚举白名单——未知取值（含 team、拼错的维度名）直接拒绝。

        修复前只校验「是字符串列表」，运维按校准报告填中文维度名可通过校验但
        在 resolver 侧永不生效（静默失效比报错危险）。
        """
        _, errors = validate_weight_config(_make_config(t2_disabled_facets=["团队", "team"]))
        assert any("t2_disabled_facets" in e for e in errors)

    def test_t2_disabled_facets_chinese_dim_normalized_to_signal(self):
        """中文维度名（校准报告行键）合法但落库前归一为英文 signal 名。"""
        normalized, errors = validate_weight_config(
            _make_config(t2_disabled_facets=["业务线/产品线", "技术栈"])
        )
        assert errors == []
        assert normalized["t2_disabled_facets"] == ["domain", "stack"]

    def test_criticality_anchor_out_of_range_rejected(self):
        cfg = _make_config()
        cfg["criticality_anchors"]["核心"] = 1.5
        _, errors = validate_weight_config(cfg)
        assert any("criticality_anchors" in e for e in errors)

    def test_partial_config_merged_with_default(self):
        """缺键补默认（merge 语义）：只给 weights 也是合法配置。"""
        normalized, errors = validate_weight_config(
            {"weights": dict(DEFAULT_WEIGHT_CONFIG["weights"])}
        )
        assert errors == []
        assert normalized["constants"] == DEFAULT_WEIGHT_CONFIG["constants"]
        assert normalized["weight_set_version"] == DEFAULT_WEIGHT_CONFIG["weight_set_version"]


# ============================================================================
# load_weight_config：默认回退 / 非法拦截 / 保存即生效
# ============================================================================


@pytest.mark.django_db
class TestLoadWeightConfig:
    def test_no_row_returns_default_deepcopy(self):
        config = load_weight_config()
        assert config == DEFAULT_WEIGHT_CONFIG
        # 深拷贝：调用方改返回值不得污染模块级默认
        config["weights"]["domain"] = 0.99
        assert DEFAULT_WEIGHT_CONFIG["weights"]["domain"] == 0.15

    def test_invalid_json_row_returns_default(self):
        SystemSetting.objects.create(
            key=SettingKeys.REPO_ROUTER_WEIGHT_CONFIG, value="{not json!"
        )
        assert load_weight_config() == DEFAULT_WEIGHT_CONFIG

    def test_invalid_config_row_returns_default_with_warning(self):
        """直写 DB 的非法值被 loader 二次校验拦截（T-106-04），回退默认 + warning。"""
        bad = _make_config(weights={"domain": 0.13})
        SystemSetting.objects.create(
            key=SettingKeys.REPO_ROUTER_WEIGHT_CONFIG, value=json.dumps(bad)
        )
        with capture_logs() as logs:
            config = load_weight_config()
        assert config == DEFAULT_WEIGHT_CONFIG
        assert any(log["event"] == "repo_router_weight_config_invalid" for log in logs)

    def test_valid_row_returns_stored_values(self):
        stored = _make_config(weights={"domain": 0.20, "stack": 0.05})
        SystemSetting.objects.create(
            key=SettingKeys.REPO_ROUTER_WEIGHT_CONFIG, value=json.dumps(stored)
        )
        config = load_weight_config()
        assert config["weights"]["domain"] == 0.20
        assert config["weights"]["stack"] == 0.05
        assert config["constants"]["half_life_days"] == 180.0

    def test_save_takes_effect_immediately(self):
        """保存即生效：先 load 预热缓存，写行触发 signal 失效，下一次 load 即新值。"""
        assert load_weight_config() == DEFAULT_WEIGHT_CONFIG  # 预热 60s 缓存（__none__）
        stored = _make_config(weights={"domain": 0.20, "stack": 0.05})
        SystemSetting.objects.create(
            key=SettingKeys.REPO_ROUTER_WEIGHT_CONFIG, value=json.dumps(stored)
        )
        assert load_weight_config()["weights"]["domain"] == 0.20

    @pytest.mark.asyncio
    async def test_aload_weight_config_matches_sync(self):
        config = await aload_weight_config()
        assert config == DEFAULT_WEIGHT_CONFIG


# ============================================================================
# load_nr_snapshot
# ============================================================================


@pytest.mark.django_db
class TestLoadNrSnapshot:
    def test_no_row_returns_empty_shape(self):
        snapshot = load_nr_snapshot()
        assert snapshot["n_r_by_repo"] == {}
        assert snapshot["n_bar"] is None

    def test_bad_json_returns_empty_shape(self):
        SystemSetting.objects.create(key=SettingKeys.REPO_ROUTER_NR_SNAPSHOT, value="[oops")
        snapshot = load_nr_snapshot()
        assert snapshot["n_r_by_repo"] == {}
        assert snapshot["n_bar"] is None

    def test_valid_row_passthrough_with_float_n_bar(self):
        SystemSetting.objects.create(
            key=SettingKeys.REPO_ROUTER_NR_SNAPSHOT,
            value=json.dumps(
                {
                    "n_r_by_repo": {"repo-1": 120, "repo-2": 45},
                    "n_bar": 82,
                    "generated_at": "2026-07-29T00:00:00Z",
                }
            ),
        )
        snapshot = load_nr_snapshot()
        assert snapshot["n_r_by_repo"] == {"repo-1": 120, "repo-2": 45}
        assert snapshot["n_bar"] == 82.0
        assert isinstance(snapshot["n_bar"], float)
        assert snapshot["generated_at"] == "2026-07-29T00:00:00Z"

"""RepoRouterWeightConfigView 专用端点测试（Phase 106-02，ROUTE-06）。

校验矩阵覆盖：
- GET 未配置 → DEFAULT + is_default=true（运维界面总能拿到当前生效配置）；
- PUT 合法 → 落库 + 保存即生效链路（GET 新值 && load_weight_config 同步新值）；
- PUT 非法（网格外 / INV-R2 破坏 / c_lo>=c_hi）→ 400 + 逐条 errors（T-106-03）；
- PUT 非 superuser → 403 中文 detail；GET 未认证 → 401/403；
- 通用端点回归：新专用路径不落入 `<str:key>/` 通配，通用路由不被新路径拦截。
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from django.core.cache import cache
from django.urls import resolve
from rest_framework import status

from codegraph.services.repo_router_config import load_weight_config
from codegraph.services.repo_router_scoring import DEFAULT_WEIGHT_CONFIG
from system.models import SettingKeys, SystemSetting
from system.settings_service import _cache_key

WEIGHT_CONFIG_URL = "/api/settings/repo-router/weight-config/"
GENERIC_SETTING_URL = f"/api/settings/{SettingKeys.REPO_ROUTER_WEIGHT_CONFIG}/"


@pytest.fixture(autouse=True)
def _clear_setting_cache():
    """settings_service 缓存跨用例共享（locmem 不随测试事务回滚），前后各清一次。"""
    cache.delete(_cache_key(SettingKeys.REPO_ROUTER_WEIGHT_CONFIG))
    yield
    cache.delete(_cache_key(SettingKeys.REPO_ROUTER_WEIGHT_CONFIG))


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
# GET：默认回退 / is_default 标记
# ============================================================================


@pytest.mark.django_db
class TestWeightConfigGet:
    def test_get_unconfigured_returns_default_with_flag(self, authenticated_admin_client):
        response = authenticated_admin_client.get(WEIGHT_CONFIG_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_default"] is True
        assert response.data["weights"] == DEFAULT_WEIGHT_CONFIG["weights"]
        assert response.data["weight_set_version"] == DEFAULT_WEIGHT_CONFIG["weight_set_version"]

    def test_get_configured_returns_stored_values(self, authenticated_admin_client):
        stored = _make_config(weights={"domain": 0.20, "stack": 0.05})
        SystemSetting.objects.create(
            key=SettingKeys.REPO_ROUTER_WEIGHT_CONFIG, value=json.dumps(stored)
        )

        response = authenticated_admin_client.get(WEIGHT_CONFIG_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_default"] is False
        assert response.data["weights"]["domain"] == 0.20

    def test_get_allows_non_superuser(self, authenticated_client):
        """GET 任意已认证用户可读（与 ClaudeCodeConfigView 口径一致）。"""
        response = authenticated_client.get(WEIGHT_CONFIG_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_default"] is True

    def test_get_unauthenticated_rejected(self, api_client):
        response = api_client.get(WEIGHT_CONFIG_URL)

        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


# ============================================================================
# PUT：合法写入 + 保存即生效链路
# ============================================================================


@pytest.mark.django_db
class TestWeightConfigPut:
    def test_put_valid_config_persists_and_takes_effect(self, authenticated_admin_client):
        """保存即生效：PUT 落库触发 signal 失效缓存，GET 与 loader 立即读到新值。"""
        # 先 GET 预热 60s 缓存（缓存 __none__），验证写入路径确实失效了缓存
        assert authenticated_admin_client.get(WEIGHT_CONFIG_URL).data["is_default"] is True

        payload = _make_config(weights={"domain": 0.20, "stack": 0.05})
        response = authenticated_admin_client.put(WEIGHT_CONFIG_URL, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["weights"]["domain"] == 0.20
        assert response.data["weights"]["stack"] == 0.05

        # GET 返回新值 + is_default 翻转
        get_response = authenticated_admin_client.get(WEIGHT_CONFIG_URL)
        assert get_response.data["is_default"] is False
        assert get_response.data["weights"]["domain"] == 0.20

        # loader 同步读到新值（106-06 router 消费的同一条链路）
        config = load_weight_config()
        assert config["weights"]["domain"] == 0.20
        assert config["weights"]["stack"] == 0.05

    def test_put_partial_config_merged_with_default(self, authenticated_admin_client):
        """merge 语义：只传 weights 也是合法配置，constants 补默认。"""
        payload = {"weights": dict(DEFAULT_WEIGHT_CONFIG["weights"])}
        response = authenticated_admin_client.put(WEIGHT_CONFIG_URL, payload, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["constants"] == DEFAULT_WEIGHT_CONFIG["constants"]

    def test_put_off_grid_weight_rejected(self, authenticated_admin_client):
        payload = _make_config(weights={"domain": 0.13})
        response = authenticated_admin_client.put(WEIGHT_CONFIG_URL, payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert any("domain" in e for e in response.data["errors"])
        # 非法值未落库
        assert not SystemSetting.objects.filter(
            key=SettingKeys.REPO_ROUTER_WEIGHT_CONFIG
        ).exists()

    def test_put_inv_r2_violation_rejected(self, authenticated_admin_client):
        """元数据权重相对和 > 0.5×总和 → 400（均在网格内，0.90/1.57≈0.573 > 0.5）。"""
        payload = _make_config(weights={"domain": 0.40, "stack": 0.30, "team": 0.20})
        response = authenticated_admin_client.put(WEIGHT_CONFIG_URL, payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert any("INV-R2" in e for e in response.data["errors"])

    def test_put_c_lo_ge_c_hi_rejected(self, authenticated_admin_client):
        payload = _make_config(constants={"s_top_c_lo": 0.55, "s_top_c_hi": 0.55})
        response = authenticated_admin_client.put(WEIGHT_CONFIG_URL, payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert any("s_top_c" in e for e in response.data["errors"])

    def test_put_non_superuser_forbidden(self, authenticated_client):
        payload = _make_config()
        response = authenticated_client.put(WEIGHT_CONFIG_URL, payload, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "系统管理员" in response.data["detail"]


# ============================================================================
# URL 路由回归：专用路径与 <str:key>/ 通配互不干扰
# ============================================================================


@pytest.mark.django_db
class TestUrlRoutingRegression:
    def test_dedicated_path_resolves_to_weight_config_view(self):
        """新专用路径不落入 <str:key>/ 通配（path 定义排序纪律）。"""
        match = resolve(WEIGHT_CONFIG_URL)
        assert match.view_name == "repo-router-weight-config"
        assert match.kwargs == {}

    def test_generic_key_path_still_resolves_to_detail_view(self):
        """通用路由不被新路径拦截：repo_router.weight_config 仍走 <str:key>/。"""
        match = resolve(GENERIC_SETTING_URL)
        assert match.view_name == "settings-detail"
        assert match.kwargs == {"key": SettingKeys.REPO_ROUTER_WEIGHT_CONFIG}

    def test_generic_put_endpoint_still_functional(self, authenticated_admin_client):
        """通用端点回归：PUT /api/settings/repo_router.weight_config/ 正常写入。

        注意：通用端点无业务校验（RESEARCH Anti-Pattern，权重写入应走专用端点），
        直写的非法值由 loader 二次校验拦截——此处只验证路由未被破坏。
        """
        response = authenticated_admin_client.put(
            GENERIC_SETTING_URL,
            {"value": json.dumps(_make_config())},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["key"] == SettingKeys.REPO_ROUTER_WEIGHT_CONFIG

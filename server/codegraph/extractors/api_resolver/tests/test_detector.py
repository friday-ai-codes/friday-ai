"""detector.py 单元测试 —— Step 0/1 axios 锚点 + ApiWrapper 识别。

per work item: 验证 LowLevelHelper 发现、ApiWrapper 识别、URL 提取、base URL 剥除。
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BASIC_TS = str(FIXTURES_DIR / "api_resolver_basic.ts")
BASE_URL_TS = str(FIXTURES_DIR / "api_resolver_base_url.ts")


@pytest.fixture()
def config():
    from codegraph.extractors.api_resolver.config import get_api_detector_config

    return get_api_detector_config()


@pytest.fixture()
def basic_parsed():
    from codegraph.extractors.api_resolver.detector import parse_ts_or_vue_for_api

    return parse_ts_or_vue_for_api(BASIC_TS)


@pytest.fixture()
def base_url_parsed():
    from codegraph.extractors.api_resolver.detector import parse_ts_or_vue_for_api

    return parse_ts_or_vue_for_api(BASE_URL_TS)


class TestStep0DiscoverHelpers:
    """Step 0: discover_low_level_helpers 单元测试（work item）。"""

    def test_discover_helpers_basic(self, basic_parsed, config):
        """从 basic fixture 找到 get / post 两个 LowLevelHelper。"""
        from codegraph.extractors.api_resolver.detector import discover_low_level_helpers

        tree, source = basic_parsed
        helpers = discover_low_level_helpers(tree, source, BASIC_TS, config)
        assert "get" in helpers, f"期望找到 get，实际 {helpers}"
        assert "post" in helpers, f"期望找到 post，实际 {helpers}"

    def test_discover_helpers_non_export_ignored(self, basic_parsed, config):
        """非 export function 内的 axios 调用不识别为 LowLevelHelper。"""
        from codegraph.extractors.api_resolver.detector import discover_low_level_helpers

        tree, source = basic_parsed
        helpers = discover_low_level_helpers(tree, source, BASIC_TS, config)
        assert "internalHelper" not in helpers

    def test_discover_helpers_vite_env(self, base_url_parsed, config):
        """VITE_API_URL 变体的 LowLevelHelper 也能识别。"""
        from codegraph.extractors.api_resolver.detector import discover_low_level_helpers

        tree, source = base_url_parsed
        helpers = discover_low_level_helpers(tree, source, BASE_URL_TS, config)
        assert "httpGet" in helpers or "vueAppGet" in helpers, f"实际 {helpers}"

    def test_force_helpers_added(self, basic_parsed, tmp_path):
        """force_helpers 配置追加到识别结果。"""
        from django.test import override_settings

        from codegraph.extractors.api_resolver.config import get_api_detector_config
        from codegraph.extractors.api_resolver.detector import discover_low_level_helpers

        with override_settings(API_DETECTOR_CONFIG={
            "base_url_patterns": [],
            "force_helpers": [{"file_path": "api_resolver_basic.ts", "func_name": "forcedHelper"}],
            "exclude_helpers": [],
            "axios_method_names": ["get"],
            "helper_method_map": {"get": "GET"},
        }):
            config = get_api_detector_config()
            tree, source = basic_parsed
            helpers = discover_low_level_helpers(tree, source, BASIC_TS, config)
        assert "forcedHelper" in helpers


class TestStep1DiscoverWrappers:
    """Step 1: discover_api_wrappers 单元测试（work item）。"""

    def test_discover_wrappers_basic(self, basic_parsed, config):
        """从 basic fixture 找到 getUserInfo / createOrder 两个 ApiWrapper。"""
        from codegraph.extractors.api_resolver.detector import discover_api_wrappers

        tree, source = basic_parsed
        wrappers = discover_api_wrappers(tree, source, BASIC_TS, {"get", "post"}, config)
        symbols = [w.function_symbol for w in wrappers]
        assert "getUserInfo" in symbols, f"期望找到 getUserInfo，实际 {symbols}"
        assert "createOrder" in symbols, f"期望找到 createOrder，实际 {symbols}"

    def test_url_extraction(self, basic_parsed, config):
        """ApiWrapper 的 url_path_raw 正确提取。"""
        from codegraph.extractors.api_resolver.detector import discover_api_wrappers

        tree, source = basic_parsed
        wrappers = discover_api_wrappers(tree, source, BASIC_TS, {"get", "post"}, config)
        uc = next((w for w in wrappers if w.function_symbol == "getUserInfo"), None)
        assert uc is not None, "未找到 getUserInfo"
        assert uc.url_path_raw == "/api/user/info", f"实际 url_path_raw={uc.url_path_raw}"

    def test_base_url_strip_not_needed(self, basic_parsed, config):
        """basic fixture 的 URL 不含 base URL 模板，url_path_pattern == url_path_raw。"""
        from codegraph.extractors.api_resolver.detector import discover_api_wrappers

        tree, source = basic_parsed
        wrappers = discover_api_wrappers(tree, source, BASIC_TS, {"get"}, config)
        uc = next((w for w in wrappers if w.function_symbol == "getUserInfo"), None)
        assert uc is not None
        # URL 不含 base URL 模板，两个字段应相同
        assert uc.url_path_pattern == uc.url_path_raw

    def test_base_url_strip_vite_env(self, base_url_parsed, config):
        """${import.meta.env.VITE_API_URL} 被正确剥除。"""
        from codegraph.extractors.api_resolver.detector import (
            discover_low_level_helpers,
            discover_api_wrappers,
        )

        tree, source = base_url_parsed
        helpers = discover_low_level_helpers(tree, source, BASE_URL_TS, config)
        wrappers = discover_api_wrappers(tree, source, BASE_URL_TS, set(helpers), config)
        assert wrappers, f"未发现任何 ApiWrapper，helpers={helpers}"
        # url_path_pattern 应该不含 ${import.meta.env...}
        for w in wrappers:
            assert "${" not in w.url_path_pattern, (
                f"{w.function_symbol}.url_path_pattern 仍含模板变量: {w.url_path_pattern}"
            )

    def test_http_method_mapping(self, basic_parsed, config):
        """get → GET，post → POST 方法映射。"""
        from codegraph.extractors.api_resolver.detector import discover_api_wrappers

        tree, source = basic_parsed
        wrappers = discover_api_wrappers(tree, source, BASIC_TS, {"get", "post"}, config)
        w_get = next((w for w in wrappers if w.function_symbol == "getUserInfo"), None)
        w_post = next((w for w in wrappers if w.function_symbol == "createOrder"), None)
        assert w_get and w_get.http_method == "GET"
        assert w_post and w_post.http_method == "POST"

    def test_exclude_helpers(self, basic_parsed):
        """exclude_helpers 生效时不生成对应 wrapper。"""
        from django.test import override_settings

        from codegraph.extractors.api_resolver.config import get_api_detector_config
        from codegraph.extractors.api_resolver.detector import discover_api_wrappers

        with override_settings(API_DETECTOR_CONFIG={
            "base_url_patterns": [],
            "force_helpers": [],
            "exclude_helpers": ["post"],
            "axios_method_names": ["get", "post"],
            "helper_method_map": {"get": "GET", "post": "POST"},
        }):
            config = get_api_detector_config()

        tree, source = basic_parsed
        wrappers = discover_api_wrappers(tree, source, BASIC_TS, {"get", "post"}, config)
        # createOrder 调用 post，post 被 exclude → 不生成 createOrder wrapper
        symbols = [w.function_symbol for w in wrappers]
        assert "createOrder" not in symbols, f"期望 createOrder 被排除，实际 {symbols}"

    def test_empty_helper_names_returns_empty(self, basic_parsed, config):
        """helper_names 为空时返回空列表（不 crash）。"""
        from codegraph.extractors.api_resolver.detector import discover_api_wrappers

        tree, source = basic_parsed
        wrappers = discover_api_wrappers(tree, source, BASIC_TS, set(), config)
        assert wrappers == []

    def test_line_number_populated(self, basic_parsed, config):
        """ApiWrapperData.line_number > 0（正确定位函数起始行）。"""
        from codegraph.extractors.api_resolver.detector import discover_api_wrappers

        tree, source = basic_parsed
        wrappers = discover_api_wrappers(tree, source, BASIC_TS, {"get"}, config)
        uc = next((w for w in wrappers if w.function_symbol == "getUserInfo"), None)
        assert uc is not None
        assert uc.line_number > 0


class TestParseFile:
    """parse_ts_or_vue_for_api 单元测试。"""

    def test_parse_ts_file_success(self):
        """TS fixture 文件解析成功，返回 (tree, source)。"""
        from codegraph.extractors.api_resolver.detector import parse_ts_or_vue_for_api

        result = parse_ts_or_vue_for_api(BASIC_TS)
        assert result is not None
        tree, source = result
        assert tree is not None
        assert "export function get" in source

    def test_parse_nonexistent_file_returns_none(self, tmp_path):
        """不存在的文件返回 None（不 crash）。"""
        from codegraph.extractors.api_resolver.detector import parse_ts_or_vue_for_api

        result = parse_ts_or_vue_for_api(str(tmp_path / "nonexistent.ts"))
        assert result is None

    def test_parse_unsupported_extension_returns_none(self, tmp_path):
        """不支持的文件扩展名返回 None。"""
        f = tmp_path / "test.py"
        f.write_text("print('hello')")
        from codegraph.extractors.api_resolver.detector import parse_ts_or_vue_for_api

        result = parse_ts_or_vue_for_api(str(f))
        assert result is None

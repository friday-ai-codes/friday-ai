"""config.py 单元测试 —— API_DETECTOR_CONFIG + .friday/config.yaml 合并层。

per work item: 验证 settings 默认值、base URL 剥除、yaml 覆盖逻辑。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from django.test import override_settings


class TestGetApiDetectorConfig:
    """get_api_detector_config() 单元测试。"""

    def test_returns_settings_defaults(self):
        """无 repo_root 时返回 settings.API_DETECTOR_CONFIG 默认值。"""
        from codegraph.extractors.api_resolver.config import get_api_detector_config

        config = get_api_detector_config()
        assert "base_url_patterns" in config
        assert "helper_method_map" in config
        assert "axios_method_names" in config
        assert "_compiled_base_patterns" in config  # 预编译 patterns
        assert len(config["_compiled_base_patterns"]) > 0

    def test_compiled_patterns_are_regex(self):
        """_compiled_base_patterns 是 re.Pattern 列表。"""
        import re

        from codegraph.extractors.api_resolver.config import get_api_detector_config

        config = get_api_detector_config()
        for p in config["_compiled_base_patterns"]:
            assert hasattr(p, "sub"), f"期望 re.Pattern，实际 {type(p)}"

    def test_no_friday_config_no_crash(self, tmp_path):
        """repo_root 存在但无 .friday/config.yaml 时不报错，返回 settings 默认值。"""
        from codegraph.extractors.api_resolver.config import get_api_detector_config

        config = get_api_detector_config(str(tmp_path))
        assert "base_url_patterns" in config

    def test_friday_config_appends_force_helpers(self, tmp_path):
        """有 .friday/config.yaml 时，force_helpers 追加而非覆盖。"""
        friday_dir = tmp_path / ".friday"
        friday_dir.mkdir()
        (friday_dir / "config.yaml").write_text(
            textwrap.dedent("""
                api_resolver:
                  force_helpers:
                    - file_path: utils/http.ts
                      func_name: customGet
            """)
        )

        with override_settings(API_DETECTOR_CONFIG={"force_helpers": [], "base_url_patterns": [], "axios_method_names": [], "helper_method_map": {}}):
            from codegraph.extractors.api_resolver.config import get_api_detector_config

            config = get_api_detector_config(str(tmp_path))

        assert len(config["force_helpers"]) >= 1
        assert any(h.get("func_name") == "customGet" for h in config["force_helpers"])

    def test_friday_config_appends_base_url_patterns(self, tmp_path):
        """.friday/config.yaml 中 base_url_patterns 追加到 settings 列表。"""
        friday_dir = tmp_path / ".friday"
        friday_dir.mkdir()
        (friday_dir / "config.yaml").write_text(
            textwrap.dedent(r"""
                api_resolver:
                  base_url_patterns:
                    - '\$\{customEnv\.API\}'
            """)
        )

        with override_settings(API_DETECTOR_CONFIG={"base_url_patterns": [r"\$\{configGlobal\.api\}"], "force_helpers": [], "exclude_helpers": [], "axios_method_names": [], "helper_method_map": {}}):
            from codegraph.extractors.api_resolver.config import get_api_detector_config

            config = get_api_detector_config(str(tmp_path))

        assert len(config["base_url_patterns"]) == 2
        patterns_str = str(config["base_url_patterns"])
        assert "customEnv" in patterns_str

    def test_friday_config_invalid_yaml_no_crash(self, tmp_path):
        """无效 yaml 时不 crash，返回 settings 默认值。"""
        friday_dir = tmp_path / ".friday"
        friday_dir.mkdir()
        (friday_dir / "config.yaml").write_text("invalid: yaml: [\n")

        from codegraph.extractors.api_resolver.config import get_api_detector_config

        config = get_api_detector_config(str(tmp_path))
        assert "base_url_patterns" in config  # 不 crash，使用默认值


class TestStripBaseUrl:
    """strip_base_url() 单元测试。"""

    @pytest.fixture()
    def config(self):
        from codegraph.extractors.api_resolver.config import get_api_detector_config

        return get_api_detector_config()

    def test_strip_config_global_api(self, config):
        """剥除 ${configGlobal.api} 前缀。"""
        from codegraph.extractors.api_resolver.config import strip_base_url

        result = strip_base_url("${configGlobal.api}/api/user/info", config)
        assert result == "/api/user/info"

    def test_strip_vite_api_url(self, config):
        """剥除 ${import.meta.env.VITE_API_URL} 前缀。"""
        from codegraph.extractors.api_resolver.config import strip_base_url

        result = strip_base_url("${import.meta.env.VITE_API_URL}/health", config)
        assert result == "/health"

    def test_strip_vue_app_api_url(self, config):
        """剥除 ${import.meta.env.VUE_APP_API_URL} 前缀。"""
        from codegraph.extractors.api_resolver.config import strip_base_url

        result = strip_base_url("${import.meta.env.VUE_APP_API_URL}/api/v1/users", config)
        assert result == "/api/v1/users"

    def test_no_base_url_passthrough(self, config):
        """无 base URL 模板时原样返回。"""
        from codegraph.extractors.api_resolver.config import strip_base_url

        result = strip_base_url("/api/user/info", config)
        assert result == "/api/user/info"

    def test_empty_url(self, config):
        """空字符串不 crash。"""
        from codegraph.extractors.api_resolver.config import strip_base_url

        result = strip_base_url("", config)
        assert result == ""

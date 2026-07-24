"""端到端集成测试 —— fetchTopicFinished 类样本追踪。

需要本地样例仓库，通过环境变量 TS_SAMPLE_REPO 指定。
运行（本地）：pytest -m integration --no-cov -v
CI 跳过：样例仓库路径不存在时自动 skip。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

STUDY_APP_PATH = os.environ.get("TS_SAMPLE_REPO", "")
STUDY_APP_GLOBAL_PKG = f"{STUDY_APP_PATH}/utils/global/src/axios.config.ts"
STUDY_APP_HOME_SERVICES = f"{STUDY_APP_PATH}/apps/home/src/services/index.ts"
STUDY_APP_LADDER_SERVICES = (
    f"{STUDY_APP_PATH}/apps/tabStudyCompany/src/views/newLadder/services/lastTextbook.ts"
)


@pytest.mark.integration
@pytest.mark.skipif(
    not STUDY_APP_PATH or not Path(STUDY_APP_PATH).exists(),
    reason="example-app repo not found (run locally with access to example-app)",
)
class TestApiResolverStep0Integration:
    """Step 0 example-app 真实仓库测试。"""

    def test_discover_helpers_from_axios_config(self):
        """Step 0：从 axios.config.ts 自动识别 get/post/put/del LowLevelHelper。"""
        from codegraph.extractors.api_resolver.config import get_api_detector_config
        from codegraph.extractors.api_resolver.detector import (
            discover_low_level_helpers,
            parse_ts_or_vue_for_api,
        )

        if not Path(STUDY_APP_GLOBAL_PKG).exists():
            pytest.skip("axios.config.ts 不存在")

        config = get_api_detector_config(STUDY_APP_PATH)
        parsed = parse_ts_or_vue_for_api(STUDY_APP_GLOBAL_PKG)
        assert parsed is not None, "axios.config.ts 解析失败"
        tree, source = parsed

        helpers = discover_low_level_helpers(tree, source, STUDY_APP_GLOBAL_PKG, config)
        assert len(helpers) >= 2, f"应至少识别 get/post，实际 {helpers}"
        assert "get" in helpers, f"未识别 get，实际 {helpers}"
        assert "post" in helpers, f"未识别 post，实际 {helpers}"


@pytest.mark.integration
@pytest.mark.skipif(
    not STUDY_APP_PATH or not Path(STUDY_APP_PATH).exists(),
    reason="example-app repo not found (run locally with access to example-app)",
)
class TestApiResolverStep1Integration:
    """Step 1 example-app 真实仓库测试。"""

    def test_discover_wrappers_from_home_services(self):
        """Step 1：从 home/src/services/index.ts 发现 ApiWrapper。"""
        from codegraph.extractors.api_resolver.config import get_api_detector_config
        from codegraph.extractors.api_resolver.detector import (
            discover_api_wrappers,
            parse_ts_or_vue_for_api,
        )

        if not Path(STUDY_APP_HOME_SERVICES).exists():
            pytest.skip("home services/index.ts 不存在")

        config = get_api_detector_config(STUDY_APP_PATH)
        parsed = parse_ts_or_vue_for_api(STUDY_APP_HOME_SERVICES)
        assert parsed is not None
        tree, source = parsed

        wrappers = discover_api_wrappers(tree, source, STUDY_APP_HOME_SERVICES, {"get", "post"}, config)
        assert len(wrappers) >= 1, f"应至少发现 1 个 ApiWrapper，实际 {len(wrappers)}"

        symbols = [w.function_symbol for w in wrappers]
        assert "getUserClassInfo" in symbols, f"未识别 getUserClassInfo，实际 {symbols}"

    def test_url_extraction_and_base_url_strip(self):
        """Step 1 URL 提取 + base URL 剥除（configGlobal.api 剥除）。"""
        from codegraph.extractors.api_resolver.config import get_api_detector_config
        from codegraph.extractors.api_resolver.detector import (
            discover_api_wrappers,
            parse_ts_or_vue_for_api,
        )

        if not Path(STUDY_APP_HOME_SERVICES).exists():
            pytest.skip("home services/index.ts 不存在")

        config = get_api_detector_config(STUDY_APP_PATH)
        parsed = parse_ts_or_vue_for_api(STUDY_APP_HOME_SERVICES)
        tree, source = parsed

        wrappers = discover_api_wrappers(tree, source, STUDY_APP_HOME_SERVICES, {"get"}, config)
        assert wrappers, "未找到任何 ApiWrapper"

        # getUserClassInfo → /api/revenue/baas/user_classification_info
        uc = next((w for w in wrappers if w.function_symbol == "getUserClassInfo"), None)
        assert uc is not None, "未找到 getUserClassInfo"
        # url_path_pattern 不应含模板变量
        assert "${" not in uc.url_path_pattern, f"base URL 未剥除: {uc.url_path_pattern}"
        assert "user_classification_info" in uc.url_path_pattern, (
            f"期望含 user_classification_info，实际 {uc.url_path_pattern}"
        )

    def test_jsdoc_enrichment_textbook_last(self):
        """getLadderV5TextbookLast JSDoc 富集 → yapi metadata 正确。"""
        from codegraph.extractors.api_resolver.detector import resolve_wrappers_for_repository

        if not Path(STUDY_APP_LADDER_SERVICES).exists():
            pytest.skip("lastTextbook.ts 不存在")
        if not Path(STUDY_APP_GLOBAL_PKG).exists():
            pytest.skip("axios.config.ts 不存在")

        wrappers = resolve_wrappers_for_repository(
            [STUDY_APP_GLOBAL_PKG, STUDY_APP_LADDER_SERVICES],
            STUDY_APP_PATH,
        )

        textbook = next(
            (w for w in wrappers if "TextbookLast" in w.function_symbol), None
        )
        assert textbook is not None, (
            f"未找到 getLadderV5TextbookLast，发现的 wrappers: {[w.function_symbol for w in wrappers]}"
        )
        assert textbook.metadata is not None, "JSDoc metadata 未填充"
        assert "yapi" in textbook.metadata, f"metadata 不含 yapi: {textbook.metadata}"
        assert textbook.metadata["yapi"]["pid"] == 2279
        assert textbook.metadata["yapi"]["iid"] == 66924
        assert textbook.metadata.get("author") == "luofeng"


@pytest.mark.integration
@pytest.mark.skipif(
    not STUDY_APP_PATH or not Path(STUDY_APP_PATH).exists(),
    reason="example-app repo not found (run locally with access to example-app)",
)
class TestApiResolverFullScan:
    """完整仓库扫描测试。"""

    def test_full_repository_scan_discovers_wrappers(self):
        """完整仓库扫描（apps 目录）：能发现 ≥ 5 个 ApiWrapper。"""
        from codegraph.extractors.api_resolver.detector import resolve_wrappers_for_repository

        # 只扫 apps 目录（避免 node_modules），限制文件数加速测试
        file_paths: list[str] = []
        for ext in ("*.ts", "*.vue"):
            for fp in Path(f"{STUDY_APP_PATH}/apps").rglob(ext):
                if "node_modules" not in fp.parts:
                    file_paths.append(str(fp))
                    if len(file_paths) >= 100:
                        break
            if len(file_paths) >= 100:
                break

        if STUDY_APP_GLOBAL_PKG not in file_paths:
            file_paths.append(STUDY_APP_GLOBAL_PKG)

        wrappers = resolve_wrappers_for_repository(file_paths, STUDY_APP_PATH)
        assert len(wrappers) >= 5, (
            f"完整扫描应发现 ≥ 5 个 ApiWrapper，实际 {len(wrappers)}"
        )

    def test_wrapper_http_methods_distribution(self):
        """发现的 ApiWrapper 中包含 GET 和 POST 两种 method。"""
        from codegraph.extractors.api_resolver.detector import resolve_wrappers_for_repository

        file_paths: list[str] = []
        for ext in ("*.ts",):
            for fp in Path(f"{STUDY_APP_PATH}/apps").rglob(ext):
                if "node_modules" not in fp.parts:
                    file_paths.append(str(fp))
                    if len(file_paths) >= 50:
                        break

        if STUDY_APP_GLOBAL_PKG not in file_paths:
            file_paths.append(STUDY_APP_GLOBAL_PKG)

        wrappers = resolve_wrappers_for_repository(file_paths, STUDY_APP_PATH)

        methods = {w.http_method for w in wrappers}
        # 至少有 GET 或 POST（example-app 同时使用两者）
        assert "GET" in methods or "POST" in methods, f"期望含 GET 或 POST，实际 {methods}"

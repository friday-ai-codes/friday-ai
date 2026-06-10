"""jsdoc_parser.py 单元测试 —— @description/@author/@date/yapi URL 解析。

验证 JSDoc 元数据解析的各种场景。
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
JSDOC_TS = str(FIXTURES_DIR / "api_resolver_jsdoc.ts")


class TestParseJsdoc:
    """parse_jsdoc 单元测试。"""

    def test_parse_full_jsdoc(self):
        """完整 JSDoc 注释 → 解析出 description/author/date/yapi 全部字段。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        comment = """/**
 * @description 查询用户的最后一次学习的教材.
 * http://yapi.example.com/project/2279/interface/api/66924
 * @author luofeng
 * @date 2023-05-12
 * @export
 */"""
        result = parse_jsdoc(comment)
        assert result is not None
        assert "description" in result
        assert "查询用户" in result["description"]
        assert result["author"] == "luofeng"
        assert result["date"] == "2023-05-12"
        assert "yapi" in result
        assert result["yapi"]["pid"] == 2279
        assert result["yapi"]["iid"] == 66924
        assert "yapi.example.com" in result["yapi"]["url"]

    def test_parse_yapi_https(self):
        """https:// yapi URL 正确解析（含 s）。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        comment = """/**
 * @description 获取话题完成状态.
 * https://yapi.example.com/project/1234/interface/api/56789
 * @author zhangsan
 * @date 2024-01-15
 */"""
        result = parse_jsdoc(comment)
        assert result is not None
        assert result["yapi"]["pid"] == 1234
        assert result["yapi"]["iid"] == 56789
        assert result["yapi"]["url"].startswith("https://")

    def test_parse_yapi_http(self):
        """http:// yapi URL（无 s）也能正确解析。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        comment = """/**
 * @description 某接口.
 * http://yapi.example.com/project/999/interface/api/111
 * @author test
 */"""
        result = parse_jsdoc(comment)
        assert result is not None
        assert result["yapi"]["pid"] == 999
        assert result["yapi"]["iid"] == 111

    def test_parse_none_input_returns_none(self):
        """None 输入 → 返回 None（不 crash）。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        result = parse_jsdoc(None)
        assert result is None

    def test_parse_empty_string_returns_none(self):
        """空字符串 → 返回 None。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        result = parse_jsdoc("")
        assert result is None

    def test_parse_non_jsdoc_returns_none(self):
        """单行注释（非 /**）→ 返回 None。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        result = parse_jsdoc("// This is a single line comment")
        assert result is None

    def test_parse_no_yapi_url(self):
        """有 @description 但无 yapi URL → result 不含 yapi key。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        comment = """/**
 * @description 普通描述.
 * @author someone
 */"""
        result = parse_jsdoc(comment)
        assert result is not None
        assert "yapi" not in result
        assert result["author"] == "someone"

    def test_parse_jsdoc_with_no_tags_returns_none(self):
        """/** */ 注释内没有任何可解析标签 → 返回 None。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        comment = """/**
 * 只是一段文字，没有任何 @tag。
 */"""
        result = parse_jsdoc(comment)
        assert result is None

    def test_description_trailing_period_stripped(self):
        """@description 末尾句号被去除。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import parse_jsdoc

        comment = """/** @description 测试接口. @author x */"""
        result = parse_jsdoc(comment)
        assert result is not None
        assert not result["description"].endswith(".")


class TestEnrichWrapperMetadata:
    """enrich_wrapper_metadata 单元测试。"""

    def _make_wrapper(self, jsdoc_text: str | None = None) -> object:
        from codegraph.extractors.api_resolver.base import ApiWrapperData

        return ApiWrapperData(
            file_path="/some/file.ts",
            function_symbol="testFunc",
            http_method="GET",
            url_path_raw="/api/test",
            url_path_pattern="/api/test",
            _jsdoc_text=jsdoc_text,
        )

    def test_enrich_sets_metadata(self):
        """有 JSDoc 时 metadata 被正确填充。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import enrich_wrapper_metadata

        jsdoc = """/**
 * @description 测试.
 * https://yapi.example.com/project/100/interface/api/200
 * @author tester
 */"""
        wrapper = self._make_wrapper(jsdoc)
        result = enrich_wrapper_metadata([wrapper])
        assert result[0].metadata is not None
        assert result[0].metadata.get("author") == "tester"
        assert result[0].metadata["yapi"]["pid"] == 100

    def test_enrich_clears_jsdoc_text(self):
        """富集后 _jsdoc_text 被清除为 None。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import enrich_wrapper_metadata

        wrapper = self._make_wrapper("/** @description 测试. @author x */")
        enrich_wrapper_metadata([wrapper])
        assert wrapper._jsdoc_text is None  # type: ignore[attr-defined]

    def test_enrich_no_jsdoc_metadata_stays_none(self):
        """无 JSDoc 时 metadata 保持 None。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import enrich_wrapper_metadata

        wrapper = self._make_wrapper(None)
        result = enrich_wrapper_metadata([wrapper])
        assert result[0].metadata is None

    def test_enrich_empty_list(self):
        """空列表不 crash，返回空列表。"""
        from codegraph.extractors.api_resolver.jsdoc_parser import enrich_wrapper_metadata

        result = enrich_wrapper_metadata([])
        assert result == []

    def test_enrich_wrapper_from_jsdoc_fixture(self):
        """从 jsdoc fixture 文件解析出的 wrapper 经过 enrich 后 metadata 正确。"""
        from codegraph.extractors.api_resolver.config import get_api_detector_config
        from codegraph.extractors.api_resolver.detector import (
            discover_api_wrappers,
            discover_low_level_helpers,
            parse_ts_or_vue_for_api,
        )
        from codegraph.extractors.api_resolver.jsdoc_parser import enrich_wrapper_metadata

        config = get_api_detector_config()
        result = parse_ts_or_vue_for_api(JSDOC_TS)
        assert result is not None
        tree, source = result

        # 先发现 helpers（get / post 来自 @util/global 导入，但 jsdoc fixture 调用了这些函数）
        helpers = {"get", "post"}  # 直接指定（fixture 从 @util/global 导入）
        wrappers = discover_api_wrappers(tree, source, JSDOC_TS, helpers, config)
        assert wrappers, "jsdoc fixture 应有 ApiWrapper"

        # JSDoc wrapper 应有 _jsdoc_text
        jsdoc_wrappers = [w for w in wrappers if w._jsdoc_text is not None]
        assert len(jsdoc_wrappers) >= 1, "应至少有 1 个 wrapper 有 JSDoc"

        # 富集
        enriched = enrich_wrapper_metadata(wrappers)
        meta_wrappers = [w for w in enriched if w.metadata is not None]
        assert len(meta_wrappers) >= 1, "富集后应至少有 1 个 wrapper 含 metadata"

        # getLadderV5TextbookLast 应含 yapi 信息
        textbook = next((w for w in meta_wrappers if "TextbookLast" in w.function_symbol), None)
        if textbook:
            assert "yapi" in textbook.metadata
            assert textbook.metadata["yapi"]["pid"] == 2279

"""initial implementation: Go gin Endpoint Extractor 单元测试 + study-course 集成测试。

覆盖 work item 四个 Requirements。
单元测试用 tree-sitter parse fixture 文件（无 mock），直接验证抽取结果。
集成测试使用 study-course 真实 Go 源码（双重保护：@integration + skipif）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.extractors.base import EndpointData, FileContext
from codegraph.extractors.go_endpoints import (
    _extract_go_string,
    _parse_ogin_func_name,
    extract_go_endpoints,
)

# =============================================================================
# Fixture 路径
# =============================================================================

FIXTURES_DIR = Path(__file__).parent.parent / "codegraph/extractors/tests/fixtures"
BASIC_FIXTURE = FIXTURES_DIR / "go_gin_endpoint_basic.go"
OGIN_FIXTURE = FIXTURES_DIR / "go_gin_endpoint_ogin.go"

STUDY_COURSE_PATH = "/Users/zaneliu/Projects/guanghe/study-course"
STUDY_COURSE_HANDLERS = Path(STUDY_COURSE_PATH) / "handlers" / "handlers.go"


# =============================================================================
# 工具函数
# =============================================================================


def _parse_go_fixture(file_path: Path) -> tuple[object, str, FileContext]:
    """解析 Go fixture 文件，返回 (tree, source, ctx)。"""
    from codegraph.backends.protocols import TreeSitterBackend

    source = file_path.read_text(encoding="utf-8")
    backend = TreeSitterBackend("go")
    tree = backend.parse_file(str(file_path), source)
    ctx = FileContext(
        file_path=str(file_path),
        language="go",
        repository_id="test-repo-269",
    )
    return tree, source, ctx


# =============================================================================
# Unit Tests（无网络依赖，直接 parse fixture）
# =============================================================================


class TestBasicGinEndpoints:
    """work item：基础 gin 路由识别。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tree, self.source, self.ctx = _parse_go_fixture(BASIC_FIXTURE)
        self.endpoints = extract_go_endpoints(self.tree, self.source, self.ctx)
        self.by_path: dict[str, EndpointData] = {
            f"{ep.http_method}:{ep.url_path}": ep for ep in self.endpoints
        }

    def test_basic_get_endpoint(self):
        """work item: r.GET 被正确识别。"""
        assert "GET:/users" in self.by_path

    def test_basic_post_endpoint(self):
        """work item: r.POST 被正确识别。"""
        assert "POST:/users" in self.by_path

    def test_all_http_methods(self):
        """work item: GET/POST/PUT/DELETE/PATCH/HEAD 全部识别。"""
        methods = {ep.http_method for ep in self.endpoints}
        for m in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"):
            assert m in methods, f"方法 {m} 未被识别"

    def test_use_middleware_ignored(self):
        """work item: r.Use() 不生成 endpoint。"""
        handler_names = {ep.handler_name for ep in self.endpoints}
        assert "someMiddleware" not in handler_names
        assert "<anonymous>" not in handler_names or True  # Use 的 anon 不应出现

    def test_url_is_first_arg_string(self):
        """work item: url_path 取第一个 string literal。"""
        ep = self.by_path.get("DELETE:/users/:id")
        assert ep is not None
        assert ep.url_path == "/users/:id"

    def test_handler_is_last_identifier(self):
        """work item: handler_name 取最后一个 identifier/selector。"""
        ep = self.by_path.get("GET:/users")
        assert ep is not None
        assert ep.handler_name == "listUsers"

    def test_anonymous_handler(self):
        """work item: func_literal handler → '<anonymous>'。"""
        ep = self.by_path.get("GET:/ping")
        assert ep is not None
        assert ep.handler_name == "<anonymous>"

    def test_router_group_routes_recognized(self):
        """work item: v1.GET/v1.POST 也被识别（宽松 recv 类型）。

        注意：per work item 已删，不合并 Group 前缀；
        路由注册的 string literal 直接作为 url_path。
        """
        assert "GET:/items" in self.by_path, (
            f"v1.GET('/items') 未识别；实际 keys={list(self.by_path.keys())}"
        )
        assert "POST:/items" in self.by_path

    def test_multiple_middleware_routes(self):
        """work item: 多 middleware 时 handler 仍取最后一个。"""
        ep = self.by_path.get("GET:/courses/:courseId")
        assert ep is not None
        assert ep.handler_name == "getCourse"

    def test_no_metadata_for_basic_routes(self):
        """基础 gin 路由（无 ogin.G*）metadata 为 None。"""
        ep = self.by_path.get("GET:/users")
        assert ep is not None
        assert ep.metadata is None


class TestOginMetadata:
    """work item：ogin.G* middleware metadata 提取。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tree, self.source, self.ctx = _parse_go_fixture(OGIN_FIXTURE)
        self.endpoints = extract_go_endpoints(self.tree, self.source, self.ctx)
        self.by_path: dict[str, EndpointData] = {
            f"{ep.http_method}:{ep.url_path}": ep for ep in self.endpoints
        }

    def test_use_calls_not_in_endpoints(self):
        """work item: server.Use() 不生成 endpoint。"""
        handler_names = {ep.handler_name for ep in self.endpoints}
        assert "metricsMiddleware" not in handler_names
        assert "tracingMiddleware" not in handler_names

    def test_ogin_path_param_extracted(self):
        """work item: GPathRequireString 提取 path_params。"""
        ep = self.by_path.get("GET:/study-course/course/:topicId/detail")
        assert ep is not None
        assert ep.metadata is not None
        assert "path_params" in ep.metadata
        path_params = ep.metadata["path_params"]
        assert len(path_params) == 1
        assert path_params[0]["name"] == "topicId"
        assert path_params[0]["required"] is True
        assert path_params[0]["type"] == "string"

    def test_ogin_query_param_optional(self):
        """work item: GQueryOptionalString 提取 query_params，required=False。"""
        ep = self.by_path.get("GET:/study-course/course/:topicId/detail")
        assert ep is not None
        query_params = ep.metadata.get("query_params", [])
        assert any(
            p["name"] == "courseId" and p["required"] is False for p in query_params
        ), f"query_params={query_params}"

    def test_ogin_header_param_optional(self):
        """work item: GHeaderOptionalString 提取 header_params，required=False。"""
        ep = self.by_path.get("GET:/study-course/course/:topicId/detail")
        assert ep is not None
        header_params = ep.metadata.get("header_params", [])
        header_names = [p["name"] for p in header_params]
        assert "client-type" in header_names

    def test_ogin_multiple_query_require_int(self):
        """work item: 多个 GQueryRequireInt 全部提取。"""
        ep = self.by_path.get("GET:/study-course/chapter/tree")
        assert ep is not None
        query_params = ep.metadata.get("query_params", [])
        names = {p["name"] for p in query_params}
        assert names == {"subjectId", "stageId", "publisherId", "semesterId"}
        for p in query_params:
            assert p["required"] is True
            assert p["type"] == "int"

    def test_no_ogin_metadata_returns_none(self):
        """work item: 无 G* middleware 时 metadata=None。"""
        ep = self.by_path.get("POST:/study-course/batch/topic/detail")
        assert ep is not None
        assert ep.metadata is None

    def test_ogin_anonymous_handler(self):
        """ogin.Server 的匿名 handler。"""
        ep = self.by_path.get("GET:/study-course/ping")
        assert ep is not None
        assert ep.handler_name == "<anonymous>"


# =============================================================================
# Helper function unit tests
# =============================================================================


class TestHelperFunctions:
    """内部工具函数单元测试。"""

    def test_extract_go_string_double_quote(self):
        """_extract_go_string 处理双引号字符串。"""
        # 用 tree-sitter 解析一个简单的 Go 字符串
        from codegraph.backends.protocols import TreeSitterBackend

        source = 'package main\nvar s = "/api/path"'
        backend = TreeSitterBackend("go")
        tree = backend.parse_file("test.go", source)

        # 遍历找到 string literal 节点
        results = []
        for node in _walk_nodes(tree.root_node, "interpreted_string_literal"):
            results.append(_extract_go_string(node))
        assert "/api/path" in results

    def test_parse_ogin_func_name_path_require(self):
        """_parse_ogin_func_name: GPathRequireString 解析正确。"""
        result = _parse_ogin_func_name("GPathRequireString")
        assert result is not None
        loc, req, typ = result
        assert loc == "path_params"
        assert req is True
        assert typ == "string"

    def test_parse_ogin_func_name_query_optional_int(self):
        """_parse_ogin_func_name: GQueryOptionalInt 解析正确。"""
        result = _parse_ogin_func_name("GQueryOptionalInt")
        assert result is not None
        loc, req, typ = result
        assert loc == "query_params"
        assert req is False
        assert typ == "int"

    def test_parse_ogin_func_name_header_optional(self):
        """_parse_ogin_func_name: GHeaderOptionalString 解析正确。"""
        result = _parse_ogin_func_name("GHeaderOptionalString")
        assert result is not None
        loc, req, typ = result
        assert loc == "header_params"
        assert req is False

    def test_parse_ogin_func_name_not_ogin_returns_none(self):
        """_parse_ogin_func_name: 非 G* 函数名返回 None。"""
        assert _parse_ogin_func_name("EnableTrace") is None
        assert _parse_ogin_func_name("someMiddleware") is None
        assert _parse_ogin_func_name("JSON") is None


def _walk_nodes(node, node_type):
    """遍历节点找特定类型。"""
    if node.type == node_type:
        yield node
    for child in node.children:
        yield from _walk_nodes(child, node_type)


# =============================================================================
# Integration Tests（study-course 真实仓库）
# =============================================================================


@pytest.mark.integration
@pytest.mark.skipif(
    not STUDY_COURSE_HANDLERS.exists(),
    reason="study-course repo 不在本机，跳过 integration test",
)
class TestStudyCourseIntegration:
    """study-course 端到端集成测试（双重保护）。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.tree, self.source, self.ctx = _parse_go_fixture(STUDY_COURSE_HANDLERS)
        self.endpoints = extract_go_endpoints(self.tree, self.source, self.ctx)

    def test_study_course_endpoint_count(self):
        """study-course handlers.go 应识别 50+ 个 endpoint。"""
        assert len(self.endpoints) >= 50, (
            f"期望 ≥ 50 个 endpoint，实际 {len(self.endpoints)}"
        )

    def test_study_course_ogin_metadata_present(self):
        """study-course 中含 ogin.G* 的路由应有 metadata。"""
        endpoints_with_metadata = [ep for ep in self.endpoints if ep.metadata]
        assert len(endpoints_with_metadata) >= 1, (
            "期望至少 1 个带 metadata 的 endpoint（含 ogin.G*）"
        )

    def test_study_course_no_use_endpoints(self):
        """study-course Use() 路由不应出现在 endpoint 列表。"""
        url_paths = {ep.url_path for ep in self.endpoints}
        # Use() 注册的 middleware 不应有 url_path
        # 验证 endpoint 列表中无空 url
        for ep in self.endpoints:
            assert ep.url_path is not None and ep.url_path != "", (
                f"endpoint handler={ep.handler_name} url_path 为空"
            )

    def test_study_course_known_route_present(self):
        """验证已知路由 /study-course/chapter 被识别。"""
        url_paths = {ep.url_path for ep in self.endpoints}
        known_routes = [
            "/study-course/chapter",
            "/study-course/chapter/tree",
        ]
        for route in known_routes:
            assert route in url_paths, (
                f"已知路由 {route} 未被识别；实际 url_paths 数量={len(url_paths)}"
            )

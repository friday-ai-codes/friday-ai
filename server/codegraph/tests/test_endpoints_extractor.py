"""Tests for Endpoint extractor ."""
import pytest
class TestEndpointExtractorLayer1:
 """Layer 1: 装饰器函数视图扫描。"""
 def test_api_view_single_method(self, parse_fixture, make_file_context):
 """@api_view(["GET"]) 提取单个 GET 端点。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("django_views.py")
 ctx = make_file_context
 endpoints = extract_endpoints(tree, source, ctx)
 user_list_eps = [ep for ep in endpoints if ep.handler_name == "user_list"]
 assert len(user_list_eps) == 1, \
 f"Expected 1 endpoint for user_list, got {len(user_list_eps)}"
 assert user_list_eps[0].http_method == "GET", \
 f"Expected GET, got {user_list_eps[0].http_method}"
 def test_api_view_multiple_methods(self, parse_fixture, make_file_context):
 """@api_view(["GET", "POST"]) 产生多个端点。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("django_views.py")
 ctx = make_file_context
 endpoints = extract_endpoints(tree, source, ctx)
 user_detail_eps = [ep for ep in endpoints if ep.handler_name == "user_detail"]
 assert len(user_detail_eps) >= 2, \
 f"Expected >= 2 endpoints for user_detail, got {len(user_detail_eps)}"
 methods = {ep.http_method for ep in user_detail_eps}
 assert "GET" in methods, f"Missing GET in {methods}"
 assert "POST" in methods, f"Missing POST in {methods}"
 def test_api_view_delete(self, parse_fixture, make_file_context):
 """@api_view(["DELETE"]) 提取 DELETE 端点。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("django_views.py")
 ctx = make_file_context
 endpoints = extract_endpoints(tree, source, ctx)
 user_delete_eps = [ep for ep in endpoints if ep.handler_name == "user_delete"]
 assert len(user_delete_eps) == 1, \
 f"Expected 1 endpoint for user_delete, got {len(user_delete_eps)}"
 assert user_delete_eps[0].http_method == "DELETE", \
 f"Expected DELETE, got {user_delete_eps[0].http_method}"
 def test_view_type_function_view(self, parse_fixture, make_file_context):
 """@api_view 装饰器 view_type=FUNCTION_VIEW。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("django_views.py")
 ctx = make_file_context
 endpoints = extract_endpoints(tree, source, ctx)
 for ep in endpoints:
 if ep.handler_name in ("user_list", "user_detail", "user_delete"):
 assert ep.view_type == "FUNCTION_VIEW", \
 f"{ep.handler_name}: expected FUNCTION_VIEW, got {ep.view_type}"
 def test_action_decorator(self, parse_fixture, make_file_context):
 """@action(detail=True, methods=["post"]) 提取 POST 端点。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("drf_viewsets.py")
 ctx = make_file_context
 endpoints = extract_endpoints(tree, source, ctx)
 activate_eps = [ep for ep in endpoints if ep.handler_name == "activate"]
 assert len(activate_eps) == 1, \
 f"Expected 1 endpoint for activate, got {len(activate_eps)}"
 assert activate_eps[0].http_method == "POST", \
 f"Expected POST, got {activate_eps[0].http_method}"
 assert activate_eps[0].view_type == "VIEWSET", \
 f"Expected VIEWSET, got {activate_eps[0].view_type}"
 def test_action_decorator_detail_false(self, parse_fixture, make_file_context):
 """@action(detail=False, methods=["get"]) 提取 GET 端点。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("drf_viewsets.py")
 ctx = make_file_context
 endpoints = extract_endpoints(tree, source, ctx)
 recent_eps = [ep for ep in endpoints if ep.handler_name == "recent"]
 assert len(recent_eps) == 1, \
 f"Expected 1 endpoint for recent, got {len(recent_eps)}"
 assert recent_eps[0].http_method == "GET", \
 f"Expected GET, got {recent_eps[0].http_method}"
class TestEndpointExtractorLayer2:
 """Layer 2: URL patterns 扫描。"""
 def test_path_extraction(self, parse_fixture, make_file_context):
 """path 调用提取 URL 路径。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, file_path = parse_fixture("django_urls.py")
 # 需要 file_path 以 urls.py 结尾才能触发 Layer 2
 ctx = make_file_context(file_path=file_path)
 endpoints = extract_endpoints(tree, source, ctx)
 url_paths = {ep.url_path for ep in endpoints if ep.url_path}
 assert any("api/users/" in (p or "") for p in url_paths), \
 f"Expected api/users/ in URL paths: {url_paths}"
 def test_path_with_int_param(self, parse_fixture, make_file_context):
 """path 中 <int:id> 参数保留。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, file_path = parse_fixture("django_urls.py")
 ctx = make_file_context(file_path=file_path)
 endpoints = extract_endpoints(tree, source, ctx)
 url_paths = {ep.url_path for ep in endpoints if ep.url_path}
 int_param_paths = [p for p in url_paths if p and "<int:id>" in p]
 assert len(int_param_paths) >= 1, \
 f"Expected path with <int:id>, got: {url_paths}"
 def test_re_path_extraction(self, parse_fixture, make_file_context):
 """re_path 调用保留正则模式。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, file_path = parse_fixture("django_urls.py")
 ctx = make_file_context(file_path=file_path)
 endpoints = extract_endpoints(tree, source, ctx)
 url_paths = {ep.url_path for ep in endpoints if ep.url_path}
 regex_paths = [p for p in url_paths if p and "^api/legacy" in p]
 assert len(regex_paths) >= 1, \
 f"Expected regex path with ^api/legacy, got: {url_paths}"
 def test_urls_py_required_for_layer2(self, parse_fixture, make_file_context):
 """非 urls.py 文件不触发 Layer 2。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("basic_module.py")
 ctx = make_file_context(file_path="basic_module.py")
 endpoints = extract_endpoints(tree, source, ctx)
 # basic_module.py 无 Django 装饰器，不应产生端点
 # 实际上 Layer 1 也不应有产出（无 @api_view 装饰器）
 assert len(endpoints) == 0, \
 f"Expected 0 endpoints for non-Django file, got {len(endpoints)}"
class TestEndpointExtractorLayer3:
 """Layer 3: ViewSet + Router 注册扫描。"""
 def test_router_registered(self, parse_fixture, make_file_context):
 """router.register 产生端点，handler_name 含 UserViewSet。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, file_path = parse_fixture("django_urls.py")
 ctx = make_file_context(file_path=file_path)
 endpoints = extract_endpoints(tree, source, ctx)
 viewset_eps = [ep for ep in endpoints if "UserViewSet" in ep.handler_name]
 # ModelViewSet 默认有 6 个 actions: list/create/retrieve/update/partial_update/destroy
 assert len(viewset_eps) >= 1, \
 f"Expected at least 1 UserViewSet endpoint, got {len(viewset_eps)}"
 def test_viewset_default_actions(self, parse_fixture, make_file_context):
 """ModelViewSet 产生默认 actions (list/create/retrieve/...)。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, file_path = parse_fixture("django_urls.py")
 ctx = make_file_context(file_path=file_path)
 endpoints = extract_endpoints(tree, source, ctx)
 viewset_eps = [ep for ep in endpoints if "UserViewSet" in ep.handler_name]
 handler_names = {ep.handler_name for ep in viewset_eps}
 assert "UserViewSet.list" in handler_names, f"Missing list action in {handler_names}"
 assert "UserViewSet.create" in handler_names, f"Missing create action in {handler_names}"
 assert "UserViewSet.retrieve" in handler_names, f"Missing retrieve action in {handler_names}"
 def test_url_prefix_in_path(self, parse_fixture, make_file_context):
 """ViewSet 端点 URL 以 router prefix 开头。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, file_path = parse_fixture("django_urls.py")
 ctx = make_file_context(file_path=file_path)
 endpoints = extract_endpoints(tree, source, ctx)
 viewset_eps = [ep for ep in endpoints if "UserViewSet" in ep.handler_name]
 for ep in viewset_eps:
 if ep.url_path:
 assert "/users/" in ep.url_path, \
 f"Expected /users/ in {ep.handler_name} url_path: {ep.url_path}"
class TestEndpointExtractorEdgeCases:
 """边界条件测试。"""
 def test_non_urls_file_returns_no_endpoints(self, parse_fixture, make_file_context):
 """非 Django 文件无端点。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("basic_module.py")
 ctx = make_file_context(file_path="basic_module.py")
 endpoints = extract_endpoints(tree, source, ctx)
 # basic_module.py 无 Django 装饰器
 assert len(endpoints) == 0, \
 f"Expected 0 endpoints for basic_module, got {len(endpoints)}"
 def test_empty_file_returns_empty(self, parse_source, make_file_context):
 """空文件返回空列表。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source = parse_source("")
 ctx = make_file_context
 endpoints = extract_endpoints(tree, source, ctx)
 assert endpoints ==, f"Expected empty, got {len(endpoints)} endpoints"
 def test_deduplication(self, parse_fixture, make_file_context):
 """同一 handler 不重复产生端点。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, file_path = parse_fixture("django_views.py")
 ctx = make_file_context(file_path=file_path)
 endpoints = extract_endpoints(tree, source, ctx)
 # 按 handler_name + http_method 去重
 seen = set
 for ep in endpoints:
 key = (ep.http_method, ep.url_path or "", ep.handler_name, ep.file_path)
 assert key not in seen, f"Duplicate endpoint: {key}"
 seen.add(key)
 def test_line_number_valid(self, parse_fixture, make_file_context):
 """所有端点的 line_number > 0。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, _ = parse_fixture("django_views.py")
 ctx = make_file_context
 endpoints = extract_endpoints(tree, source, ctx)
 for ep in endpoints:
 assert ep.line_number > 0, \
 f"{ep.handler_name}: line_number={ep.line_number} should be > 0"
 def test_file_path_in_output(self, parse_fixture, make_file_context):
 """所有 EndpointData 的 file_path 等于 ctx.file_path。"""
 from codegraph.extractors.endpoints import extract_endpoints
 tree, source, file_path = parse_fixture("django_views.py")
 ctx = make_file_context(file_path=file_path)
 endpoints = extract_endpoints(tree, source, ctx)
 for ep in endpoints:
 assert ep.file_path == file_path, \
 f"{ep.handler_name}: expected file_path={file_path}, got {ep.file_path}"

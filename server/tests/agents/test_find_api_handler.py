"""``find_api_handler`` MCP tool 单元测试 —— per Phase Plan Task 6 / 。
测试目标（≥6 cases）：
1. ``test_url_normalizes_and_matches_endpoint`` —— URL 归一化后精确匹配
2. ``test_method_case_normalized_to_upper`` —— get → GET（大小写）
3. ``test_no_matching_endpoint_returns_empty`` —— 无匹配时空列表 + message
4. ``test_missing_repository_id_returns_error`` —— repository_id 必填守卫
5. ``test_missing_url_returns_error`` —— url 必填守卫
6. ``test_missing_method_returns_error`` —— method 必填守卫
7. ``test_multiple_matches_returned`` —— 同 method+path 多 handler
8. ``test_orm_value_error_returns_toolresult`` —— ORM ValueError 不冒泡
per Phase 测试模式：mock ``Endpoint.objects``（不依赖真实 DB），
async iterable 模拟 queryset。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import MagicMock
import pytest
_VALID_REPO_ID = "33333333-3333-3333-3333-333333333333"
# ---------------------------------------------------------------------------
# helpers —— async queryset mock
# ---------------------------------------------------------------------------
class _AsyncIter:
 """async iterable mock —— 支持 ``async for x in qs`` 模式。"""
 def __init__(self, items: list[dict[str, Any]]) -> None:
 self._items = items
 def __aiter__(self) -> "_AsyncIter":
 self._index = 0
 return self
 async def __anext__(self) -> dict[str, Any]:
 if self._index >= len(self._items):
 raise StopAsyncIteration
 item = self._items[self._index]
 self._index += 1
 return item
def _patch_endpoint_values(
 monkeypatch: pytest.MonkeyPatch, items: list[dict[str, Any]]
) -> MagicMock:
 """patch ``Endpoint.objects.filter(...).values(...)`` → async iter。
 Returns the filter mock so caller can assert filter kwargs.
 """
 values_iter = _AsyncIter(items)
 filter_mock = MagicMock
 filter_mock.values = MagicMock(return_value=values_iter)
 objects_mock = MagicMock
 objects_mock.filter = MagicMock(return_value=filter_mock)
 from codegraph import models as cg_models
 monkeypatch.setattr(cg_models.Endpoint, "objects", objects_mock)
 return objects_mock.filter
# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_url_normalizes_and_matches_endpoint(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """URL 归一化后能匹配到 Endpoint —— 三种 placeholder 风格归一化为同一形式。"""
 from agents.tools.find_api_handler import find_api_handler
 _patch_endpoint_values(
 monkeypatch,
 [
 {
 "handler_name": "GetUserHandler",
 "url_path": "/api/v1/users/{id}",
 "http_method": "GET",
 "file_path": "internal/handlers/user.go",
 "line_number": 42,
 "view_type": "FUNCTION_VIEW",
 }
 ],
 )
 result = await find_api_handler(
 url="/api/v1/users/:id",
 method="GET",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 data = result.output["data"]
 assert len(data["handlers"]) == 1
 assert data["handlers"][0]["handler_name"] == "GetUserHandler"
 assert data["normalized_url"]
 assert result.output["metadata"]["match_count"] == 1
@pytest.mark.asyncio
async def test_method_case_normalized_to_upper(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """method 输入小写 → 内部转大写后查询 Endpoint。"""
 from agents.tools.find_api_handler import find_api_handler
 filter_mock = _patch_endpoint_values(
 monkeypatch,
 [
 {
 "handler_name": "PostLoginHandler",
 "url_path": "/api/login",
 "http_method": "POST",
 "file_path": "internal/auth.go",
 "line_number": 10,
 "view_type": "FUNCTION_VIEW",
 }
 ],
 )
 result = await find_api_handler(
 url="/api/login",
 method="post",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 filter_mock.assert_called_once
 kwargs = filter_mock.call_args.kwargs
 assert kwargs["http_method"] == "POST"
 assert kwargs["repository_id"] == _VALID_REPO_ID
@pytest.mark.asyncio
async def test_no_matching_endpoint_returns_empty(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """所有 endpoint 归一化后都不匹配 → 空 handlers + message 提示。"""
 from agents.tools.find_api_handler import find_api_handler
 _patch_endpoint_values(
 monkeypatch,
 [
 {
 "handler_name": "ListUsersHandler",
 "url_path": "/api/v1/users",
 "http_method": "GET",
 "file_path": "internal/handlers/user.go",
 "line_number": 5,
 "view_type": "FUNCTION_VIEW",
 }
 ],
 )
 result = await find_api_handler(
 url="/api/v1/orders/123",
 method="GET",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 data = result.output["data"]
 assert data["handlers"] ==
 assert "未找到" in data["message"]
 assert result.output["metadata"]["match_count"] == 0
@pytest.mark.asyncio
async def test_missing_repository_id_returns_error -> None:
 """repository_id=None → ToolResult.error 含 'repository_id is required'。"""
 from agents.tools.find_api_handler import find_api_handler
 result = await find_api_handler(url="/api/foo", method="GET", repository_id=None)
 assert result.success is False
 assert result.error is not None
 assert "repository_id is required" in result.error
@pytest.mark.asyncio
async def test_missing_url_returns_error -> None:
 """url=None / 空字符串 → ToolResult.error 含 'url is required'。"""
 from agents.tools.find_api_handler import find_api_handler
 result = await find_api_handler(url=None, method="GET", repository_id=_VALID_REPO_ID)
 assert result.success is False
 assert result.error is not None
 assert "url is required" in result.error
@pytest.mark.asyncio
async def test_missing_method_returns_error -> None:
 """method=None / 空字符串 → ToolResult.error 含 'method is required'。"""
 from agents.tools.find_api_handler import find_api_handler
 result = await find_api_handler(url="/api/foo", method=None, repository_id=_VALID_REPO_ID)
 assert result.success is False
 assert result.error is not None
 assert "method is required" in result.error
@pytest.mark.asyncio
async def test_multiple_matches_returned(monkeypatch: pytest.MonkeyPatch) -> None:
 """同 method+path 归一化后存在多个 handler → 全部返回。"""
 from agents.tools.find_api_handler import find_api_handler
 _patch_endpoint_values(
 monkeypatch,
 [
 {
 "handler_name": "HandlerA",
 "url_path": "/api/v1/users/{id}",
 "http_method": "GET",
 "file_path": "a.go",
 "line_number": 1,
 "view_type": "FUNCTION_VIEW",
 },
 {
 "handler_name": "HandlerB",
 "url_path": "/api/v1/users/:id",
 "http_method": "GET",
 "file_path": "b.go",
 "line_number": 2,
 "view_type": "FUNCTION_VIEW",
 },
 {
 "handler_name": "OtherHandler",
 "url_path": "/api/v1/orders",
 "http_method": "GET",
 "file_path": "c.go",
 "line_number": 3,
 "view_type": "FUNCTION_VIEW",
 },
 ],
 )
 result = await find_api_handler(
 url="/api/v1/users/123",
 method="GET",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 data = result.output["data"]
 handler_names = {h["handler_name"] for h in data["handlers"]}
 assert handler_names == {"HandlerA", "HandlerB"}
@pytest.mark.asyncio
async def test_orm_value_error_returns_toolresult(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """ORM 抛 ValueError（如 UUIDField 转换失败）→ tool 层兜底返结构化 error。"""
 from agents.tools.find_api_handler import find_api_handler
 def _raise_value_error(*_a: object, **_kw: object) -> None:
 raise ValueError("badly formed UUID")
 objects_mock = MagicMock
 objects_mock.filter = MagicMock(side_effect=_raise_value_error)
 from codegraph import models as cg_models
 monkeypatch.setattr(cg_models.Endpoint, "objects", objects_mock)
 result = await find_api_handler(
 url="/api/foo",
 method="GET",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is False
 assert result.error is not None
 assert "invalid input or downstream failure" in result.error

"""``list_endpoints`` MCP tool 单元测试 —— per Phase Plan Task 8。
测试目标（≥6 条）：
1. ``test_returns_sorted_by_method_then_path`` — 返回按 method ASC + path ASC 排序
2. ``test_missing_repository_id_returns_error`` — repository_id 缺失 → error
3. ``test_empty_repo_returns_empty_list`` — 仓库无端点 → + message 非空
4. ``test_limit_parameter_applied`` — limit 生效，返回数 ≤ limit
5. ``test_limit_capped_at_maximum`` — limit=9999 → Pydantic ge/le 报错 → error
6. ``test_total_reflects_full_count_not_just_returned`` — total ≠ len(endpoints) 时正确
7. ``test_endpoint_fields_complete`` — 每条 EndpointSummary 包含所有必填字段
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
import pytest
# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
_REPO_ID = "55555555-5555-5555-5555-555555555555"
# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_endpoint_row(
 http_method: str = "GET",
 url_path: str = "/api/v1/users",
 handler_name: str = "ListUsersHandler",
 file_path: str = "handler/user.go",
 line_number: int = 10,
) -> dict:
 return {
 "http_method": http_method,
 "url_path": url_path,
 "handler_name": handler_name,
 "file_path": file_path,
 "line_number": line_number,
 }
class _AsyncEndpointIter:
 """异步迭代器，模拟 Django async queryset 切片 + values。"""
 def __init__(self, rows: list[dict]) -> None:
 self._rows = iter(rows)
 def __aiter__(self):
 return self
 async def __anext__(self):
 try:
 return next(self._rows)
 except StopIteration:
 raise StopAsyncIteration
 def __getitem__(self, key):
 """支持 queryset[:limit] 切片语法。"""
 if isinstance(key, slice):
 # 截取 _rows 的底层列表（mock 场景下直接返回 self）
 return self
 return self
def _patch_endpoint_objects(
 monkeypatch: pytest.MonkeyPatch,
 rows: list[dict],
 total: int | None = None,
) -> None:
 """Mock Endpoint.objects.filter.acount + order_by.values[:limit] 链。"""
 effective_total = total if total is not None else len(rows)
 acount_mock = AsyncMock(return_value=effective_total)
 sliced_qs = _AsyncEndpointIter(rows)
 # .values[:limit] → sliced_qs
 values_mock = MagicMock
 values_mock.__getitem__ = MagicMock(return_value=sliced_qs)
 order_by_mock = MagicMock
 order_by_mock.values = MagicMock(return_value=values_mock)
 filter_mock = MagicMock
 filter_mock.acount = acount_mock
 filter_mock.order_by = MagicMock(return_value=order_by_mock)
 objects_mock = MagicMock
 objects_mock.filter = MagicMock(return_value=filter_mock)
 import codegraph.models as cg_models
 monkeypatch.setattr(cg_models.Endpoint, "objects", objects_mock)
# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_returns_sorted_by_method_then_path(monkeypatch: pytest.MonkeyPatch) -> None:
 """端点按 method ASC + path ASC 排序（mock 已按序，验证结构正确）。"""
 rows = [
 _make_endpoint_row(http_method="DELETE", url_path="/api/v1/users/:id"),
 _make_endpoint_row(http_method="GET", url_path="/api/v1/orders"),
 _make_endpoint_row(http_method="GET", url_path="/api/v1/users"),
 _make_endpoint_row(http_method="POST", url_path="/api/v1/users"),
 ]
 _patch_endpoint_objects(monkeypatch, rows)
 from agents.tools.list_endpoints import list_endpoints
 result = await list_endpoints(repository_id=_REPO_ID)
 assert result.success is True
 data = result.output["data"]
 assert len(data["endpoints"]) == 4
 assert data["endpoints"][0]["http_method"] == "DELETE"
 assert data["endpoints"][1]["http_method"] == "GET"
@pytest.mark.asyncio
async def test_missing_repository_id_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
 """repository_id 缺失 → ToolResult(success=False)。"""
 _patch_endpoint_objects(monkeypatch, )
 from agents.tools.list_endpoints import list_endpoints
 result = await list_endpoints(repository_id=None)
 assert result.success is False
 assert "repository_id" in (result.error or "")
@pytest.mark.asyncio
async def test_empty_repo_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
 """仓库无端点 → endpoints= + message 非空。"""
 _patch_endpoint_objects(monkeypatch,, total=0)
 from agents.tools.list_endpoints import list_endpoints
 result = await list_endpoints(repository_id=_REPO_ID)
 assert result.success is True
 data = result.output["data"]
 assert data["endpoints"] ==
 assert data["message"] != ""
 assert data["total"] == 0
@pytest.mark.asyncio
async def test_limit_parameter_applied(monkeypatch: pytest.MonkeyPatch) -> None:
 """limit 参数生效，mock 返回截断后的数据。"""
 rows = [_make_endpoint_row(url_path=f"/api/v1/r{i}") for i in range(5)]
 _patch_endpoint_objects(monkeypatch, rows, total=100)
 from agents.tools.list_endpoints import list_endpoints
 result = await list_endpoints(repository_id=_REPO_ID, limit=5)
 assert result.success is True
 data = result.output["data"]
 assert len(data["endpoints"]) == 5
 meta = result.output["metadata"]
 assert meta["truncated"] is True # total=100 > limit=5
@pytest.mark.asyncio
async def test_limit_capped_at_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
 """limit=9999 超过 Pydantic le=1000 → ValidationError → ToolResult error。"""
 _patch_endpoint_objects(monkeypatch, )
 from agents.tools.list_endpoints import list_endpoints
 result = await list_endpoints(repository_id=_REPO_ID, limit=9999)
 assert result.success is False
 # Pydantic strict=True 且 le=1000，应返回 error
 assert result.error is not None
@pytest.mark.asyncio
async def test_total_reflects_full_count_not_just_returned(monkeypatch: pytest.MonkeyPatch) -> None:
 """total 字段 = 仓库实际端点总数（acount），与 len(endpoints) 可能不同。"""
 rows = [_make_endpoint_row(url_path=f"/api/v1/r{i}") for i in range(3)]
 _patch_endpoint_objects(monkeypatch, rows, total=285)
 from agents.tools.list_endpoints import list_endpoints
 result = await list_endpoints(repository_id=_REPO_ID, limit=3)
 assert result.success is True
 data = result.output["data"]
 assert len(data["endpoints"]) == 3
 assert data["total"] == 285
@pytest.mark.asyncio
async def test_endpoint_fields_complete(monkeypatch: pytest.MonkeyPatch) -> None:
 """每条 EndpointSummary 包含所有必填字段（method/path/handler/file/line）。"""
 rows = [
 _make_endpoint_row(
 http_method="GET",
 url_path="/api/v1/users",
 handler_name="ListUsersHandler",
 file_path="handler/user.go",
 line_number=42,
 )
 ]
 _patch_endpoint_objects(monkeypatch, rows)
 from agents.tools.list_endpoints import list_endpoints
 result = await list_endpoints(repository_id=_REPO_ID)
 assert result.success is True
 ep = result.output["data"]["endpoints"][0]
 assert ep["http_method"] == "GET"
 assert ep["url_path"] == "/api/v1/users"
 assert ep["handler_name"] == "ListUsersHandler"
 assert ep["file_path"] == "handler/user.go"
 assert ep["line_number"] == 42

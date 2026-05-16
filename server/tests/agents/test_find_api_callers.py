"""``find_api_callers`` MCP tool 单元测试 —— per Phase Plan Task 7 / 。
测试目标（≥6 cases）：
1. ``test_handler_to_call_sites_chain`` —— 完整查询链 endpoint → cross_repo → call_site
2. ``test_unknown_handler_returns_empty`` —— 无对应 endpoint → 空 callers + message
3. ``test_no_cross_repo_calls_returns_empty`` —— endpoint 存在但无跨仓调用 → 空列表
4. ``test_multiple_call_sites_returned_sorted`` —— 多个 call site 按 file+line 排序
5. ``test_match_confidence_passed_through`` —— match_confidence 透传
6. ``test_missing_repository_id_returns_error`` —— repository_id 必填守卫
7. ``test_missing_handler_name_returns_error`` —— handler_name 必填守卫
8. ``test_orm_value_error_returns_toolresult`` —— ORM ValueError 兜底
per Phase 测试模式：mock ``Endpoint.objects`` / ``CrossRepoApiCall.objects``。
"""
from __future__ import annotations
from typing import Any
from unittest.mock import MagicMock
import pytest
_VALID_REPO_ID = "44444444-4444-4444-4444-444444444444"
# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class _AsyncIter:
 """async iterable mock。"""
 def __init__(self, items: list[Any]) -> None:
 self._items = items
 def __aiter__(self) -> "_AsyncIter":
 self._index = 0
 return self
 async def __anext__(self) -> Any:
 if self._index >= len(self._items):
 raise StopAsyncIteration
 item = self._items[self._index]
 self._index += 1
 return item
def _patch_endpoint_values_list(
 monkeypatch: pytest.MonkeyPatch, endpoint_ids: list[str]
) -> MagicMock:
 """patch ``Endpoint.objects.filter(...).values_list('id', flat=True)`` async iter。"""
 values_list_iter = _AsyncIter(endpoint_ids)
 filter_mock = MagicMock
 filter_mock.values_list = MagicMock(return_value=values_list_iter)
 objects_mock = MagicMock
 objects_mock.filter = MagicMock(return_value=filter_mock)
 from codegraph import models as cg_models
 monkeypatch.setattr(cg_models.Endpoint, "objects", objects_mock)
 return objects_mock.filter
def _patch_cross_repo_select(
 monkeypatch: pytest.MonkeyPatch, cross_calls: list[Any]
) -> MagicMock:
 """patch ``CrossRepoApiCall.objects.filter(...).select_related(...)`` async iter。"""
 select_iter = _AsyncIter(cross_calls)
 filter_mock = MagicMock
 filter_mock.select_related = MagicMock(return_value=select_iter)
 objects_mock = MagicMock
 objects_mock.filter = MagicMock(return_value=filter_mock)
 from codegraph import models as cg_models
 monkeypatch.setattr(cg_models.CrossRepoApiCall, "objects", objects_mock)
 return objects_mock.filter
def _make_cross_call(
 caller_file: str = "src/api/users.ts",
 caller_function: str = "fetchUser",
 line_number: int = 10,
 api_wrapper_symbol: str = "getUserApi",
 match_confidence: float = 1.0,
) -> MagicMock:
 """构造 CrossRepoApiCall mock（含 select_related call_site + api_wrapper）。"""
 api_wrapper_mock = MagicMock
 api_wrapper_mock.function_symbol = api_wrapper_symbol
 call_site_mock = MagicMock
 call_site_mock.caller_file = caller_file
 call_site_mock.caller_function = caller_function
 call_site_mock.line_number = line_number
 call_site_mock.api_wrapper = api_wrapper_mock
 cross_call_mock = MagicMock
 cross_call_mock.call_site = call_site_mock
 cross_call_mock.match_confidence = match_confidence
 return cross_call_mock
# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_handler_to_call_sites_chain(monkeypatch: pytest.MonkeyPatch) -> None:
 """endpoint → CrossRepoApiCall → ApiCallSite 完整链。"""
 from agents.tools.find_api_callers import find_api_callers
 _patch_endpoint_values_list(monkeypatch, ["ep-uuid-1"])
 _patch_cross_repo_select(
 monkeypatch,
 [
 _make_cross_call(
 caller_file="src/pages/User.vue",
 caller_function="onMounted",
 line_number=42,
 api_wrapper_symbol="getUserApi",
 match_confidence=1.0,
 )
 ],
 )
 result = await find_api_callers(
 handler_name="GetUserHandler",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 data = result.output["data"]
 assert len(data["callers"]) == 1
 caller = data["callers"][0]
 assert caller["caller_file"] == "src/pages/User.vue"
 assert caller["caller_function"] == "onMounted"
 assert caller["line_number"] == 42
 assert caller["api_wrapper_symbol"] == "getUserApi"
 assert caller["match_confidence"] == 1.0
 assert result.output["metadata"]["caller_count"] == 1
 assert result.output["metadata"]["endpoint_count"] == 1
@pytest.mark.asyncio
async def test_unknown_handler_returns_empty(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """handler_name 未匹配到任何 Endpoint → 空 callers + message 提示。"""
 from agents.tools.find_api_callers import find_api_callers
 _patch_endpoint_values_list(monkeypatch, )
 result = await find_api_callers(
 handler_name="NonExistentHandler",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 data = result.output["data"]
 assert data["callers"] ==
 assert "未找到 handler_name" in data["message"]
@pytest.mark.asyncio
async def test_no_cross_repo_calls_returns_empty(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """endpoint 存在但无 CrossRepoApiCall 记录 → 空 callers + message 提示。"""
 from agents.tools.find_api_callers import find_api_callers
 _patch_endpoint_values_list(monkeypatch, ["ep-uuid-1"])
 _patch_cross_repo_select(monkeypatch, )
 result = await find_api_callers(
 handler_name="OrphanHandler",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 data = result.output["data"]
 assert data["callers"] ==
 assert "暂无跨仓前端调用记录" in data["message"]
@pytest.mark.asyncio
async def test_multiple_call_sites_returned_sorted(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """多个 call site → 按 (caller_file, line_number) 升序返回。"""
 from agents.tools.find_api_callers import find_api_callers
 _patch_endpoint_values_list(monkeypatch, ["ep-uuid-1"])
 _patch_cross_repo_select(
 monkeypatch,
 [
 _make_cross_call(caller_file="z/late.ts", line_number=1),
 _make_cross_call(caller_file="a/early.ts", line_number=200),
 _make_cross_call(caller_file="a/early.ts", line_number=10),
 ],
 )
 result = await find_api_callers(
 handler_name="MultiCallerHandler",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 callers = result.output["data"]["callers"]
 files_lines = [(c["caller_file"], c["line_number"]) for c in callers]
 assert files_lines == [
 ("a/early.ts", 10),
 ("a/early.ts", 200),
 ("z/late.ts", 1),
 ]
@pytest.mark.asyncio
async def test_match_confidence_passed_through(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """match_confidence 三档 (1.0/0.7/0.4) 必须原样透传，不被丢弃。"""
 from agents.tools.find_api_callers import find_api_callers
 _patch_endpoint_values_list(monkeypatch, ["ep-uuid-1"])
 _patch_cross_repo_select(
 monkeypatch,
 [
 _make_cross_call(caller_file="a.ts", line_number=1, match_confidence=1.0),
 _make_cross_call(caller_file="b.ts", line_number=2, match_confidence=0.7),
 _make_cross_call(caller_file="c.ts", line_number=3, match_confidence=0.4),
 ],
 )
 result = await find_api_callers(
 handler_name="ConfidenceHandler",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is True
 confidences = [c["match_confidence"] for c in result.output["data"]["callers"]]
 assert confidences == [1.0, 0.7, 0.4]
@pytest.mark.asyncio
async def test_missing_repository_id_returns_error -> None:
 """repository_id=None → ToolResult.error。"""
 from agents.tools.find_api_callers import find_api_callers
 result = await find_api_callers(handler_name="Foo", repository_id=None)
 assert result.success is False
 assert result.error is not None
 assert "repository_id is required" in result.error
@pytest.mark.asyncio
async def test_missing_handler_name_returns_error -> None:
 """handler_name=None / 空 → ToolResult.error。"""
 from agents.tools.find_api_callers import find_api_callers
 result = await find_api_callers(handler_name=None, repository_id=_VALID_REPO_ID)
 assert result.success is False
 assert result.error is not None
 assert "handler_name is required" in result.error
@pytest.mark.asyncio
async def test_orm_value_error_returns_toolresult(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 """ORM 抛 ValueError → tool 层兜底返结构化 error 不冒泡。"""
 from agents.tools.find_api_callers import find_api_callers
 def _raise(*_a: object, **_kw: object) -> None:
 raise ValueError("badly formed UUID")
 objects_mock = MagicMock
 objects_mock.filter = MagicMock(side_effect=_raise)
 from codegraph import models as cg_models
 monkeypatch.setattr(cg_models.Endpoint, "objects", objects_mock)
 result = await find_api_callers(
 handler_name="Foo",
 repository_id=_VALID_REPO_ID,
 )
 assert result.success is False
 assert result.error is not None
 assert "invalid input or downstream failure" in result.error

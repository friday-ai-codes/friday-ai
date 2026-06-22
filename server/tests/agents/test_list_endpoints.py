"""``list_endpoints`` MCP tool 单元测试 —— per implementation Task 8 / work item。

测试目标（≥6 cases）：

1. ``test_returns_sorted_by_method_then_path`` —— ORM order_by 参数透传契约
2. ``test_total_count_returned`` —— acount 返回值进入 metadata.total
3. ``test_empty_repo_returns_empty_list`` —— 空仓库 → empty + message 提示
4. ``test_limit_default_200`` —— 不传 limit 默认 200
5. ``test_limit_capped_at_maximum`` —— limit > 1000 → Pydantic 校验失败 → ToolResult.error
6. ``test_limit_below_minimum_returns_error`` —— limit < 1 → ToolResult.error
7. ``test_missing_repository_id_returns_error`` —— repository_id 必填守卫
8. ``test_truncated_metadata_flag`` —— total > limit 时 truncated=True

per implementation 测试模式：mock ``Endpoint.objects``。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

_VALID_REPO_ID = "55555555-5555-5555-5555-555555555555"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _AsyncIter:
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


def _patch_endpoint_list_query(
    monkeypatch: pytest.MonkeyPatch,
    *,
    items: list[dict[str, Any]],
    total: int,
) -> dict[str, MagicMock]:
    """patch ``Endpoint.objects.filter(...).acount()`` 与
    ``Endpoint.objects.filter(...).order_by(...).values(...)[:N]`` 链。

    ``Endpoint.objects.filter`` 被调用两次（acount 一次 + 列表一次），返回不同 mock。
    """
    # acount 分支
    acount_filter_mock = MagicMock()
    acount_filter_mock.acount = AsyncMock(return_value=total)

    # 列表分支：filter().order_by().values()[:N]
    values_iter = _AsyncIter(items)
    values_slice_mock = MagicMock()
    values_slice_mock.__getitem__ = MagicMock(return_value=values_iter)
    order_by_mock = MagicMock()
    order_by_mock.values = MagicMock(return_value=values_slice_mock)
    list_filter_mock = MagicMock()
    list_filter_mock.order_by = MagicMock(return_value=order_by_mock)

    objects_mock = MagicMock()
    # 两次 filter 返回不同结果（acount 第 1 次，列表第 2 次）
    objects_mock.filter = MagicMock(side_effect=[acount_filter_mock, list_filter_mock])

    from codegraph import models as cg_models

    monkeypatch.setattr(cg_models.Endpoint, "objects", objects_mock)
    return {
        "objects": objects_mock,
        "order_by_method": list_filter_mock.order_by,
        "values_method": order_by_mock.values,
        "values_slice": values_slice_mock,
    }


def _make_endpoint_dict(
    method: str = "GET",
    path: str = "/api/v1/users",
    handler: str = "ListUsersHandler",
    file_path: str = "internal/handlers/user.go",
    line_number: int = 10,
) -> dict[str, Any]:
    return {
        "http_method": method,
        "url_path": path,
        "handler_name": handler,
        "file_path": file_path,
        "line_number": line_number,
    }


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_sorted_by_method_then_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``order_by('http_method', 'url_path')`` 透传给 ORM。"""
    from agents.tools.list_endpoints import list_endpoints

    mocks = _patch_endpoint_list_query(
        monkeypatch,
        items=[
            _make_endpoint_dict("GET", "/api/v1/orders"),
            _make_endpoint_dict("POST", "/api/v1/orders"),
        ],
        total=2,
    )

    result = await list_endpoints(repository_id=_VALID_REPO_ID, limit=10)

    assert result.success is True
    mocks["order_by_method"].assert_called_once()
    args = mocks["order_by_method"].call_args.args
    # 透传 method 与 path 两键
    assert "http_method" in args
    assert "url_path" in args


@pytest.mark.asyncio
async def test_total_count_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """metadata.total 来自 acount，不被 limit 截断。"""
    from agents.tools.list_endpoints import list_endpoints

    _patch_endpoint_list_query(
        monkeypatch,
        items=[_make_endpoint_dict()],
        total=999,
    )

    result = await list_endpoints(repository_id=_VALID_REPO_ID, limit=1)

    assert result.success is True
    data = result.output["data"]
    assert data["total"] == 999
    assert result.output["metadata"]["total"] == 999
    assert result.output["metadata"]["returned"] == 1
    assert result.output["metadata"]["truncated"] is True


def _patch_symbol_count(monkeypatch: pytest.MonkeyPatch, *, count: int) -> None:
    """patch ``Symbol.objects.filter(...).acount()`` 返回指定符号数。"""
    filter_mock = MagicMock()
    filter_mock.acount = AsyncMock(return_value=count)
    objects_mock = MagicMock()
    objects_mock.filter = MagicMock(return_value=filter_mock)

    from codegraph import models as cg_models

    monkeypatch.setattr(cg_models.Symbol, "objects", objects_mock)


@pytest.mark.asyncio
async def test_empty_repo_with_codegraph_built_clarifies_no_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codegraph 已构建（symbol>0）但无 endpoint → message 明确「不代表 codegraph 未跑」。

    回归：原文案「需先运行 codegraph 索引」会误导 Agent 得出 codegraph 未跑的结论。
    """
    from agents.tools.list_endpoints import list_endpoints

    _patch_endpoint_list_query(monkeypatch, items=[], total=0)
    _patch_symbol_count(monkeypatch, count=12678)

    result = await list_endpoints(repository_id=_VALID_REPO_ID)

    assert result.success is True
    data = result.output["data"]
    assert data["endpoints"] == []
    assert data["total"] == 0
    # 不再误导为「codegraph 未跑」，而是说明已构建但无端点
    assert "codegraph 已构建" in data["message"]
    assert "未提取到任何 HTTP 端点" in data["message"]
    assert result.output["metadata"]["codegraph_built"] is True
    assert result.output["metadata"]["symbol_count"] == 12678


@pytest.mark.asyncio
async def test_empty_repo_without_codegraph_says_not_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """codegraph 未构建（symbol=0）且无 endpoint → message 明确尚未构建。"""
    from agents.tools.list_endpoints import list_endpoints

    _patch_endpoint_list_query(monkeypatch, items=[], total=0)
    _patch_symbol_count(monkeypatch, count=0)

    result = await list_endpoints(repository_id=_VALID_REPO_ID)

    assert result.success is True
    data = result.output["data"]
    assert data["endpoints"] == []
    assert "codegraph 索引尚未构建" in data["message"]
    assert result.output["metadata"]["codegraph_built"] is False


@pytest.mark.asyncio
async def test_limit_default_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """不传 limit → Pydantic schema 默认 200，进入 slice [:200]。"""
    from agents.tools.list_endpoints import list_endpoints

    mocks = _patch_endpoint_list_query(
        monkeypatch,
        items=[_make_endpoint_dict()],
        total=1,
    )

    result = await list_endpoints(repository_id=_VALID_REPO_ID)

    assert result.success is True
    mocks["values_slice"].__getitem__.assert_called_once()
    slice_arg = mocks["values_slice"].__getitem__.call_args.args[0]
    assert isinstance(slice_arg, slice)
    assert slice_arg.stop == 200


@pytest.mark.asyncio
async def test_limit_capped_at_maximum() -> None:
    """limit=2000（>1000 上限）→ Pydantic ValidationError → ToolResult.error。"""
    from agents.tools.list_endpoints import list_endpoints

    result = await list_endpoints(repository_id=_VALID_REPO_ID, limit=2000)

    assert result.success is False
    assert result.error is not None
    assert "1000" in result.error or "less than or equal" in result.error.lower()


@pytest.mark.asyncio
async def test_limit_below_minimum_returns_error() -> None:
    """limit=0（<1 下限）→ Pydantic ValidationError → ToolResult.error。"""
    from agents.tools.list_endpoints import list_endpoints

    result = await list_endpoints(repository_id=_VALID_REPO_ID, limit=0)

    assert result.success is False
    assert result.error is not None
    assert "greater" in result.error.lower() or "1" in result.error


@pytest.mark.asyncio
async def test_missing_repository_id_returns_error() -> None:
    """repository_id=None / 空 → ToolResult.error。"""
    from agents.tools.list_endpoints import list_endpoints

    result = await list_endpoints(repository_id=None)

    assert result.success is False
    assert result.error is not None
    assert "repository_id is required" in result.error


@pytest.mark.asyncio
async def test_truncated_metadata_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """total <= limit → truncated=False；total > limit → truncated=True。"""
    from agents.tools.list_endpoints import list_endpoints

    _patch_endpoint_list_query(
        monkeypatch,
        items=[_make_endpoint_dict()],
        total=5,
    )

    result = await list_endpoints(repository_id=_VALID_REPO_ID, limit=10)

    assert result.success is True
    assert result.output["metadata"]["truncated"] is False

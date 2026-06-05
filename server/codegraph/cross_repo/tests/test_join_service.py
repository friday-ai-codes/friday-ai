"""offline join service 单测 —— 验证 O(N+M) join 逻辑（work item）。"""

from __future__ import annotations

from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest

from codegraph.cross_repo.join_service import (
    BATCH_SIZE,
    _match_endpoint,
    build_cross_repo_matches,
    build_endpoint_map,
    write_cross_repo_matches,
)
from codegraph.cross_repo.path_normalizer import normalize_url_path


def make_ep_map_simple() -> dict[tuple[str, str], list[str]]:
    """简单的 ep_map fixture。"""
    return {
        ("GET", "/users/:param"): ["ep-1"],
        ("POST", "/orders/:param"): ["ep-2"],
        ("GET", "/api/v1/items"): ["ep-3"],
        ("DELETE", "/repos/:param/:param/branches"): ["ep-4"],
    }


class TestMatchEndpoint:
    """_match_endpoint 单测。

    注意：_match_endpoint 期望已归一化的 norm_path 参数。
    """

    def test_full_match_get(self) -> None:
        ep_map = make_ep_map_simple()
        result = _match_endpoint(normalize_url_path("/users/:id"), "GET", ep_map)
        assert result == [("ep-1", 1.0)]

    def test_full_match_post(self) -> None:
        ep_map = make_ep_map_simple()
        result = _match_endpoint(normalize_url_path("/orders/:id"), "POST", ep_map)
        assert result == [("ep-2", 1.0)]

    def test_path_only_match(self) -> None:
        ep_map = make_ep_map_simple()
        result = _match_endpoint(normalize_url_path("/users/:id"), "POST", ep_map)
        assert len(result) == 1
        assert result[0][0] == "ep-1"
        assert result[0][1] == 0.7

    def test_partial_match_two_segments(self) -> None:
        ep_map = make_ep_map_simple()
        result = _match_endpoint(normalize_url_path("/users/:id/profile"), "GET", ep_map)
        assert len(result) == 1
        assert result[0][0] == "ep-1"
        assert result[0][1] == 0.4

    def test_no_match(self) -> None:
        ep_map = make_ep_map_simple()
        result = _match_endpoint(normalize_url_path("/completely/different/path"), "GET", ep_map)
        assert result == []

    def test_full_match_before_path_only(self) -> None:
        ep_map: dict[tuple[str, str], list[str]] = {
            ("GET", "/users/:param"): ["ep-1"],
            ("POST", "/users/:param"): ["ep-2"],
        }
        result = _match_endpoint(normalize_url_path("/users/:id"), "GET", ep_map)
        assert result == [("ep-1", 1.0)]

    def test_exact_path_multiple_endpoints(self) -> None:
        ep_map: dict[tuple[str, str], list[str]] = {
            ("GET", "/users/:param"): ["ep-1", "ep-2"],
        }
        result = _match_endpoint(normalize_url_path("/users/:id"), "GET", ep_map)
        assert len(result) == 2
        assert all(conf == 1.0 for _, conf in result)

    def test_partial_match_needs_two_segments(self) -> None:
        ep_map: dict[tuple[str, str], list[str]] = {
            ("GET", "/users"): ["ep-single"],
        }
        # 只有 1 segment：不触发前缀匹配
        result = _match_endpoint(normalize_url_path("/users/detail"), "POST", ep_map)
        assert result == []


class TestBuildCrossRepoMatches:
    """build_cross_repo_matches 单测（mock ORM）。

    两阶段实现：先预建 call_site_map，再遍历 wrapper。
    """

    @patch("codegraph.cross_repo.join_service.ApiCallSite")
    @patch("codegraph.cross_repo.join_service.ApiWrapper")
    def test_returns_records_for_matching_wrapper(
        self, mock_apiw_cls: MagicMock, mock_cs_cls: MagicMock
    ) -> None:
        ep_map: dict[tuple[str, str], list[str]] = {("GET", "/users/:param"): ["ep-1"]}

        mock_wrapper = MagicMock()
        mock_wrapper.id = "w-1"
        mock_wrapper.http_method = "GET"
        mock_wrapper.url_path_pattern = "/users/:id"

        mock_apiw_cls.objects.all.return_value.values_list.return_value = ["w-1"]
        mock_apiw_cls.objects.all.return_value.only.return_value.iterator.return_value = iter(
            [mock_wrapper]
        )

        # 模拟 ApiCallSite 查询返回一条 call_site
        mock_cs_cls.objects.filter.return_value.values.return_value.iterator.return_value = iter(
            [{"id": "cs-1", "api_wrapper_id": "w-1"}]
        )

        records = build_cross_repo_matches(ep_map)
        assert len(records) == 1
        assert records[0].match_confidence == 1.0

    @patch("codegraph.cross_repo.join_service.ApiCallSite")
    @patch("codegraph.cross_repo.join_service.ApiWrapper")
    def test_no_records_for_non_matching_wrapper(
        self, mock_apiw_cls: MagicMock, mock_cs_cls: MagicMock
    ) -> None:
        ep_map: dict[tuple[str, str], list[str]] = {("GET", "/orders/:param"): ["ep-2"]}

        mock_wrapper = MagicMock()
        mock_wrapper.id = "w-1"
        mock_wrapper.http_method = "GET"
        mock_wrapper.url_path_pattern = "/completely/different"

        mock_apiw_cls.objects.all.return_value.values_list.return_value = ["w-1"]
        mock_apiw_cls.objects.all.return_value.only.return_value.iterator.return_value = iter(
            [mock_wrapper]
        )
        mock_cs_cls.objects.filter.return_value.values.return_value.iterator.return_value = iter(
            [{"id": "cs-1", "api_wrapper_id": "w-1"}]
        )

        records = build_cross_repo_matches(ep_map)
        assert records == []

    @patch("codegraph.cross_repo.join_service.ApiCallSite")
    @patch("codegraph.cross_repo.join_service.ApiWrapper")
    def test_multiple_call_sites_produce_multiple_records(
        self, mock_apiw_cls: MagicMock, mock_cs_cls: MagicMock
    ) -> None:
        ep_map: dict[tuple[str, str], list[str]] = {("GET", "/users/:param"): ["ep-1"]}

        mock_wrapper = MagicMock()
        mock_wrapper.id = "w-1"
        mock_wrapper.http_method = "GET"
        mock_wrapper.url_path_pattern = "/users/:id"

        mock_apiw_cls.objects.all.return_value.values_list.return_value = ["w-1"]
        mock_apiw_cls.objects.all.return_value.only.return_value.iterator.return_value = iter(
            [mock_wrapper]
        )
        mock_cs_cls.objects.filter.return_value.values.return_value.iterator.return_value = iter(
            [
                {"id": "cs-1", "api_wrapper_id": "w-1"},
                {"id": "cs-2", "api_wrapper_id": "w-1"},
            ]
        )

        records = build_cross_repo_matches(ep_map)
        assert len(records) == 2


class TestWriteCrossRepoMatches:
    """write_cross_repo_matches 单测（mock bulk_create）。"""

    def test_empty_records_returns_zero(self) -> None:
        result = write_cross_repo_matches([])
        assert result == 0

    @patch("codegraph.cross_repo.join_service.transaction")
    @patch("codegraph.cross_repo.join_service.CrossRepoApiCall")
    def test_calls_bulk_create(self, mock_cross: MagicMock, mock_txn: MagicMock) -> None:
        mock_txn.atomic.return_value.__enter__ = MagicMock(return_value=None)
        mock_txn.atomic.return_value.__exit__ = MagicMock(return_value=False)

        mock_record = MagicMock()
        mock_cross.objects.bulk_create.return_value = [mock_record]

        result = write_cross_repo_matches([mock_record])
        assert result == 1
        mock_cross.objects.bulk_create.assert_called_once()

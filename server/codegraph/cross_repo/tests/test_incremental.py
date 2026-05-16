"""增量更新单测 —— 验证 update_for_wrapper 只更新受影响记录。"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
class TestUpdateForWrapper:
 """update_for_wrapper 单测。"""
 @patch("codegraph.cross_repo.incremental.build_endpoint_map")
 @patch("codegraph.cross_repo.incremental._match_endpoint")
 @patch("codegraph.cross_repo.incremental.ApiWrapper")
 @patch("codegraph.cross_repo.incremental.CrossRepoApiCall")
 def test_deletes_old_and_creates_new(
 self,
 mock_cross_cls: MagicMock,
 mock_apiw_cls: MagicMock,
 mock_match: MagicMock,
 mock_build_map: MagicMock,
 ) -> None:
 from codegraph.cross_repo.incremental import update_for_wrapper
 mock_wrapper = MagicMock
 mock_wrapper.http_method = "GET"
 mock_wrapper.url_path_pattern = "/users/:id"
 mock_wrapper.call_sites.values_list.return_value = ["cs-1"]
 mock_apiw_cls.DoesNotExist = LookupError
 mock_apiw_cls.objects.prefetch_related.return_value.get.return_value = mock_wrapper
 mock_build_map.return_value = {}
 mock_match.return_value = [("ep-1", 1.0)]
 mock_cross_cls.objects.filter.return_value.delete.return_value = (1, {})
 mock_cross_cls.objects.bulk_create.return_value =
 with patch("codegraph.cross_repo.incremental.transaction") as mock_txn:
 mock_txn.atomic.return_value.__enter__ = MagicMock(return_value=None)
 mock_txn.atomic.return_value.__exit__ = MagicMock(return_value=False)
 result = update_for_wrapper("wrapper-uuid")
 assert result == 1
 @patch("codegraph.cross_repo.incremental.ApiWrapper")
 def test_wrapper_not_found_returns_zero(self, mock_apiw_cls: MagicMock) -> None:
 from codegraph.cross_repo.incremental import update_for_wrapper
 mock_apiw_cls.DoesNotExist = LookupError
 mock_apiw_cls.objects.prefetch_related.return_value.get.side_effect = (
 mock_apiw_cls.DoesNotExist("not found")
 )
 result = update_for_wrapper("nonexistent-uuid")
 assert result == 0
 @patch("codegraph.cross_repo.incremental.build_endpoint_map")
 @patch("codegraph.cross_repo.incremental.ApiWrapper")
 def test_no_call_sites_returns_zero(
 self,
 mock_apiw_cls: MagicMock,
 mock_build_map: MagicMock,
 ) -> None:
 from codegraph.cross_repo.incremental import update_for_wrapper
 mock_wrapper = MagicMock
 mock_wrapper.call_sites.values_list.return_value = # 空 call_site
 mock_apiw_cls.DoesNotExist = LookupError
 mock_apiw_cls.objects.prefetch_related.return_value.get.return_value = mock_wrapper
 result = update_for_wrapper("wrapper-no-sites")
 assert result == 0
 mock_build_map.assert_not_called
 @patch("codegraph.cross_repo.incremental.build_endpoint_map")
 @patch("codegraph.cross_repo.incremental._match_endpoint")
 @patch("codegraph.cross_repo.incremental.ApiWrapper")
 @patch("codegraph.cross_repo.incremental.CrossRepoApiCall")
 def test_no_matches_creates_zero_records(
 self,
 mock_cross_cls: MagicMock,
 mock_apiw_cls: MagicMock,
 mock_match: MagicMock,
 mock_build_map: MagicMock,
 ) -> None:
 from codegraph.cross_repo.incremental import update_for_wrapper
 mock_wrapper = MagicMock
 mock_wrapper.http_method = "GET"
 mock_wrapper.url_path_pattern = "/no/match/path"
 mock_wrapper.call_sites.values_list.return_value = ["cs-1"]
 mock_apiw_cls.DoesNotExist = LookupError
 mock_apiw_cls.objects.prefetch_related.return_value.get.return_value = mock_wrapper
 mock_build_map.return_value = {}
 mock_match.return_value =
 mock_cross_cls.objects.filter.return_value.delete.return_value = (0, {})
 with patch("codegraph.cross_repo.incremental.transaction") as mock_txn:
 mock_txn.atomic.return_value.__enter__ = MagicMock(return_value=None)
 mock_txn.atomic.return_value.__exit__ = MagicMock(return_value=False)
 result = update_for_wrapper("wrapper-no-match")
 assert result == 0
class TestUpdateForEndpoint:
 """update_for_endpoint 单测。"""
 @patch("codegraph.cross_repo.incremental.Endpoint")
 def test_endpoint_not_found_returns_zero(self, mock_ep_cls: MagicMock) -> None:
 from codegraph.cross_repo.incremental import update_for_endpoint
 mock_ep_cls.DoesNotExist = LookupError
 mock_ep_cls.objects.get.side_effect = mock_ep_cls.DoesNotExist("not found")
 result = update_for_endpoint("nonexistent-ep")
 assert result == 0

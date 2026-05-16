"""match_confidence 评分单测 —— 3 档评分 + 边界 case。"""
import pytest
from codegraph.cross_repo.confidence import (
 ANY_METHOD,
 MIN_CONFIDENCE,
 compute_confidence,
 passes_threshold,
)
class TestFullMatch:
 """1.0 完全匹配场景。"""
 def test_exact_method_and_path(self) -> None:
 assert compute_confidence("GET", "/users/:id", "GET", "/users/<int:pk>") == 1.0
 def test_exact_fastapi_to_express(self) -> None:
 assert compute_confidence("POST", "/orders/{id}", "POST", "/orders/:id") == 1.0
 def test_case_insensitive_method(self) -> None:
 assert compute_confidence("get", "/users/:id", "GET", "/users/{id}") == 1.0
 def test_exact_with_multiple_params(self) -> None:
 result = compute_confidence(
 "GET", "/repos/:owner/:repo/commits",
 "GET", "/repos/{owner}/{repo}/commits",
 )
 assert result == 1.0
 def test_any_method_wrapper_full_path(self) -> None:
 assert compute_confidence(ANY_METHOD, "/users/:id", "GET", "/users/{user_id}") == 1.0
 def test_delete_method_match(self) -> None:
 assert compute_confidence("DELETE", "/items/{id}", "DELETE", "/items/:id") == 1.0
class TestPathOnlyMatch:
 """0.7 path-only 匹配场景。"""
 def test_different_method_same_path(self) -> None:
 assert compute_confidence("POST", "/users/{id}", "GET", "/users/:id") == 0.7
 def test_put_vs_patch_same_path(self) -> None:
 assert compute_confidence("PUT", "/items/{id}", "PATCH", "/items/<int:pk>") == 0.7
 def test_any_method_endpoint_same_path(self) -> None:
 # ANY method endpoint + 路径相同 → method_match=True → 返回 1.0（完全匹配）
 assert compute_confidence("GET", "/users/:id", ANY_METHOD, "/users/{id}") == 1.0
 def test_delete_vs_get_same_path(self) -> None:
 assert compute_confidence("DELETE", "/users/<pk>", "GET", "/users/:id") == 0.7
class TestPartialMatch:
 """0.4 部分匹配场景（前缀 ≥ 2 segments）。"""
 def test_common_prefix_two_segments(self) -> None:
 result = compute_confidence(
 "GET", "/users/:id/profile",
 "GET", "/users/:id/settings",
 )
 assert result == 0.4
 def test_common_prefix_three_segments(self) -> None:
 result = compute_confidence(
 "GET", "/api/v1/users/:id",
 "GET", "/api/v1/orders/:id",
 )
 assert result == 0.4
 def test_different_method_partial_path(self) -> None:
 result = compute_confidence(
 "POST", "/users/:id/profile",
 "DELETE", "/users/:id/settings",
 )
 assert result == 0.4
 def test_prefix_match_with_normalized_params(self) -> None:
 result = compute_confidence(
 "GET", "/repos/{owner}/{repo}/commits",
 "GET", "/repos/{owner}/{repo}/branches",
 )
 assert result == 0.4
class TestNoMatch:
 """0.0 无匹配场景。"""
 def test_completely_different_paths(self) -> None:
 assert compute_confidence("GET", "/orders", "GET", "/users") == 0.0
 def test_single_segment_prefix_only(self) -> None:
 assert compute_confidence("GET", "/users", "GET", "/users/:id") == 0.0
 def test_no_common_prefix(self) -> None:
 assert compute_confidence("GET", "/a/b/c", "GET", "/x/y/z") == 0.0
 def test_one_segment_paths_different(self) -> None:
 assert compute_confidence("GET", "/users", "GET", "/orders") == 0.0
class TestThreshold:
 """passes_threshold 辅助函数测试。"""
 def test_min_confidence_value(self) -> None:
 assert MIN_CONFIDENCE == 0.4
 @pytest.mark.parametrize(
 "confidence, expected",
 [
 (1.0, True),
 (0.7, True),
 (0.4, True),
 (0.3, False),
 (0.0, False),
 ],
 )
 def test_passes_threshold(self, confidence: float, expected: bool) -> None:
 assert passes_threshold(confidence) is expected

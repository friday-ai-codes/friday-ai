"""Phase: API_CALLS reason 模板测试。"""
from __future__ import annotations
import pytest
from services.retrieval.find_related import explain_neighbor
def test_api_calls_direction_calls_full_metadata -> None:
 """完整 metadata 应产出符合 格式的 reason。"""
 reason = explain_neighbor(
 "API_CALLS",
 source_file="api/topic.ts",
 target_file="/study-flow/topic/finished",
 metadata={
 "function_symbol": "fetchTopicFinished",
 "caller_file": "api/topic.ts",
 "line_number": 23,
 "http_method": "GET",
 "url_path": "/study-flow/topic/finished",
 "direction": "calls",
 },
 )
 assert "fetchTopicFinished" in reason
 assert "api/topic.ts:23" in reason
 assert "GET" in reason
 assert "/study-flow/topic/finished" in reason
def test_api_calls_direction_called_by -> None:
 reason = explain_neighbor(
 "API_CALLS",
 source_file=None,
 target_file=None,
 metadata={
 "function_symbol": "fetchUser",
 "direction": "called_by",
 },
 )
 assert "called by" in reason.lower
 assert "fetchUser" in reason
def test_api_calls_fallback_no_metadata -> None:
 reason = explain_neighbor("API_CALLS", source_file=None, target_file=None)
 assert reason
 assert len(reason) > 0
def test_api_calls_fallback_empty_metadata -> None:
 reason = explain_neighbor("API_CALLS", source_file=None, target_file=None, metadata={})
 assert reason
def test_api_calls_in_template_registry -> None:
 from services.retrieval.find_related import _TEMPLATE_REGISTRY
 assert "API_CALLS" in _TEMPLATE_REGISTRY
def test_api_calls_without_line_number -> None:
 reason = explain_neighbor(
 "API_CALLS",
 metadata={
 "function_symbol": "fetchData",
 "caller_file": "src/api.ts",
 "http_method": "POST",
 "url_path": "/api/data",
 "direction": "calls",
 },
 )
 assert "fetchData" in reason
 assert "POST" in reason

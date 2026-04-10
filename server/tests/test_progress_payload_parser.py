"""parse_progress_payload 纯函数单元测试（Phase）。
覆盖场景:
- 基本字段解析（phase/progress/message/updated_at）
- coding_progress dict 解析
- details.suggested_commit_message 提取
- details scalar 字段透传
- details 嵌套 dict 不透传
- 保留字段黑名单（progress/coding_progress）不被 details 覆盖
- 非 dict details 防御（None/list/str）
- 空 payload / coding_progress 非 dict 防御
"""
from __future__ import annotations
from typing import Any
# 注意：parse_progress_payload 在 Task 2 创建前此 import 会 ImportError — 这是 RED 期预期行为
from orchestration.progress_payload import parse_progress_payload
def test_parses_basic_progress_fields -> None:
 """基本字段应规范化到 output['progress'] 嵌套 dict。"""
 payload: dict[str, Any] = {
 "phase": "coding",
 "progress": 0.5,
 "message": "hello",
 }
 output = parse_progress_payload(payload)
 assert isinstance(output["progress"], dict)
 assert output["progress"]["phase"] == "coding"
 assert output["progress"]["progress"] == 0.5
 assert output["progress"]["message"] == "hello"
 assert "updated_at" in output["progress"]
def test_parses_coding_progress_field -> None:
 """coding_progress 为 dict 时应规范化到 output['coding_progress']。"""
 payload: dict[str, Any] = {
 "coding_progress": {
 "modified_files": ["a.py"],
 "recent_tool_calls": [{"tool": "Read"}],
 }
 }
 output = parse_progress_payload(payload)
 assert "coding_progress" in output
 assert output["coding_progress"]["modified_files"] == ["a.py"]
 assert output["coding_progress"]["recent_tool_calls"] == [{"tool": "Read"}]
 assert "updated_at" in output["coding_progress"]
def test_extracts_suggested_commit_message_from_details -> None:
 """details.suggested_commit_message 必须透传到 output 顶层（G1 阻塞前置条件）。"""
 payload: dict[str, Any] = {
 "details": {"suggested_commit_message": "feat: add auth"},
 }
 output = parse_progress_payload(payload)
 assert output["suggested_commit_message"] == "feat: add auth"
def test_details_scalar_fields_passthrough -> None:
 """details 中的 scalar 字段（str/int/float/bool）应透传到 output 顶层。"""
 payload: dict[str, Any] = {
 "details": {"foo": "bar", "count": 42, "enabled": True},
 }
 output = parse_progress_payload(payload)
 assert output["foo"] == "bar"
 assert output["count"] == 42
 assert output["enabled"] is True
def test_details_nested_dict_not_passthrough -> None:
 """details 中的嵌套 dict 不应透传到 output 顶层（避免跨字段语义耦合）。"""
 payload: dict[str, Any] = {
 "details": {"nested": {"key": "value"}},
 }
 output = parse_progress_payload(payload)
 assert "nested" not in output
def test_details_reserved_key_blacklist_not_overwrite_progress -> None:
 """保留字段黑名单：details 中的 progress/coding_progress key 不得覆盖 output 顶层的 nested dict。"""
 payload: dict[str, Any] = {
 "phase": "coding",
 "progress": 0.3,
 "details": {
 "progress": 0.99, # 恶意 scalar 覆盖企图
 "coding_progress": "should_not_leak",
 },
 }
 output = parse_progress_payload(payload)
 # output["progress"] 必须仍为 dict（未被 details.progress float 覆盖）
 assert isinstance(output["progress"], dict)
 assert "phase" in output["progress"]
 assert output["progress"]["phase"] == "coding"
 # coding_progress 作为保留字段，details 中的同名 scalar 不得出现在顶层
 # （由于原 payload 未提供 coding_progress，output 顶层不应出现此 key）
 assert "coding_progress" not in output or isinstance(output.get("coding_progress"), dict)
def test_details_non_dict_defensive -> None:
 """details 为非 dict 类型（str/list）时，函数不崩溃且不透传任何 scalar。"""
 # 字符串 details
 output_str = parse_progress_payload({"details": "this is a string not a dict"})
 assert isinstance(output_str["progress"], dict)
 assert "suggested_commit_message" not in output_str
 # list details
 output_list = parse_progress_payload({"details": [1, 2, 3]})
 assert isinstance(output_list["progress"], dict)
 assert "suggested_commit_message" not in output_list
def test_details_none_safe -> None:
 """details 为 None 时函数不崩溃。"""
 output = parse_progress_payload({"details": None})
 assert isinstance(output["progress"], dict)
def test_empty_payload_returns_valid_structure -> None:
 """空 payload 返回带默认值的 progress dict。"""
 output = parse_progress_payload({})
 assert "progress" in output
 assert isinstance(output["progress"], dict)
 assert output["progress"]["phase"] == ""
 assert output["progress"]["progress"] == 0.0
 assert output["progress"]["message"] == ""
 assert "updated_at" in output["progress"]
def test_coding_progress_non_dict_skipped -> None:
 """coding_progress 为非 dict（str）时应被忽略，output 不含此 key。"""
 output = parse_progress_payload({"coding_progress": "not-a-dict"})
 assert "coding_progress" not in output

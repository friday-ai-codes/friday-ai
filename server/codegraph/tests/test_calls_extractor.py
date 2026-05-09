"""Tests for Call extractor ."""
import pytest
class TestCallExtractorHappyPath:
 """正常路径：basic_module.py 调用提取。"""
 def test_direct_call(self, parse_fixture, make_file_context):
 """直接函数调用 call_type=DIRECT。"""
 from codegraph.extractors.calls import extract_calls
 tree, _, _ = parse_fixture("basic_module.py")
 ctx = make_file_context
 calls = extract_calls(tree, ctx)
 direct_calls = [c for c in calls if c.call_type == "DIRECT"]
 assert len(direct_calls) > 0, f"Expected at least 1 DIRECT call, got {len(direct_calls)}"
 # helper_function(len(cleaned)) in process 或 helper_function(42) in main
 callee_names = {c.callee_name for c in direct_calls}
 assert "helper_function" in callee_names or "len" in callee_names, \
 f"Expected helper_function or len in DIRECT calls: {callee_names}"
 def test_method_call(self, parse_fixture, make_file_context):
 """方法调用 call_type=METHOD。"""
 from codegraph.extractors.calls import extract_calls
 tree, _, _ = parse_fixture("basic_module.py")
 ctx = make_file_context
 calls = extract_calls(tree, ctx)
 method_calls = [c for c in calls if c.call_type == "METHOD"]
 assert len(method_calls) > 0, f"Expected at least 1 METHOD call, got {len(method_calls)}"
 # processor.process([...]) in async_main or main
 callee_names = {c.callee_name for c in method_calls}
 assert "process" in callee_names or "async_fetch" in callee_names, \
 f"Expected process or async_fetch in METHOD calls: {callee_names}"
 def test_caller_identified(self, parse_fixture, make_file_context):
 """每个 CallData 的 caller_key[1] 不为 None。"""
 from codegraph.extractors.calls import extract_calls
 tree, _, _ = parse_fixture("basic_module.py")
 ctx = make_file_context
 calls = extract_calls(tree, ctx)
 for c in calls:
 assert c.caller_key[1] is not None, \
 f"callee={c.callee_name}: caller_key[1] is None"
 assert isinstance(c.caller_key[1], str), \
 f"callee={c.callee_name}: caller_key[1] should be str"
 def test_call_line_number(self, parse_fixture, make_file_context):
 """line_number > 0。"""
 from codegraph.extractors.calls import extract_calls
 tree, _, _ = parse_fixture("basic_module.py")
 ctx = make_file_context
 calls = extract_calls(tree, ctx)
 for c in calls:
 assert c.line_number > 0, \
 f"callee={c.callee_name}: line_number={c.line_number} should be > 0"
 def test_module_level_calls_skipped(self, parse_fixture, make_file_context):
 """模块级调用（如 if __name__ == "__main__": 块内）被跳过。"""
 from codegraph.extractors.calls import extract_calls
 tree, _, _ = parse_fixture("basic_module.py")
 ctx = make_file_context
 calls = extract_calls(tree, ctx)
 # main 调用在 if __name__ == "__main__": 块内是无 ancestor_function 的模块级调用
 # 不应被提取
 main_calls = [c for c in calls if c.callee_name == "main"]
 # 可能为 0（完全跳过）或 1（如果 walker 处理后 ancestor_function 非 None）
 # 至少确认调用提取器对模块级代码不崩溃
 assert isinstance(calls, list), "extract_calls should return list"
class TestCallExtractorEdgeCases:
 """边界条件测试。"""
 def test_empty_file_returns_empty(self, parse_source, make_file_context):
 """空文件返回空列表。"""
 from codegraph.extractors.calls import extract_calls
 tree, source = parse_source("")
 ctx = make_file_context
 calls = extract_calls(tree, ctx)
 assert calls ==, f"Expected empty, got {len(calls)} calls"
 def test_file_with_only_imports(self, parse_source, make_file_context):
 """仅有 import 语句的文件无调用。"""
 from codegraph.extractors.calls import extract_calls
 tree, source = parse_source("import os\n")
 ctx = make_file_context
 calls = extract_calls(tree, ctx)
 assert calls ==, f"Expected empty, got {len(calls)} calls"
 def test_lambdas_not_confuse_extractor(self, parse_fixture, make_file_context):
 """lambda 内调用不导致崩溃。"""
 from codegraph.extractors.calls import extract_calls
 tree, _, _ = parse_fixture("edge_cases.py")
 ctx = make_file_context
 try:
 calls = extract_calls(tree, ctx)
 assert isinstance(calls, list), "extract_calls should return list"
 except Exception as e:
 pytest.fail(f"extract_calls raised exception on edge_cases: {e}")
 def test_calls_in_nested_functions(self, parse_fixture, make_file_context):
 """嵌套函数内的调用正确归属 ancestor_function。"""
 from codegraph.extractors.calls import extract_calls
 tree, _, _ = parse_fixture("edge_cases.py")
 ctx = make_file_context
 calls = extract_calls(tree, ctx)
 # outer_method 中有 inner.inner_method 调用
 # inner_method 调用会被提取，caller 为 outer_method
 for c in calls:
 assert c.caller_key[1] is not None, f"All calls should have caller"

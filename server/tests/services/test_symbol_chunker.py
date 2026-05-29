"""``services.symbol_chunker`` 语言无关切分核心单测。
重点覆盖旧 ``CodeParser._ast_aware_chunk`` 翻车的三类场景：
- class 不被揉进相邻小函数的合并组（旧实现核心 bug）；
- 大符号按行窗口切分、覆盖到尾不丢代码（旧实现 ``[:max_chars]`` 截断丢尾）；
- 类内方法等嵌套符号不重复成顶层 chunk。
"""
from __future__ import annotations
from services.code_chunk import SymbolSpan
from services.symbol_chunker import build_chunks_from_spans, normalize_kind
def _build(spans, content, **kw):
 defaults = dict(file_path="f.py", file_hash="h" * 64, language="python")
 defaults.update(kw)
 return build_chunks_from_spans(spans, content, **defaults)
# ---------------------------------------------------------------------------
# normalize_kind
# ---------------------------------------------------------------------------
def test_normalize_kind_from_node_type -> None:
 assert normalize_kind("function_definition") == "function"
 assert normalize_kind("class_declaration") == "class"
 assert normalize_kind("interface_declaration") == "class"
 assert normalize_kind("type_alias_declaration") == "class"
 assert normalize_kind("method_definition") == "method"
 assert normalize_kind("arrow_function") == "function"
 assert normalize_kind("unknown_node") == "other"
def test_normalize_kind_from_symbol_type_takes_priority -> None:
 # codegraph SymbolData.symbol_type 优先于 node_type
 assert normalize_kind("function_definition", symbol_type="CLASS") == "class"
 assert normalize_kind("", symbol_type="METHOD") == "method"
 assert normalize_kind("", symbol_type="VARIABLE") == "variable"
 assert normalize_kind("", symbol_type="WEIRD") == "other"
# ---------------------------------------------------------------------------
# 基本：一符号一 chunk
# ---------------------------------------------------------------------------
def test_single_symbol_one_chunk -> None:
 content = "def foo:\n return 1\n # padding line to exceed merge"
 span = SymbolSpan("foo", "function", 1, 3, node_type="function_definition")
 chunks = _build([span], content)
 sym_chunks = [c for c in chunks if c.parent_symbol == "foo"]
 assert len(sym_chunks) == 1
 c = sym_chunks[0]
 assert c.node_type == "function_definition"
 assert c.start_line == 1
 assert c.end_line == 3
 assert "def foo" in c.content
# ---------------------------------------------------------------------------
# 核心 bug 修复：class 不被揉进相邻小函数组
# ---------------------------------------------------------------------------
def test_class_not_merged_with_adjacent_small_functions -> None:
 content = "\n".join([
 "def a: pass", # 1
 "def b: pass", # 2
 "class C:", # 3
 " def m(self): pass", # 4
 ])
 spans = [
 SymbolSpan("a", "function", 1, 1, node_type="function_definition"),
 SymbolSpan("b", "function", 2, 2, node_type="function_definition"),
 SymbolSpan("C", "class", 3, 4, node_type="class_definition"),
 ]
 chunks = _build(spans, content)
 class_chunks = [c for c in chunks if c.node_type == "class_definition"]
 assert len(class_chunks) == 1, "class 必须独立成块"
 assert class_chunks[0].parent_symbol == "C"
 merged = [c for c in chunks if c.node_type == "merged_group"]
 assert len(merged) == 1, "a/b 两个小函数应合并为一个组"
 assert merged[0].parent_symbol is not None
 assert "a" in merged[0].parent_symbol and "b" in merged[0].parent_symbol
 # class 名不得出现在合并组里
 assert "C" not in merged[0].parent_symbol
def test_small_functions_merged_into_group -> None:
 content = "\n".join([
 "def a: pass", # 1
 "def b: pass", # 2
 "def c: pass", # 3
 ])
 spans = [
 SymbolSpan("a", "function", 1, 1, node_type="function_definition"),
 SymbolSpan("b", "function", 2, 2, node_type="function_definition"),
 SymbolSpan("c", "function", 3, 3, node_type="function_definition"),
 ]
 chunks = _build(spans, content)
 merged = [c for c in chunks if c.node_type == "merged_group"]
 assert len(merged) == 1
 assert merged[0].start_line == 1
 assert merged[0].end_line == 3
def test_large_function_not_merged_even_if_adjacent -> None:
 # 大函数（>= min_merge_lines 行）不参与合并，独立成块。
 content = "\n".join([f"def a: pass" if i == 0 else f" x{i} = {i}" for i in range(12)])
 spans = [
 SymbolSpan("big", "function", 1, 12, node_type="function_definition"),
 SymbolSpan("small", "function", 13, 13, node_type="function_definition"),
 ]
 content = content + "\ndef small: pass"
 chunks = _build(spans, content, min_merge_lines=10)
 # big 12 行 >= 10 → 不合并
 assert not any(c.node_type == "merged_group" for c in chunks)
 assert any(c.parent_symbol == "big" for c in chunks)
# ---------------------------------------------------------------------------
# 大符号按行窗口切分：不丢尾
# ---------------------------------------------------------------------------
def test_large_symbol_split_covers_full_range_no_truncation -> None:
 # 20 行、每行 ~26 字符 ≈ 520 字符；max_chars=100 → 必然多 part。
 lines = [f"line_{i:02d} xxxxxxxxxxxxxxxxxx" for i in range(1, 21)]
 content = "\n".join(lines)
 span = SymbolSpan("big", "function", 1, 20, node_type="function_definition")
 chunks = _build([span], content, max_chars=100, overlap_lines=2)
 assert len(chunks) > 1, "大符号应被切成多个 part"
 assert chunks[0].start_line == 1
 assert chunks[-1].end_line == 20, "最后一个 part 必须覆盖到尾行（不丢尾）"
 covered: set[int] = set
 for c in chunks:
 covered |= set(range(c.start_line, c.end_line + 1))
 assert covered == set(range(1, 21)), "所有 part 的并集必须完整覆盖 1..20 行"
 # 无 '... (truncated)' 截断标记（旧实现的丢尾标志）
 assert all("truncated" not in c.content for c in chunks)
def test_single_overlong_line_does_not_loop -> None:
 # 单行超长：不得死循环，至少产出一个 chunk。
 content = "x" * 5000
 span = SymbolSpan("huge", "function", 1, 1, node_type="function_definition")
 chunks = _build([span], content, max_chars=100)
 assert len(chunks) >= 1
 assert chunks[0].start_line == 1
# ---------------------------------------------------------------------------
# 嵌套去重：类内方法不重复成顶层
# ---------------------------------------------------------------------------
def test_nested_method_deduped_under_class -> None:
 content = "\n".join([
 "class C:", # 1
 " def m(self):", # 2
 " return 1", # 3
 " # pad", # 4
 " # pad", # 5
 " def n(self):", # 6
 " return 2", # 7
 " # pad", # 8
 " # pad", # 9
 " # pad", # 10
 ])
 spans = [
 SymbolSpan("C", "class", 1, 10, node_type="class_definition"),
 SymbolSpan("m", "method", 2, 5, node_type="method_definition"),
 SymbolSpan("n", "method", 6, 10, node_type="method_definition"),
 ]
 chunks = _build(spans, content)
 # 只有 class C 一个符号 chunk；m/n 被包含、不单独成块
 assert any(c.node_type == "class_definition" and c.parent_symbol == "C" for c in chunks)
 assert not any(c.parent_symbol == "m" for c in chunks)
 assert not any(c.parent_symbol == "n" for c in chunks)
# ---------------------------------------------------------------------------
# 模块级收尾
# ---------------------------------------------------------------------------
def test_module_level_chunk_for_uncovered_lines -> None:
 content = "\n".join([
 "import os", # 1 (uncovered)
 "GLOBAL_CONFIG = {'a': 1}", # 2 (uncovered)
 "", # 3
 "def foo:", # 4 (covered)
 " return GLOBAL_CONFIG", # 5 (covered)
 ])
 spans = [SymbolSpan("foo", "function", 4, 5, node_type="function_definition")]
 chunks = _build(spans, content)
 module_chunks = [c for c in chunks if c.node_type == "module"]
 assert len(module_chunks) == 1
 assert "import os" in module_chunks[0].content
 assert "GLOBAL_CONFIG" in module_chunks[0].content
 assert module_chunks[0].parent_symbol is None
def test_empty_spans_whole_file_becomes_module -> None:
 content = "import os\nCONST = 42\nprint(CONST)\n# meaningful module body here"
 chunks = _build(, content)
 assert len(chunks) >= 1
 assert all(c.node_type == "module" for c in chunks)
def test_pure_comment_module_segment_skipped -> None:
 content = "\n".join([
 "# just a comment", # 1
 "# another comment", # 2
 "def foo:", # 3
 " return 1", # 4
 " # pad pad pad pad pad", # 5
 ])
 spans = [SymbolSpan("foo", "function", 3, 5, node_type="function_definition")]
 chunks = _build(spans, content)
 # 纯注释的模块段（行 1-2）应被跳过（< 20 有意义字符）
 module_chunks = [c for c in chunks if c.node_type == "module"]
 assert module_chunks ==
# ---------------------------------------------------------------------------
# 第二阶段绑定基础：symbol_key 透传
# ---------------------------------------------------------------------------
def test_symbol_key_propagated_to_chunk -> None:
 content = "def foo:\n return 1\n # pad to avoid merge edge"
 span = SymbolSpan(
 "foo", "function", 1, 3, node_type="function_definition",
 symbol_key=("f.py", "foo", 1),
 )
 chunks = _build([span], content)
 sym = next(c for c in chunks if c.parent_symbol == "foo")
 assert sym.symbol_key == ("f.py", "foo", 1)
def test_output_sorted_by_line -> None:
 content = "\n".join(f"line {i}" for i in range(1, 31))
 spans = [
 SymbolSpan("c", "class", 20, 25, node_type="class_definition"),
 SymbolSpan("a", "class", 1, 6, node_type="class_definition"),
 SymbolSpan("b", "class", 10, 15, node_type="class_definition"),
 ]
 chunks = _build(spans, content)
 starts = [c.start_line for c in chunks]
 assert starts == sorted(starts)

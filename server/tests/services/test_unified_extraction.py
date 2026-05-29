"""``services.unified_extraction`` 一次解析双供 + chunk↔symbol 同源绑定测试。
用 Python（``PythonExtractor`` 走纯 tree-sitter，不依赖 gopls / volar LSP 进程）
保证测试稳定，验证：
- 一次调用同时产出 RAG chunks 与 Graph ExtractionBundle；
- chunk 的 ``symbol_key`` 与 bundle.symbols 同源对齐（可直接绑定 Symbol）；
- 不支持语言 / 抽取失败时优雅兜底（module 切分 + 空 bundle）。
"""
from __future__ import annotations
from services.unified_extraction import extract_chunks_and_graph, spans_from_symbols
_PY = (
 "import os\n"
 "GLOBAL = 1\n"
 "def foo(x):\n"
 " return x + 1\n"
 "class Bar:\n"
 " def method(self):\n"
 " return foo(GLOBAL)\n"
)
def test_python_dual_output_chunks_and_graph -> None:
 chunks, bundle = extract_chunks_and_graph(
 "m.py", _PY, "python", "repo-1", file_hash="h" * 64
 )
 # Graph 轨：symbols 含 foo / Bar
 sym_names = {s.name for s in bundle.symbols}
 assert "foo" in sym_names
 assert "Bar" in sym_names
 # RAG 轨：chunks 含符号 chunk
 chunk_syms = {c.parent_symbol for c in chunks if c.parent_symbol}
 assert "foo" in chunk_syms
 assert "Bar" in chunk_syms
def test_chunk_symbol_key_same_source_as_bundle -> None:
 chunks, bundle = extract_chunks_and_graph(
 "m.py", _PY, "python", "repo-1", file_hash="h" * 64
 )
 sym_keys = {(s.file_path, s.name, s.start_line) for s in bundle.symbols}
 bound = [c for c in chunks if c.symbol_key is not None]
 assert bound, "应有 chunk 携带 symbol_key 绑定"
 for c in bound:
 # 每个绑定 chunk 的 symbol_key 必须能在同一次抽取的 symbols 中找到（真正同源）
 assert c.symbol_key in sym_keys
def test_spans_from_symbols_maps_kind_and_key -> None:
 from codegraph.extractors.base import SymbolData
 syms = [
 SymbolData(name="f", symbol_type="FUNCTION", file_path="m.py", start_line=1, end_line=2),
 SymbolData(name="C", symbol_type="CLASS", file_path="m.py", start_line=3, end_line=5),
 SymbolData(name="m", symbol_type="METHOD", file_path="m.py", start_line=4, end_line=5),
 ]
 spans = spans_from_symbols(syms)
 assert [s.kind for s in spans] == ["function", "class", "method"]
 assert spans[0].symbol_key == ("m.py", "f", 1)
 assert spans[1].symbol_key == ("m.py", "C", 3)
def test_unsupported_language_module_fallback -> None:
 chunks, bundle = extract_chunks_and_graph(
 "d.json",
 '{"a": 1, "b": 2, "note": "a reasonably long json value for padding"}\n',
 "json",
 "repo-1",
 file_hash="h" * 64,
 )
 assert bundle.symbols ==
 assert bundle.imports ==
 assert isinstance(chunks, list) # module 兜底或空，不报错
def test_typescript_dual_output_interface_extracted -> None:
 # TS 经 get_extractor 可能走 volar(LSP) 或 lazy fallback 到 tree-sitter；
 # 两种路径都应抽到 interface/function 并产出同源 chunk。
 ts = (
 "export interface User { id: number }\n"
 "export function add(a: number, b: number): number { return a + b }\n"
 )
 chunks, bundle = extract_chunks_and_graph(
 "m.ts", ts, "typescript", "repo-1", file_hash="h" * 64
 )
 sym_names = {s.name for s in bundle.symbols}
 assert "add" in sym_names
 # chunk 与 symbol 同源
 sym_keys = {(s.file_path, s.name, s.start_line) for s in bundle.symbols}
 for c in chunks:
 if c.symbol_key is not None:
 assert c.symbol_key in sym_keys
def test_index_and_rebuild_paths_extract_identical_symbols -> None:
 """"创建索引"路径与"手动重建"兜底路径必须抽出相同的 TS 符号集。
 回归防护（用户实测整库 5608 → 2069）：兜底路径曾用 ``CodeParser`` 的
 JavaScript grammar 解析 TS，丢失 interface/type/enum 等 TS 专属符号。
 两条路径现在都走 ``get_extractor(language).extract``，符号集必须逐一对齐。
 """
 from codegraph.extractors.base import FileContext
 from codegraph.extractors.registry import get_extractor
 ts = (
 "export interface User { id: number; name: string }\n"
 "export type ID = string | number\n"
 "export function add(a: number, b: number): number { return a + b }\n"
 "export class Svc { run: void {} }\n"
 )
 # 路径①「创建索引」来源：unified_extraction（single-parse 缓存供图谱轨复用）
 _, bundle_index = extract_chunks_and_graph(
 "m.ts", ts, "typescript", "repo-1", file_hash="h" * 64
 )
 # 路径②「手动重建」来源：_extract_and_write_graph 的 else 兜底分支等价调用
 ctx = FileContext(
 file_path="m.ts",
 language="typescript",
 repository_id="repo-1",
 module_path="m",
 )
 extractor = get_extractor("typescript")
 assert extractor is not None
 bundle_rebuild = extractor.extract("m.ts", ts, ctx)
 names_index = sorted(s.name for s in bundle_index.symbols)
 names_rebuild = sorted(s.name for s in bundle_rebuild.symbols)
 assert names_index == names_rebuild, (
 f"两条路径符号集不一致：创建索引={names_index} 重建={names_rebuild}"
 )
 # 确保不是"两条路径一致地都为空"——TS 专属符号（interface）必须被抽到，
 # 否则说明又退化成了 JavaScript grammar。
 assert "User" in names_rebuild # interface（旧 JS grammar 下会丢失）
 assert "add" in names_rebuild # function
 assert "Svc" in names_rebuild # class
def test_treesitter_extractor_handles_javascript -> None:
 """javascript 无专用 LanguageExtractor（EXTRACTOR_REGISTRY 未注册），通用
 TreeSitterExtractor 必须能抽到 js 符号。
 图谱兜底据此覆盖 volar 动态注入 BACKEND_REGISTRY 的 javascript / jsx，
 避免 .js 文件被跳过丢符号 + 刷 extractor_not_found 噪声。
 """
 from codegraph.extractors.base import FileContext
 from codegraph.extractors.registry import TreeSitterExtractor
 js = (
 "export function foo(a, b) { return a + b }\n"
 "export class Bar { run { return foo(1, 2) } }\n"
 )
 ctx = FileContext(
 file_path="m.js",
 language="javascript",
 repository_id="repo-1",
 module_path="m",
 )
 bundle = TreeSitterExtractor.extract("m.js", js, ctx)
 names = {s.name for s in bundle.symbols}
 assert "foo" in names
 assert "Bar" in names
